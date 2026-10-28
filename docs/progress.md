# 进度记录

> 每个阶段做完追加一节。数字全部来自实际运行，不估算。

## P0-1 真实手册接入 · 2026-10-28

**前置检查结果：PDF 不存在。** `data/equipment/manuals/real/` 里只有 `README.md`，
没有 `ATV320_manual.pdf`。按任务书要求跳过本条的实际接入，等待用户用浏览器手动下载
（`download.schneider-electric.com` 有 403 防盗链，AI 侧下不了，也不该反复重试）。

**但通道本身已经跑通并补了测试**——之前只有 README 承诺、没有测试证明，属于"说了没验"：

- 做了什么
  - 把真实手册元数据的读取从「模块加载时合并一次」改成函数 `real_meta()` / `manual_meta()`，
    每次调用重读 `real/_meta.json`；换手册不必重启进程（但索引缓存仍需显式失效，见下）。
  - 新增 `manual_path(doc_id)`：先找 `manuals/`，再找 `manuals/real/`。
  - `chunks()`、`resolve_model()`、未知型号检测全部改走合并后的清单。
  - 新增 `tests/test_data_replace.py`（3 条）：新手册只要「丢 PDF + 写一行 JSON」即可检索；
    只丢 PDF 不登记不会悄悄进索引；`_meta.json` 缺失不算错误。
- 怎么验证的
  ```
  $ python -m pytest tests/test_data_replace.py -q
  3 passed
  $ python -m pytest -q
  67 passed, 1 warning
  $ python -m ruff check .
  All checks passed!
  ```
  测试里现生成一本 `TEST900_manual.pdf`（两页：封面 + 8.1 节），登记后
  `store.chunks()` 出现 `TEST900_manual#p2#s01#c01`，且 `search(..., model_id="TEST900")` 命中——
  证明型号过滤对新手册立刻生效，没改一行代码。
- 数字变化
  - 语料仍为 48 段 / 4 型号（**没有真手册，索引不变**）。
  - 评测数字无变化：Recall@5 96.7%、MRR 0.939、单跳 Recall@1 80.0%
    （报告 `evals/reports/20261028_2016_6fc0845.json`）。
  - 测试 64 → 67。
- 顺手修掉的一处虚报
  - 上一次会话在 README 顶部画了架构图，写的是「向量 + BM25 混合检索 · 交叉编码器重排」。
    **这两样代码里都没有**，属于典型的"图画得比代码好看"。已改成实际情况
    （bigram 分词 + BM25、字段加权、低信息段落降权、型号硬过滤、子句分解），
    并明确写出"没有向量检索、没有重排，原因是离线拉不到 embedding 模型"。
  - 同一张图里还有「型号未知 → 先问型号」，实际行为是退到机型族过滤、再不行全库检索后由证据闸拦。
    一并改成实际行为。
- 遗留问题
  - 等用户提供 `ATV320_manual.pdf` 后，按 README 的 5 步接入，然后本节的数字要重跑补上。
  - 索引缓存不自动失效：换手册后要调 `POST /api/admin/reload`（P1 里实现）。

---

## P0-2 演示材料 · 2026-10-28

- 做了什么
  - `docs/demo.md`：6 个场景（正常处置 / 型号混淆 / 证据不足拒答 / 安全拦截 / 体检域差距 / 多跳），
    每段输出都是**本机实跑的原文**，含服务端耗时、引用页码、拒答理由、trace 行。
  - README 顶部加「30 秒看懂」：一张流程 + 三个可复跑的数字（单跳 R@1 80.0%、拒答 100%/误拒 0%、
    伪造引用 116→0）。
- 怎么验证的
  - 场景 1 实测 `elapsed_ms = 34`，10 条引用（3 手册段 + 3 工单 + 1 传感器 + …）。
  - 场景 3 `insufficient_evidence`，命中词 1/3、信息量 1.4495/2.5。
  - 场景 4 trace 只有一行「安全规则 E-SAFE-01 命中，短路」——证明确实没查库。
- 数字变化
  - 无（这一阶段只加文档，没动代码）。
- 遗留
  - 文档里留了"截图位置"，没有真截图（本机无浏览器录制）；截图由演示者按标注的位置自己截。

---

## P1 mfg-agent 推到 L3 · 2026-10-28

八条验收逐条对照。**顺序按任务书建议**：5 指标 → 4 配额 → 3 审计 → 2 鉴权 → 1 容器 → 7 初始化 → 8 运维。

| # | 要求 | 状态 | 证据 |
|---|---|---|---|
| 5 | `/metrics` | ✅ | `mfg_qps_60s`、`mfg_ask_latency_ms{quantile}`、`mfg_error_rate`、`mfg_refusal_rate`；`tests/test_metrics.py` 3 条 |
| 4 | 限流/配额 | ✅ | 按调用方分钟+天双窗口，429 + `Retry-After`；`tests/test_limits.py` 5 条（含"被拦的请求没进检索"） |
| 3 | 审计留痕 | ✅ | `audit` 表 + `GET /api/audit`；fail closed（写不进 → 503）；`tests/test_audit.py` 3 条 |
| 2 | 账号体系 ≥2 角色 | ✅ | `admin`/`user`，key 只存哈希，`Depends(require_admin)` 管写操作；`tests/test_auth.py` 10 条 |
| 1 | Dockerfile + compose | ⚠ **写了，未实跑** | `tests/test_deploy.py` 只做静态校验；本机没有 docker |
| 7 | 初始化脚本 | ✅ | `scripts/bootstrap.py`，空库跑过：建 2 把 key、预热 105 ms、退出码 0 |
| 6 | 数据可替换 | ✅（原本只有口头承诺） | `tests/test_data_replace.py` 3 条，现生成一本 `TEST900_manual.pdf` 验证 |
| 8 | 运维文档 | ✅ | `docs/ops.md`：起服务 / 排障表 / 升级 / 备份 / 已知边界 |

真 LLM 通道：`provider_status()` 把"配了什么、实际用什么、为什么"暴露在 `/healthz` 和启动日志里，
避免"以为在用大模型、其实还是 stub"。6 条测试全部打桩 httpx，pytest 不依赖网络。

**过程中修掉的真 bug**
- `X-Actor` 响应头塞中文（actor 叫"班组A"）会触发 latin-1 编码错误，整个响应 500。改百分号编码。
  这是测试抓到的，不是想出来的。
- `sqlite3.Row` 迭代出的是值不是列名，我按 ruff 的 SIM118 建议改成 `for k in row` 后审计接口直接 500。
  已改回 `.keys()` 并写清原因——**linter 的建议也要看语义**。

**测试**：64 → 99 条，全绿。`ruff check .` 干净。评测数字无变化（`evals/reports/20261028_2038_b7a2df9.json`：
单跳 R@1 80.0%、引用精确 79.3%）。

**遗留**
- `docker compose up` 必须在有 docker 的机器上验一次，把结果补进本节。
- 审计表无归档策略（100 万行以内不用管，ops.md 已写）。
- 配额计数在进程内存，多副本要换 Redis（ops.md 已写）。

---

## P2 OmniAgent 去仿真 · 2026-10-28

仓库：`D:/Codex/Projects/OmniAgent-Platform`（commit `7adee46`）。两个项目仍然完全独立，没有合并。

读 `services.yaml` 与 `routers/gateway.py` 后发现，真实情况比任务书里写的更微妙：

| 项 | 任务书假设 | 实际情况 |
|---|---|---|
| 鉴权 | 「已仿真」 | 有 HMAC-SHA256 JWT + RBAC，**但** `get_tenant_context()` 在 Bearer 解析失败时会继续向下落到默认开发租户（`role=admin`）——换个坏 Token 反而拿到管理员 |
| 配额 | 「已仿真」 | 完全没有。`FAILOVER_SCENARIOS` 里的 429 只是一段演示文本，服务端从未拒绝过请求 |
| 转发 | 「主备热切是仿真」 | 属实，仍是 `sleep(0.038)` + 模板回复 |

所以做了三件事：

1. **真配额**（`core/quota.py`）：按租户分钟/天双窗口，超阈值 429，带
   `X-Quota-Remaining` / `X-Quota-Limit` / `X-Quota-Window` / `Retry-After`。
   新增 `GET /api/v1/gateway/quota` 只读查询。计数在进程内存，多副本要换 Redis（已写进 README）。
2. **真鉴权**：修掉上面的降级洞；`/v1/chat/completions` 改为只认 JWT
   （`X-Tenant-ID` 标头谁都能编，不能当身份凭证）。
3. **前端配套**：`openaiChat` 无 JWT 时先取 token 再请求，避免演示面板因为 401 掉到本地降级。

**怎么验证的**（不只是 TestClient，还起了真进程 `OMNI_PORT=8911 OMNI_QUOTA_PER_MINUTE=2`）：

```
无 token                → 401
只带 X-Tenant-ID        → 401
有效 JWT（第 1 次）      → 200，响应头 x-quota-remaining: 1
第 2 次                 → 200
第 3 次                 → 429，retry-after: 58，x-quota-remaining: 0
另一个租户              → 200（额度按租户隔离）
/api/v1/gateway/quota   → {"used_last_minute":1,"remaining":1,...}
```

测试：**70 → 78 passed**（新增 8 条），`ruff check .` 干净。

**README 的改法**（这条最关键）：原文「它不是什么」里写着「没有配额账本」——现在有了，
所以改成"这一轮加了，但只管网关代理这一个入口，不是全平台计费账本"。
「主备热切是仿真」那句**一个字没动**，因为它仍然是真的。

**遗留**
- 配额是进程内存，横向扩容要换 Redis
- 上游转发仍是仿真：本机没有可用模型线路，不做假的透传
- `/api/v1/auth/token` 是无认证的签发端点（谁都能要一个 admin token）。这是演示级设计，
  要上生产必须换成公司 SSO/IdP。**这一条没有改**，如实记在这里
