# 运维手册

> 这份文件写给"接手这台机器的人"。假设他没读过 README，也不知道我为什么这么设计。
> 所有命令都在本机跑过；**唯一没跑过的是 `docker compose up`（本机没装 docker）**，那一节标了。

---

## 1. 这台机器上有什么

| 东西 | 位置 | 说明 |
|---|---|---|
| 语料 | `data/equipment/manuals/*.pdf`、`data/compliance/**/*.md` | 合成数据，脚本可重生成 |
| 真实手册 | `data/equipment/manuals/real/` | 厂商 PDF，**不进仓库**，挂载/手动放入 |
| 运行期状态 | `data/state.sqlite3` | 工单草稿、差距清单、API key、**审计记录**。删了等于清空历史 |
| 评测报告 | `evals/reports/*.json` | 页面底部指标条读这里的最新一份 |
| 日志 | 标准输出 | 容器/服务管理器负责收集；本服务不写日志文件 |

一句话：**语料可再生，`state.sqlite3` 不可再生。** 备份只盯它。

---

## 2. 起服务

### 2.1 本机（最快）

```bash
cd /d/wb_job/mfg-agent
VP=~/.workbuddy/binaries/python/envs/default/Scripts/python.exe

$VP scripts/bootstrap.py                  # 自检 + 建 key，退出码 0 才能起
$VP -m uvicorn app.main:app --host 127.0.0.1 --port 8321
```

打开 <http://127.0.0.1:8321>，页面会要求填 API key（首次见 §3）。

> 用 curl 在本机测时加 `--noproxy '*'`：这台机器的系统代理会把 127.0.0.1 也代理掉，
> 不加会得到 `upstream connect failed` 或 HTTP 502。

### 2.2 容器

```bash
cp .env.example .env        # 改掉两个 key
docker compose up -d --build
docker compose ps           # 应该 healthy
curl -s localhost:8080/healthz
```

**状态：本机没有 docker，这一节没有实际执行过。** 已验证的部分是：Dockerfile 里 COPY 的路径都存在、
compose 的 YAML 结构合法、启动命令引用的 `scripts/bootstrap.py` 存在（`tests/test_deploy.py`）。
上目标机器后请先跑一次 `docker compose up`，把结果补记到 `docs/progress.md`。

容器里的路径约定：
- 语料在镜像内 `/app/data`
- 状态在卷 `/state/state.sqlite3`（`STATE_DB` 指定），重建镜像不会丢审计
- 真手册从宿主机只读挂到 `/app/data/equipment/manuals/real`

---

## 3. Key 与角色

首次启动会建两把：`admin`、`user`。**默认值 `dev-admin-key` / `dev-user-key` 只为本机能打开页面**，
试点前必须：

```bash
# 换 key 的正确做法：删掉旧库里的 key 表再重启，或者用管理员接口发新 key
curl -s -X POST localhost:8321/api/admin/keys \
  -H "X-API-Key: $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"维修一班","role":"user"}'
# 返回里的 key 只出现这一次，库里只有 sha256
```

权限边界：

| 角色 | 能做 | 不能做 |
|---|---|---|
| `user` | 提问、看自己的审计 | 写工单/差距、确认记录、重载语料、发 key |
| `admin` | 以上全部 + 写 + 重载 + 发 key + 看所有人审计 | — |

> 取舍：真实部署里"维修工能不能开工单草稿"应该是第三个角色（technician）。
> 试点阶段按任务书要求只做两角色，这一条写在结论里，不含糊过去。

关掉鉴权（只用于本地调试）：`AUTH_ENABLED=0`。

---

## 4. 配额

环境变量：

| 变量 | 默认 | 作用 |
|---|---|---|
| `RATE_LIMIT_ENABLED` | 1 | 关掉就完全不限 |
| `RATE_LIMIT_PER_MINUTE` | 60 | 单调用方每分钟 |
| `RATE_LIMIT_PER_DAY` | 2000 | 单调用方每天 |

超限返回 **429**，带 `Retry-After` / `X-RateLimit-Remaining` / `X-RateLimit-Window`。

**已知局限（很重要）**：计数器在进程内存里。多副本部署时每个副本各算各的，
实际额度 = 副本数 × 配置值。真要卡死配额，把 `core/auth/limits.py` 的存储换成 Redis，
接口（`check(identity) -> Decision`）不用变。

`/healthz`、`/metrics`、`/api/metrics` 不限额也不鉴权（Prometheus 和探针要用）。
如果这台机器暴露在不可信网络里，在反向代理层把 `/metrics` 关掉。

---

## 5. 排障

按"最可能先遇到"排序。

| 现象 | 先看哪 | 常见原因 / 处理 |
|---|---|---|
| 页面打开是空的，控制台 401 | `/api/auth/whoami` | 没填 key 或 key 被停用；页面会弹密钥条，粘贴管理员给的 key |
| 所有回答都是"证据不足" | `python scripts/bootstrap.py` | 语料缺失。它会直接说缺哪个文件；`/healthz` 的 `issues` 也有 |
| `[boot]` 那行段数比预期少 | `/healthz` 的 `corpus` | 手册没被识别：`manuals/real/` 里放了 PDF 但没写 `_meta.json` |
| 换了手册但答案还是旧的 | — | 索引是缓存的，调 `POST /api/admin/reload`（要 admin key） |
| 429 | 响应头 `Retry-After` | 配额上限，调 `RATE_LIMIT_PER_MINUTE`，或给调用方单独发 key |
| 503 且 detail 含"审计" | 磁盘 / `STATE_DB` 路径权限 | 审计写不进去时服务**故意拒绝应答**：宁可报错也不留"答了但查无此事" |
| 启动报 `database is locked` | 是否跑了两份服务指向同一个 `STATE_DB` | 一个库只能一个进程写；要并行就各给一个库 |
| `curl` 报 502 / upstream connect failed | 是否漏了 `--noproxy '*'` | 系统代理拦截了 127.0.0.1 |

指标在哪看：

```bash
curl -s --noproxy '*' localhost:8321/api/metrics | python -m json.tool
curl -s --noproxy '*' localhost:8321/metrics | grep -E "qps|latency|error_rate|refusal"
```

`/metrics` 里有 `mfg_qps_60s`、`mfg_ask_latency_ms{quantile}`、`mfg_error_rate`、`mfg_refusal_rate`，
以及按域拆的 `mfg_ask_total{domain,outcome}`。

---

## 6. 升级

1. `git pull`（或换镜像 tag）
2. `python scripts/bootstrap.py` —— 幂等，会自检语料并在缺时生成
3. 重启进程/容器
4. 冒烟三条：
   ```bash
   curl -s --noproxy '*' localhost:8321/healthz | grep -o '"index_ready":[a-z]*'
   curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' localhost:8321/api/ask \
     -H "X-API-Key: $USER_KEY" -H 'Content-Type: application/json' \
     -d '{"domain":"equipment","query":"AX300 报 E05 怎么处理"}'
   curl -s --noproxy '*' localhost:8321/metrics | head -3
   ```
5. 要看质量有没有退：`python -m evals.run`，和 `evals/reports/` 里上一份对比。
   **数字变差要先说清楚是数据变了还是代码变了**，别直接调阈值把它压回去。

数据库没有迁移框架。加字段用 `ALTER TABLE`，加表在 `init()` 里 `CREATE TABLE IF NOT EXISTS`，
都写在对应模块里，重启即生效（`core/store/records.py`、`core/store/audit.py`、`core/auth/keys.py`）。

---

## 7. 备份与恢复

```bash
# 备份：只备份状态库就够（语料能重生成）
cp data/state.sqlite3 backup/state-$(date +%F).sqlite3

# 恢复：停服务 → 覆盖 → 启动（keys 也在里面，恢复后原 key 继续可用）
```

热备份请用 `sqlite3 data/state.sqlite3 ".backup backup/state.sqlite3"`，
直接 `cp` 在写入瞬间可能拿到半个事务。

---

## 8. 已知边界（别在试点时被问倒）

- 单进程：限流、指标都在内存里，横向扩容要改这两处
- 无数据库迁移工具，字段演进靠 `ALTER TABLE`
- 失败降级策略是 **fail closed**：审计写不进去 → 503；引用全校验不过 → 拒答
- 真 LLM 是开关式的（`PROVIDER=openai`），默认 `stub`；评测数字全部来自 `stub`，不代表模型能力
- 审计表会一直长，没有归档任务；超过 ~100 万行再加清理策略
