# PROGRESS — hfss-mcp 真实 AEDT V0 演示

分支：`feat/real-aedt-v0`（不合并、不 push）。每完成一个任务 commit 一次，信息带任务号。

## 任务 0 · 基线核对（2026-07-29，本机）

- 理解的目标：一条命令驱动真实 HFSS 走完「白名单调参→求解→S11 改善」闭环，原始 .aedt 字节不变；
  顺序：先全绿基线（任务1）→ 黄金工程（2）→ 演示脚本（3）→ 文档（4）；
  最大风险：GUI attach/save 路径会改写原始工程 + 干净环境下 PyAEDT attach 不稳定。
- 实测（与任务书一致）：
  - `pytest -m "not real_aedt"` → **60 passed, 1 deselected** ✓
  - 全量 pytest → **1 failed, 60 passed**（test_real_aedt_full_loop）✓
  - `ruff check .` → **9 errors**（含 tests/test_setup_ops.py:31 B017）✓
    - 注意：若先跑过 pytest，`.tmp_pytest/gen_py/` 会多出 2 条（I001/E701，pywin32 缓存），删掉该目录即回到 9。
  - `mypy` → **5 errors**（均在 src）✓
- 已清理任务残留 ansysedt.exe（PID 28936、23648，均为本任务历史测试spawn）。
- 干净状态下 real AEDT 测试的实际失败点（比任务书更靠前，需一并修）：
  1. `design_snapshot` → COM ensure 起 GUI 会话后，PyAEDT 按 PID attach 命中
     pyaedt 1.3 坑 `'Desktop' object has no attribute 'grpc_plugin'`（该会话是 COM 模式）；
  2. 兜底 `new_desktop=True` 再开同一文件 → `Project is locked`（COM 会话持有锁）。
  3. 任务书描述的末尾哈希断言失败 = trial 在 `use_gui` 分支把 `working_path` 指向原始工程
     （`app.py` trial_start：`working_path = live_path = manifest.project_path`），
     mutate+solve+save 全落在原件上。

## 任务 1 · 修复方案（动手前记录）

- A. `config.py`：`attach_live_project` 默认改为 False（`HFSS_MCP_ATTACH_LIVE=1` 仍可显式开启）。
  理由：默认路径必须满足安全不变量（原始工程字节不变）；live-mutate 本质上是危险操作，应显式 opt-in。
  效果：`trial_start` 默认走 workspace 副本 + supervisor worker（独占 desktop、close_on_exit、杀自有 PID）。
- B. `app.py::_get_or_attach_gui`：无现存会话可 attach 时跳过 COM ensure，
  直接建 PyAEDT 自有图形 desktop（new_desktop=True, close_on_exit=False），
  避开 grpc_plugin 坑与锁冲突；有现存会话时维持原 COM 优先路径。
- C. ruff 9 条全修（tests 的 B017 按特许加 `# noqa`）；mypy 5 条全修。
- 验证：任务 0 四条命令全绿后 commit「任务1」。

## 任务 1 · 完成（2026-07-29）

改动（全部在 src/ 与特许的 tests noqa）：
- `config.py`：`attach_live_project` 默认 False（`HFSS_MCP_ATTACH_LIVE=1` 可显式开启 live 模式）；
  `non_graphical` 默认 True（trial worker 一律 headless；GUI attach 路径自行显式 graphical）。
- `app.py::_get_or_attach_gui`：无存活 AEDT 会话时跳过 COM ensure，直接建 PyAEDT-owned
  图形 desktop——避开 pyaedt 1.3 grpc_plugin 坑与 COM 持锁冲突。
- `metrics.py`：新增 `HFSS_MCP_TOUCHSTONE_KEEP_DIR` 钩子，导出 Touchstone 时保留带时间戳副本
  （任务 3 演示取证用）。
- ruff 9→0（含 tests/test_setup_ops.py:31 特许 `# noqa: B017`）；mypy 5→0。

验收实测：
- 单跑 `tests/test_real_aedt.py`（干净环境，先杀光 ansysedt）：**1 passed in 51.45s**，
  evidence 10 步全过含 `original_hash: True`，trial 走 worker 独占 desktop 打副本。
- 全量：**61 passed in 62.17s**；ruff **All checks passed**；mypy **0 errors**。
- 测试后 ansysedt.exe 残留：**0**（自有 desktop 均正确释放）。

## 任务 2/3/4 · 待办

- examples/build_golden.py + golden_patch.aedt + manifest json（复用 real_project.create_minimal_patch_project）。
- examples/run_demo.py：stdio MCP client → server 子进程，≥6 trial，S11 表，results.json，自清理 ansysedt。
- README 25 工具表 + 演示节；STATUS.md 更正过时结论。
