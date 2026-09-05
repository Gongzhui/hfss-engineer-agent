# 求解期间进度查询阻塞修复

## 原因与改动

`analyze_status → _reconcile_running_job → _ensure_session → GUI 工程枚举` 会等待 `RunScript` 在整轮求解期间持有的 COM 锁。原路径还同步读取 Message Manager，并用 Optimetrics 的 `has_result` 推断完成；部分结果或旧结果可能导致提前判定完成。

- 状态响应只读取内存/持久任务状态，返回独立副本，不同步访问 AEDT。
- Message Manager 由单个后台线程刷新。即使 COM 不返回，后续查询仍返回，且不累积更多 COM 线程。
- `messages_updated_at`、`messages_refresh_pending` 标识消息新鲜程度；消息获取失败保留 `job.messages_error`。
- 完成状态来自求解线程；恢复的 running 状态标记 `state_verified=false`。仍存活的原服务可通过 jobs.json 发布终态；原 worker 已丢失时不凭历史消息或已有结果猜测完成。
- 恢复时的后台消息读取绑定任务自己的工程、设计与已记录 PID，不跟随其他 GUI 活动工程。

## 验证

- 离线测试：90 passed，3 个现有实机测试按 marker 排除；新增用例覆盖 Analyze/Parametric、COM 阻塞时及时返回、单个后台读、终态、部分结果不提前完成、恢复状态与原工程绑定。
- 本轮变更文件 Ruff 检查通过。
- 全仓库 Ruff 尚有 6 个既有问题；mypy 有 8 个既有问题，已在 HEAD 源码副本复核同样的 8 项，本次没有增加。未顺手改其他模块。
- 正在运行的真实 AEDT 扫描 `Exam001_Radiator`：独立新版 STDIO 客户端连续查询 6 次，耗时 6.2–23.6 ms；读取到第三个参数组合的 Message Manager 行与新的刷新时间。证据：`scratch/progress-polling-active-20260905.json`。
- 独立工程从启动到完成的实机回归：未执行；用户于 2026-09-05 明确决定不再等待该项，直接提交修复。保留脚本 `examples/verify_progress_live.py`（从仓库根执行 `python -m examples.verify_progress_live`）；会在 scratch 下复制 golden 工程，通过真实 MCP 跑 Analyze 与两点 Parametric，再导出 family 曲线。以后运行须先确保桌面未在运行其他考试求解。

## 生效边界

运行中的旧 MCP 不会热加载 Python 修改；需要重启对应宿主的 MCP 进程。不要把重启当成停止 HFSS 求解。考试源码冻结已因用户授权修 bug 而改变，旧冻结清单继续作为历史证据，不覆盖它。
