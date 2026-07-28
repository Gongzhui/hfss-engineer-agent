# BLOCKED — 待裁决清单

随交付提交。分类：A = 基线核对出入（已自行解决，报备）；B = 顺手活（按任务书不做）；C = 已自行裁决（按任务书意图，备查）。

## A · 基线核对出入（证据，已解决）

- **ruff 基线 9 vs 11**：任务书写 9 errors，首次实跑见 11。多出的 2 条（I001/E701）
  来自 `.tmp_pytest/gen_py/3.12/__init__.py`——pywin32 的 COM 缓存，由任务书自带的
  pytest 命令（TMP 指向 `.tmp_pytest`）运行后生成。`rm -rf .tmp_pytest/gen_py` 后
  回到 9，与任务书一致。建议后续把 `.tmp_pytest/` 加入 `.gitignore` 或 ruff
  extend-exclude——两者均不在本任务可改范围，未动。
- **real AEDT 失败点比任务书描述靠前**：干净环境（无存活 ansysedt）下，
  `test_real_aedt_full_loop` 并非只在末尾哈希断言失败，而是在 `design_snapshot`
  阶段就连败两跳：① COM ensure 起的是 COM 模式会话，PyAEDT 1.3 按 PID attach 命中
  `'Desktop' object has no attribute 'grpc_plugin'`；② 兜底 new_desktop 打开同一文件
  撞 COM 会话持有的锁（`Project is locked`）。任务书描述的哈希失败（trial 把
  `working_path` 指向原始工程）同样存在。两者均已在任务 1 修复，未改动任何测试逻辑。

## B · 顺手活（按任务书一律不做，列此待裁决）

1. `.tmp_e2e_gui/` 清理——任务书点名进 BLOCKED，未动。
2. pyaedt 1.3 COM 会话 attach-by-PID 的 `grpc_plugin` 坑：干净环境已绕过（无存活会话时
   直接建 PyAEDT-owned desktop）。但「用户已有 COM GUI 会话且工程在其中打开」的场景仍是
   best-effort——attach 失败后 new_desktop 会撞该会话持有的文件锁。彻底方案（全程 COM
   RunScript 驱动，或升级 pyaedt）属「修 PyAEDT 已知坑」，未做。
3. `adapter/pyaedt_adapter.py`（约 1400 行）混合 session/attach/setup CRUD/solve/metrics，
   建议后续拆分；重构超出本任务范围，未做。
4. `save_project_copy` 在复制前会先 `save_project()`：worker 流程中作用于 workspace 副本，
   无害；但值得 review 该 save 是否必要。未改。
5. 新依赖：任务书要求一律不加。本实现未需要任何新依赖（demo 用文本表，未画图）。

## C · 已自行裁决（按任务书意图，备查）

- **MCP 协议层走通，无需降级**：`run_demo.py` 以 stdio 起 `hfss_mcp.server` 子进程，
  用 `mcp.client.stdio` 调工具。期间发现并修复一个 stdio 专有死锁：工具线程内首次惰性
  import（`numpy._core.multiarray`）与主线程 import 锁成环——`server.main()` 现在
  先 prewarm 重模块（numpy/win32com/ansys.aedt.core）再 `mcp.run()`。详见 PROGRESS.md。
- **反向验证方式**：采用「manifest `project_path` 指向不存在文件」制造失败（任务书
  建议的「改坏 workspace 副本」的等价物；「目标频点改成无解值」不会失败——
  `s11_at_freq` 取最近点，恒有值）。
- **ansysedt 清理范围**：脚本只杀自己 spawn 的 PID（启动时快照对比）。验收从 0 个
  ansysedt 开始，结束也为 0；若演示前已有别人的 AEDT 会话，不会被误杀。
- **`.gitattributes`**：在 `examples/.gitattributes` 新增 `*.aedt -text`，防止 git
  CRLF 转换改动黄金工程字节（该文件属新建 `examples/` 范围）。
