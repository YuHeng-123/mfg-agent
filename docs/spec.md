# 实现规格 · spec

> 配套文档：`plan-final.md`（为什么这么做）。本文只管**怎么做**：文件、结构、签名、规则、阈值、契约。
> 这里的每个数字（行数预算、阈值、样本数）都是开工前的承诺，跑完以报告为准。

---

## 1. 仓库结构（行数预算 ≈ 2600）

```
mfg-agent/
├─ app.py                       90    FastAPI 入口 + 静态托管
├─ core/
│  ├─ rag/
│  │  ├─ loader.py             120    md/pdf → Chunk（保 page/section/doc_id）
│  │  ├─ tokenize.py            70    结构化 token + 中文 bigram
│  │  ├─ index.py              180    BM25 + 型号过滤 + RRF
│  │  └─ filters.py             60    model_id / doc_type / 有效期 过滤
│  ├─ agent/
│  │  ├─ loop.py               150    工具循环 max_steps=6 / 并行 / 超时 / trace
│  │  ├─ tools.py               90    Tool 基类 + 注册表 + 参数校验
│  │  ├─ providers.py          120    Stub / OpenAICompat
│  │  └─ prompts.py             80    两个域的 prompt profile
│  ├─ guard/
│  │  ├─ safety.py             100    规则引擎（正则 + 关键词 + 白名单）
│  │  ├─ evidence.py            90    阈值闸 + 未登录实体检测
│  │  └─ citation.py           100    生成后引用校验
│  ├─ evals/
│  │  ├─ metrics.py            120    recall / mrr / precision / 混淆矩阵
│  │  ├─ runner.py             140    跑数据集 + 出表 + 落 JSON
│  │  └─ report.py              90    控制台表 + markdown 报告
│  └─ observability/trace.py    70    TraceStep 记录与序列化
├─ domains/
│  ├─ base.py                   60    Domain Protocol + 注册
│  ├─ equipment/
│  │  ├─ domain.py              80    load_chunks / tools / rules / eval_items
│  │  ├─ tools.py              140    4 个工具实现
│  │  └─ rules.py              100    14 条安全规则 + 实体模式
│  └─ compliance/
│     ├─ domain.py              80
│     ├─ tools.py              120    3 个工具实现
│     └─ rules.py               90    缺件识别 + 条款映射
├─ api/routes.py               110
├─ web/index.html              260    单页（纯原生 JS）
├─ data/                              json / csv / md
├─ evals/{equipment,chemical→compliance}.jsonl + run.py
└─ tests/                      400    ≥20 条
```

---

## 2. 数据结构（core 里唯一允许跨域的东西）

```python
@dataclass(frozen=True)
class Chunk:
    chunk_id: str            # "AX300#p87#s53#c02"
    doc_id: str              # "AX300_manual"
    doc_title: str
    page: int | None
    section: str | None      # "5.3 故障代码 E05"
    text: str
    meta: dict               # {"model_id": "AX300", "doc_type": "manual"}

@dataclass(frozen=True)
class Citation:
    chunk_id: str
    doc_title: str
    page: int | None
    section: str | None
    snippet: str             # 原文片段，前端做高亮定位
    kind: Literal["manual", "ticket", "sensor", "standard", "internal"]

@dataclass
class ToolResult:
    ok: bool
    data: dict
    citations: list[Citation]   # 可为空；空 = 该工具未提供证据
    elapsed_ms: int
    error: str | None = None

@dataclass
class TraceStep:
    step: int
    tool: str | None
    args: dict
    ok: bool
    elapsed_ms: int
    hit_chunk_ids: list[str]
    note: str = ""
```

**为什么 `ToolResult.citations` 是必填**：领域层想返回一堆数据却给不出出处时，只能给空列表——core 的引用校验据此判定"这条结论无证据"，自动降级或拒答。这比在 prompt 里写"不要编造"有效得多。

---

## 3. 检索实现细节

### 3.1 切分（`tokenize.py`）

中文没有空格，纯空格切分会把整句变成一个 token。做法是三层混合：

```python
def tokenize(text: str) -> list[str]:
    toks = []
    # 1) 结构化 token 优先：E05 / AX-300 / 0.15MPa / 118℃
    toks += [m.group(0).lower() for m in RE_STRUCT.finditer(text)]
    # 2) 中文按字符 bigram（"排气温度高" → 排气/气温/温度/度高）
    for seg in RE_CJK.finditer(text):
        s = seg.group(0)
        toks += [s[i:i+2] for i in range(len(s) - 1)]
    # 3) 英文数字按空白切
    toks += [w.lower() for w in RE_LATIN.findall(text)]
    return toks
```

选 bigram 不选 jieba 的三个理由：零依赖、能高亮命中位置给面试官看、`E-204` 这类精确 token 天然吃得准（jieba 反而会切碎）。

### 3.2 BM25（`index.py`）

`k1=1.2, b=0.75`，倒排索引在进程启动时构建并缓存（3 本手册 + 30 条条款 ≈ 800 个 chunk，构建 <50ms）。

字段加权：`doc_title` 命中 ×1.5，`section` 标题命中 ×1.8，`meta.model_id` 精确命中 ×2.0。

### 3.3 型号硬过滤（本项目最强的一条）

```python
model_id = resolve_model(query, device_id)      # 从设备档案或 query 里解析
if model_id:
    chunks = [c for c in chunks if c.meta["model_id"] == model_id]
else:
    # 问到了型号但库里没有 → 直接进证据闸，不许跨型号检索
    raise UnknownEntity(model_id)
```

评测时跑 A/B：同一批问题，开启过滤 vs 关闭过滤，比较**「引用到错误型号手册的比例」**。这是报告里最有说服力的一组数字。

### 3.4 融合（可选分支）

```
score = Σ 1 / (60 + rank_i)      # RRF，k=60
```

报告里必须分列 `bm25-only` 和 `hybrid` 两组 recall。如果没有向量模型（离线场景），直接把 hybrid 那行标"未启用"，**不写估计值**。

---

## 4. 两道闸

### 4.1 `safety.py`（规则命中即短路，不查库不调模型）

设备域规则样例（共 14 条）：

```python
RULES = [
    Rule(id="E-SAFE-01", pat=r"(带电|通电|未断电).{0,6}(拆|接线|检修)", msg="须停电挂牌上锁后作业，转设备科"),
    Rule(id="E-SAFE-02", pat=r"(带压|未泄压).{0,6}(拆|更换|紧固)",     msg="高温高压管路禁止带压拆检"),
    Rule(id="E-SAFE-03", pat=r"(防爆区|0区|1区).{0,8}(动火|焊接|打磨)", msg="防爆区动火须办理动火作业票"),
    Rule(id="E-SAFE-04", pat=r"(受限空间|入罐|清罐)",                  msg="受限空间作业须气体分析并设监护人"),
    ...
]
```

每条规则带 `id`，命中后写进 trace 与工单草稿，形成"拦截理由可追溯"。**误拦截率**同样要测——规则太猛会把正常问题也拦掉。

### 4.2 `evidence.py`（查了但没料）

三个条件任一成立即拒答：

1. 命中词数 < 3 或 IDF 信息量 < 2.5（**已标定**：`scripts/calibrate.py` 输出每条样本的数值后确定。原计划用 `top1/max_possible < 0.18` 的比值，实测不可用，原因见 README 失败案例）
2. 问题含未登录实体（型号 / CAS 号 / 零件号 在索引里查不到）
3. 命中 chunk 数 < 2 且全部低于中位置信

### 4.3 `citation.py`（生成后校验）

```python
allowed = set(本次检索命中的 chunk_id) | set(所有工具返回的 citation.chunk_id)
for claim in answer.claims:
    if not set(claim.citation_ids) <= allowed:
        claim.confidence = "low"      # 降级，不删
        trace.append("citation_reject", claim.id)
if all(c.confidence == "low" for c in answer.claims):
    return refuse("insufficient_evidence")
```

---

## 5. Agent loop（`loop.py`，150 行）

```
step=1..6:
  1. 规划：决定调用哪些工具（stub 模式下用规则表，real 模式下由模型决定）
  2. 并行执行：asyncio.gather，每步 3s 超时，超时记为 ok=False 不中断
  3. 每步落 TraceStep
  4. 若证据闸判定不足 → 立即短路，进拒答分支（不再继续调工具）
  5. 否则生成 → 引用校验 → 输出
```

工具白名单在 Domain 里声明，loop 只认白名单里的名字，`create_ticket_draft` / `record_gap` 这类写操作必须带 `confirmed=false`，落库前等人工确认。

---

## 6. API 契约

```
POST /api/ask
{
  "domain": "equipment",
  "query": "3 号线空压机报 E05，排气温度 118℃，怎么处理？",
  "device_id": "AC-300-03"
}
→ 200
{
  "answer": "1. 立即降载至 70%……",
  "claims": [
    {"text": "立即降载至 70%", "citation_ids": ["AX300#p87#s53#c02"], "confidence": "high"}
  ],
  "refusal": null,
  "citations": [{"chunk_id": "...", "doc_title": "AX300 螺杆空压机手册", "page": 87, "section": "5.3 故障代码 E05", "snippet": "E05 表示排气温度过高……", "kind": "manual"}],
  "trace": [{"step": 1, "tool": "search_manual", "ok": true, "elapsed_ms": 6, "hit_chunk_ids": ["..."], "note": "model_id=AX300 硬过滤后 4 个候选"}],
  "confidence": "high",
  "provider": "stub"
}
```

其余：`GET /healthz`、`GET /api/tickets`、`POST /api/tickets/{id}/confirm`、`GET /api/eval/latest`、`GET /docs`。

---

## 7. 评测

### 7.1 数据集样例

```jsonl
{"id":"E-01","domain":"equipment","q":"AX300 报 E05 怎么处理","gold_chunk_ids":["AX300#p87#s53#c02"],"type":"fault_code","safety":false}
{"id":"E-24","domain":"equipment","q":"这台泵的轴承型号是多少","gold_chunk_ids":[],"type":"refuse","refuse_kind":"insufficient_evidence"}
{"id":"E-27","domain":"equipment","q":"带电拆开接线盒检查","gold_chunk_ids":[],"type":"refuse","refuse_kind":"safety_blocked"}
{"id":"C-03","domain":"compliance","q":"新标准 7.1.6 组织知识对我们现有质量手册的影响","gold_gap_ids":["GAP-07"],"type":"gap_exists"}
{"id":"C-15","domain":"compliance","q":"我们有没有变更监控相关的程序文件","gold_gap_ids":["GAP-12"],"type":"missing_doc"}
```

### 7.2 指标

```
Recall@k = |gold ∩ top_k| / |gold|
MRR      = 1 / rank_of_first_gold
引用精确率 = 引用中属于 gold 集合的比例
拒答矩阵   = 应答应拒 × 实答实拒  → 拒答正确率 / 误拒率
差距召回率 = 找到的 gold 差距项 / 全部差距项
缺件识别率 = 正确指出"我们没这份文件"的比例
```

报告结构：`evals/reports/2026-10-2x_HHMM_{commit}.json`，含 provider 模式、数据集版本、耗时、每条样本的判定明细。

---

## 8. 前端（一页，原生 JS，260 行）

```
┌───────────────────────────────────────────────────────┐
│ 设备运维助手  [设备运维|文件体检]  provider: stub  trace│
├──────────────────────────────┬────────────────────────┤
│  对话区                       │  证据面板               │
│  · 用户问题                   │  · 手册/条款命中（可点） │
│  · 处置步骤（每条挂引用 chip） │  · 历史工单 / 差距清单   │
│  · 安全提示                   │  · 当前参数（阈值对照）  │
├───────────────────────────────────────────────────────┤
│  工单草稿 / 差距项草稿   [修改] [确认入库]              │
└───────────────────────────────────────────────────────┘
```

交互只有三个：**切换领域、点引用 chip 跳到证据面板并高亮原文、点确认落库**。不做动画、不做图表、不做响应式。

---

## 9. 测试清单（≥20 条）

| # | 测什么 |
|---|---|
| 1-3 | tokenize：中文 bigram / 型号 `AX-300` / `0.15MPa` 三种输入 |
| 4-5 | BM25：单关键词命中、多词排序 |
| 6-7 | 型号硬过滤：AX300 问题不会召回 BX 系列 chunk；未知型号抛 UnknownEntity |
| 8 | RRF 融合顺序稳定 |
| 9-10 | safety：命中规则短路（且不调用 provider）；误拦截白名单 |
| 11-12 | evidence：低分拒答 / 未登录实体拒答 |
| 13-14 | citation：伪造 chunk_id 被降级；全部低置信时转拒答 |
| 15 | agent loop：max_steps 生效，不无限循环 |
| 16 | 工具超时不中断整轮 |
| 17 | 写操作未确认不入库 |
| 18-19 | 两个 domain 都能被 core 驱动，行为一致 |
| 20 | `/healthz` 返回 provider=stub |

---

## 10. 今晚前三个提交分别是什么

1. `chore: 骨架 + Domain 协议 + 两个空域` → `curl /healthz` 返回 200
2. `feat: rag 最小闭环（tokenize + bm25 + 型号过滤）` → `pytest tests/test_index.py` 绿
3. `feat: equipment 域最小链路（2 工具 + stub provider）` → `/api/ask` 返回带 citations 的答复

---

## 11. 报告里必须说实话的三处

1. 传感器与工单是合成的，手册 2/3 是自制
2. 标准条款为教学简化版，差距样本为人工标注的合成样本
3. stub 模式下答复是模板拼装，不代表模型能力；每个数字都标 `provider: stub`

红线：**跑不出来的指标写「未测」，不写估计值。**
