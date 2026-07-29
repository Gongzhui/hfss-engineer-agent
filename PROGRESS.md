# PROGRESS — hfss-mcp benchmark 设施（任务书 2026-07-29）

> 本文件为「benchmark 设施」目标新建。上一目标（真实 AEDT V0 演示）的 PROGRESS 全文
> 已随其交付提交进 git 历史（末次 8369a2a），此处不重复保留。

分支：`feat/real-aedt-v0`。每完成一个任务 commit 一次（不 push），提交信息带任务号。

## 任务 0 · 基线核对（2026-07-29 本机实测，与任务书一致）

- `pytest -p no:cacheprovider`（TMP 重定向 .tmp_pytest）→ **61 passed, 0 skipped**（63.02s）✓
- `ruff check .` → **0**（先删可再生 pywin32 缓存 `.tmp_pytest/gen_py`，见 BLOCKED A 类）✓
- `mypy` → **0 errors**（30 source files）✓
- 结论：基线与任务书吻合，全量开工。

## 理解的目标 / 顺序 / 最大风险（≤10 行）

- 目标：在 hfss-mcp 建可扩展 benchmark 设施——拿故意调错的真实 SIW 天线工程，
  验证这套工具经 MCP 闭环能否把天线调回来；新增 case 零改代码（只加 case 目录 + case.json）。
- 顺序：骨架/case 格式（任务1）→ 答案册真实求解（2）→ 沙箱剥离+泄露审计（3）→
  MCP 探针冒烟 ≤6 trial（4）；每任务一 commit。
- 最大风险：① 沙箱剥不干净（Soln/报告/兄弟 design 藏标称值）——所以 verify 要反向验证红→绿；
  ② 单次求解 ~4 分钟，任务 2 需 2 次、任务 4 需 ≤6+ 次，总耗时 ~40 分钟级，脚本必须
  无人值守且自清理 ansysedt；③ 求解优先走仓库自有 manifest/trial 机制，走不通才
  PyAEDT 直连并记原因（这本身是第一条 FINDING）。

## 任务 1 · 完成（2026-07-29）

- 新增 `benchmark/`：`case_io.py`（case.json schema + 确定性扰动 + .aedt 文本变量解析）、
  `aedt_text.py`（剥离/审计文本工具）、`procs.py`（ansysedt 快照/清理）、
  `build_case.py`（probe/answer/sandbox 三阶段 CLI）、`README.md`（加 case 指南）、
  `cases/siw_feed_l1/case.json`（白名单 fl fw fx fy t1，区间=标称×[0.65,1.45]）、
  `.gitattributes`（`*.aedt/*.sNp -text` 防 CRLF）、`.gitignore`（build/ 等中间产物）。
- 验收：`build_case.py --case siw_feed_l1 --help` EXIT=0 ✓；README 存在 ✓；
  `--stage probe` 正确列出 3 design、主 design 恰 19 个字面值变量（与任务书一致）✓；
  `ruff check benchmark/` 0 ✓。
- 修掉一个解析 bug：.aedt 含同行 `$begin_cdata$ $end_cdata$`，深度计数需按出现次数算，
  否则变量表串到下一个 HFSSModel 块（实测串出 30 变量的假表）。
- 扰动（seed=42 实算）：fl -22.8%、fw -24.8%、fx -14.5%、fy -23.5%、t1 -21.8%，全部在区间内。
