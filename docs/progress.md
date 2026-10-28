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
    （报告 `evals/reports/20261028_2151_<hash>.json`）。
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
