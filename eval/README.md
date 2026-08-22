# Eval：测 MCP + Skill，不测模型

这套夹具检验的是 **hfss-mcp 工具面** 和 **tune-hfss-antenna Skill** 会不会把 Host Agent 带成工程师。不换模型、不发榜。

协议：

1. **先清 `runs/`。** 上一场的 `eval/exams/<id>/runs/<时间戳>/` 必须先挪到 `eval/archive/exams/<id>/runs/`（考场工作区外）。应试 Agent 只打开考场文件夹，留在 `runs/` 里等于开卷。只留 `.gitkeep`。
2. 人在 AEDT 里打开该题的 **sandbox**（不要打开 `nominal/`）。
3. Cursor **只打开** `eval/exams/<id>/`，不要打开仓库根（否则 `cases/*/answer`、`eval/archive/` 和源码会泄题）。新开对话，不要在应试窗口里搜旧聊天。
4. 新聊天说「执行测试」。Agent 读考场内说明，用 Optimetrics **联合矩阵**调参（不是单点改值），把日志写进本场新建的 `runs/<时间戳>/`。分组和点数由本结构决定。
5. 人回到仓库根跑 `eval/score_run.py`。判卷脚本和 `eval/keys/` **不在考场工作区里**。判完再把该场挪进 `eval/archive/`，下一场才能开。已归档的场次用 `--run eval/archive/exams/<id>/runs/<run-id>`。

| 考题 | 测什么 |
|---|---|
| `uwb_circular_notch` | 6.6 GHz 阻带（频率不放宽，峰与 6.6 GHz 点须 > −7 dB）+ 宽度 ≤ 0.5 GHz + 包络相对带宽 ≥ 130%；求解时间合计 ≤ 3 小时（只计求解，自己加总） |
| `me_dipole_77` | 77 GHz 落入 −10 dB 通带 + 该段相对阻抗带宽 ≥ 30%；求解时间合计 ≤ 8 小时（只计求解，自己加总） |

| 路径 | 谁看得见 | 放什么 |
|---|---|---|
| `eval/exams/<id>/` | 应试 Agent | 目标、白名单、日志模板；`runs/` 开考时必须空 |
| `eval/archive/exams/<id>/runs/` | 事后、人 | 已结束场次；不在考场工作区里 |
| `eval/keys/<id>.json` | 事后判卷 | 卷面阈值、标称/起始曲线、答案册指针 |
| `cases/<id>/answer/` | 答案册 | 标称尺寸；应试会话禁止读 |
| `cases/<id>/nominal/` | 答案工程 | 应试会话禁止打开 |

用户级 MCP（`hfss-mcp`）和 `~/.agents/skills/tune-hfss-antenna` 在新窗口里仍然可用，不必把源码放进考场。

无人值守连考 N 场（监考脚本、卡住后续考）是以后要做的事，规格见仓库 `docs/FUTURE-UNATTENDED-EXAM.md`。现在仍按上面人工五步。
