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

## 任务 2 · 完成（2026-07-29）

- `examples/build_golden.py`（可重跑，固定产物路径）→ `golden_patch.aedt` + `golden_manifest.json`。
- 白名单变量：`gap`（mm，0.5–3.0）；metrics：S11_min_dB / S11_min_freq_GHz / S11_at_target_dB（目标 2.4 GHz）。
- 实测：`uv run python examples/build_golden.py` 退出码 0，产物存在；manifest 通过 `validate_manifest_dict`；构建后 ansysedt 残留 0。

## 任务 3 · 完成（2026-07-29）

- `examples/run_demo.py`：stdio 起 `hfss_mcp.server` 子进程 + `mcp.client.stdio` 调工具
  （manifest_validate → trial_start/status/result ×6）→ Touchstone 重解析出表 → results.json →
  自清理 spawn 的 ansysedt。未走降级（协议层全程走通）。
- **排障记录（stdio 专有死锁）**：server 子进程里首个 `health` 调用挂死。faulthandler
  注入定位：FastMCP 工具线程内首次惰性 import `numpy._core.multiarray`（经
  pyaedt/win32com 链），与主线程持有的 import 锁成环——CPython import-lock 死锁经典款。
  同进程/内存传输不复现，只有 stdio 子进程命中。
  修法：`server.main()` 在 `mcp.run()` 前 `_prewarm_imports()`（numpy、win32com.client、
  pythoncom、ansys.aedt.core），主线程完成全部重 import，工具线程只命中 sys.modules。
  修复后 stdio 探针 health 0.87s 返回。ruff/mypy/60 非 real 测试回归全绿。
- `examples/.gitattributes`：`*.aedt -text`，防 git CRLF 改写黄金工程字节。
- 反向验证：manifest 指向不存在工程 → `DEMO FAILED: ... "code": "original_missing"`，
  退出码 1，NO_AEDT_RESIDUE: True；还原 manifest 后全绿。
- 正式跑（绿）：EXIT=0；6 trial，S11@2.4GHz 从 -0.1166（gap=1.0 基线）单调改善到
  -0.2351（gap=2.5），IMPROVEMENT 0.1185 dB；GOLDEN_SHA256 前后一致
  （89379846…48c2cc）；NO_AEDT_RESIDUE: True；results.json 含每个 trial 的
  Touchstone 文件名+mtime（非手写）。
- 另一个小修：anyio ExceptionGroup 会把 DemoFailure 包装逃逸——main() 现在解包取
  叶子错误，保证失败时打印一行清晰错误并以 1 退出。

## 任务 4 · 完成（2026-07-29）

- README：工具表补全为 25 行（每工具一行）；新增「Demo: one-command real closed loop」
  一节（环境前提 + 两条命令）；health 的 connection_mode 描述更正为 auto 语义；
  Safety model 增加 attach_live opt-in 说明。
- docs/STATUS.md：更正 2026-07-21「PASSED」结论（当时实为 session_mode=new 路径；
  默认 auto 路径有两个失败模式，已修）；写入 2026-07-29 实测（61 passed / ruff 0 /
  mypy 0 / 演示 6 trial 改善 0.1185 dB / 哈希不变 / 零残留）；Known limits 增加
  6–9（attach_live、COM attach 限制、prewarm、TMP 重定向）。

## 最终验收（2026-07-29，四次提交之后重跑）

- 全量 pytest：**61 passed in 58.86s**（EXIT=0）；ruff **All checks passed**；mypy **0 errors**。
- 演示正式跑：EXIT=0，6 trial 单调改善（-0.1166 → -0.2351 dB @2.4GHz），
  GOLDEN_SHA256 前后一致（89379846…48c2cc），NO_AEDT_RESIDUE: True。
- 反向验证：manifest 指向缺失工程 → DEMO FAILED（original_missing），退出码 1；还原后全绿。
- `git diff --stat 414fd68..HEAD -- tests/`：仅 test_setup_ops.py 一行特许 `# noqa: B017`。
- 提交：846fe41（任务1）bdbbc6d（任务2）ba1ce07（任务3）8369a2a（任务4）。
- 未提交的运行产物（可再生）：`.tmp_pytest/`、`examples/demo_output/`、
  `examples/golden_patch.aedtresults/`。
