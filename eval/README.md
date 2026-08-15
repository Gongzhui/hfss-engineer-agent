# Eval：测 MCP + Skill，不测模型

这套夹具检验的是 **hfss-mcp 工具面** 和 **tune-hfss-antenna Skill** 会不会把 Host Agent 带成工程师。不换模型、不发榜。

协议：

1. 人在 AEDT 里打开该题的 **sandbox**（不要打开 `nominal/`）。
2. Cursor **只打开** `eval/exams/<id>/`，不要打开仓库根（否则 `cases/*/answer` 和源码会泄题）。
3. 新聊天说「执行测试」。Agent 读考场内说明，用 Optimetrics **联合矩阵**调参（不是单点改值），把日志写进 `runs/`。分组和点数由本结构决定。有墙钟时限的题以 GOAL/AGENTS 里的时刻为准，到点停，不靠轮数卡预算。
4. 人回到仓库根跑 `eval/score_run.py`。判卷脚本和 `eval/keys/` **不在考场工作区里**。

| 考题 | 测什么 |
|---|---|
| `uwb_circular_notch` | 阻抗带宽 + 通带中间有清晰阻带（不指定频点） |
| `uwb_circular_notch_wlan58` | 阻带钉在中国 5.8 GHz WLAN，带宽度、相对带宽、墙钟时限 |

| 路径 | 谁看得见 | 放什么 |
|---|---|---|
| `eval/exams/<id>/` | 应试 Agent | 目标、白名单、日志模板、`runs/` |
| `eval/keys/<id>.json` | 事后判卷 | 标称曲线、起始曲线、答案册指针；有 `spec` 的题会给出 pass |
| `cases/<id>/answer/` | 答案册 | 标称尺寸；应试会话禁止读 |
| `cases/<id>/nominal/` | 答案工程 | 应试会话禁止打开 |

用户级 MCP（`hfss-mcp`）和 `~/.agents/skills/tune-hfss-antenna` 在新窗口里仍然可用，不必把源码放进考场。
