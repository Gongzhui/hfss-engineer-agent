# Unattended exam harness（以后要做，现在不做）

Status: **deferred**. 2026-08-19 记下规格，未写代码、未接 SDK、未改考场 AGENTS。

人工考场协议仍以 `eval/README.md` 为准。本文只描述「我说考 N 次、人不用盯着」时监考层该怎么做。

## 目标

对某一题（当前即 `uwb_circular_notch`）连续跑 N 场独立应试：每场冷启动、交卷、判卷、归档，再复位沙箱开下一场。过程（日志、各轮 CSV、交卷 S11、对话/run id）和判卷结果都进 `eval/archive/`。

人只负责：AEDT 开着该题 sandbox、机器不休眠、监考进程不被杀掉。不关用户的 Desktop，不 `project_save`。

## 两层

| 层 | 看得见什么 | 干什么 |
|---|---|---|
| **监考**（仓库根） | `eval/keys/`、`score_run.py`、archive、MCP | 复位沙箱、确认 `runs/` 只有 `.gitkeep`、拉起一场考生、等结束或超时、判卷、归档、再复位 |
| **考生** | 只有 `eval/exams/<id>/` | 收到开考指令后按该目录 `AGENTS.md` 调参。不读 keys/answer/archive |

一场一个考生会话，考完就扔。不要让同一个会话连考五场（会看见自己的 `runs/`，沙箱也会被自己钉脏）。

一台 AEDT、一条 COM：**N 场串行**。求解上限仍是每场 3 小时（只计 HFSS）；墙钟另设一档超时（建议 5 小时），到点停这一场、有什么交什么、归档、复位、下一场。

## 可移植规则 vs 宿主适配器

规则写在监考层，不写死 Cursor。以后换 Claude Code / Codex 等，只换「怎么把一句话送进考生会话」。目前只做 Cursor 适配器。

### 开考 / 续考（宿主无关）

- 开考：考生只收到该题规定的那一句（现在是「执行测试」）。
- 续考：指向**磁盘上的本场日志**，例如读 `runs/<本场>/hfss-tuning-log.md` 和已有 CSV，从下一轮矩阵接着干；不要重新 `snapshot`、不要另开 `runs/`。不要只发「继续」两个字当唯一记忆。

### 卡住才催（宿主无关）

```
若 HFSS 当前没有在求解
且 超过 20 分钟没有任何助手消息或工具调用
→ 发一条续考引导
```

「有没有在求解」由监考自己问 MCP（`analyze_status` / job），不要问聊天 UI，也不要靠 “Taking longer than expected”。HFSS 在扫 20 分钟是正常的，此时静默也不催。

工具调用必须保持短请求：`parametric_start` 立刻返回 job，再轮询 `analyze_status`。不要把整轮扫参堵在一次 MCP `tools/call` 里（ACP/SDK 路径超时大约 60 秒，IDE 大约 60 分钟）。

### Cursor 适配器（当前唯一）

- 用 **Cursor SDK 本地 Agent**（`cwd` = 考场目录，MCP = 本机 `hfss-mcp`）。不是云端 Agent，也不是往用户正在看的那扇聊天里打字。云虚拟机挂不上这台 AEDT。
- 静默后续考：默认只 `send` 引导，**不要** `local.force=True`。这对应 GUI 里卡住后打字回车，是同一对话里的引导，不是先 Stop 再开一场。
- `force=True` 会先把仍标着 `running` 的那一轮作废再发新消息，相当于 Stop 后再发。只当后备：流已断、status 仍是 running、发引导也没有新事件时，才对**下一条**打开。
- 本地 SDK 的多次 `send()` 不保证带上上一轮对话（已有报告）。续考文案必须写明读本场日志。
- 不要用 Cursor Automations / 向当前 Composer 模拟按键。

## 场与场之间

每场开始前监考必须把 sandbox 拧回开场九点、Optimetrics 清空、多余报告清掉、开场 S11 与 `s11_sandbox.csv` 对上，且 **不保存**。场与场之间若不清掉上一场的 Parametric 和钉点，后面全是脏考。

考生工作区隔离今天仍是约定（`AGENTS.md` 禁止读上级路径），不是 OS 沙箱。硬拦路径是第二期。

HFSS/MCP 挂了：这一场记 `infra_fail`，默认不自动重启 AEDT。射频未过不算基础设施失败，不重考。

归档每场至少：`hfss-tuning-log.md`、各轮 table/s11、交卷 `s11.csv`、`score.json`、宿主 run/会话 id。半截场（催过、超时停过）同样归档，不要当没考过。

## 明确不做（现在）

- 不写监考脚本、不接 SDK、不改考场 AGENTS。
- 不并行五场、不让考生自己循环五次、不把仪表盘当第一期。
- 不把 Cloud Agent 当无人值守主路径。
