---
name: tune-hfss-antenna
description: Tune allowlisted parameters on an existing HFSS/AEDT antenna via hfss-mcp. Inner loop is a joint Optimetrics Parametric of knobs that are coupled in this structure this round — grouping and sample density are the agent's call, not a fixed recipe. Diagnose from the family of curves, not one-point jumps. Use when recovering matching, tuning S11, tuning reflection-phase states, or running an eval exam. Do not use to build geometry from scratch.
---

# Tune HFSS antenna

Host Agent 当工程师，挂用户**已经打开**的 AEDT。内环是人坐在 HFSS 前会做的事：按**这一副结构、这一轮问题**判断哪些量相互耦合，用自带的 **Optimetrics → Parametric** 做联合矩阵，在 Results 里看**一簇**曲线，冻结不敏感的量，再决定下一组或把范围收窄。不要一次把一个参数改成另一个值再 Analyze。不要遗传/粒子群。手续对匹配天线和相位单元通用，只换观察量。

两种常见题目共用同一套手续，只换观察量：

| 题目 | 看什么 |
|---|---|
| 小型辐射天线的匹配 | Modal S11 的 −10 dB 频段、必要时 Smith / `terminal_z`。某个频点再深没有加分。 |
| 2-bit 等单元的反射相位 | 各状态下相位是否大约隔 90°。 |

## Hard rules

- 只调 allowlist 里的变量；禁改几何、材料、端口、HFSS Setup。
- 扫参必须出现在 Optimetrics 树里。禁止自己循环 `variables_set`+Analyze 冒充矩阵。
- 禁止 Optimetrics Optimization / Sensitivity / Statistical / DOE。
- `variables_set` 只用于矩阵看完之后**钉住一组点**，不要求解、不要保存。钉之前必须对照 GOAL 里**还没完成的每一项**：某一格把一项做到最好、却把另一项还需要的特征填掉了，那一格不能钉。不要把 GOAL 拆成「先做完 A 再加 B」。
- `parametric_start` / `analyze_start` 的 `ok: true` **只表示任务已受理**，不是扫完。看 `done`。未 `done` 就必须 `analyze_status`（里面有 Message Manager 最近几行，这就是进度）。`failed` 时读 `job.error` 和 `messages`，不要空等。
- **禁止** `trial_*` / `run_*`。
- 不自动保存。有明显进展才 `project_save(mode="save_as")`。用户说「直接保存」才 `mode="save"`。
- 推理写在 `hfss-tuning-log.md`。开扫前必须写清：**为什么是这一组、为什么是这些采样点**。写不出结构理由就还没到 `parametric_create`。

## Size the matrix (you decide)

耦合个数、每轴点数都不是本文件里的常数。给建议值 Agent 就会照抄、不再想；所以这里**不设默认 N、不设默认每轴点数**。你必须自己从结构推出来，并写进日志。

每一轮按这个顺序想，再调用工具：

1. **这一轮的问题是什么**（搬低频匹配、辨阻带、收相位差……）。
2. **哪些量现在是耦合的**（几何上是一套、上一簇曲线里一起动的）。耦合可能是 2 个，也可能是 4、5，一直到一张表里十来个。
3. **这一轮扫几组、每组几个**。一组太大就拆成仍有物理意义的几组；一组不大就联合扫，不必拆。不要为了凑个数把不相关的量塞进来，也不要因为怕大而每次只动一个。
4. **每轴取几个点、范围多宽**。够看出这一轮的趋势即可：范围还不清楚时疏一点、宽一点；已经知道敏感区间时再密、再窄。点数是判断，不是配方。
5. **乘积能不能坐在机器前跑完**。`parametric_create` 会返回 `points`。当前 MCP **一轮最多 256 点**——这是防整张白名单阶乘的安全阀，不是推荐网格。四个耦合量的联合扫参应当进得去；十维 2^n 进不去，那就拆组。被上限卡住时写明，不要假装 256 就是好网格。

**这一轮不合格的矩阵：**

- 单点跳变（一个量改成一个新值 + Analyze）。
- 整张白名单一网打尽「图个全面」。
- 分组/点数换到另一副天线也能原样粘贴——说明没针对本结构想。
- 因为本 Skill 或别处出现过某个数字，就采用那个数字。

**对照（不是默认。没有结构理由就抄这些数，等于没判断）：**

- 十来个相互耦合的量：拆成几组分别联合扫（例如按几何分成几簇），而不是十维一张网。
- 四个确实耦合的量：可以咬牙一轮联合扫。
- 两个强耦合的量：两个就够；硬加一个不相干的第三量，一簇曲线会变脏。

## Tools

`health` → `session_list` → `allowlist_load` → `snapshot` → `variable_map` / `view_capture` → `optimetrics_list` → `parametric_create` → `parametric_start`（`analyze_status` 轮询）→ `parametric_export_table` + **新的** Results 报告 `report_create(..., parametric=<该矩阵名>)` → `report_export`。钉点时才 `variables_set`。场/电流用 `report_create(report_type="field_face", quantity="Mag_E"|"Mag_Jsurf")`，见 Diagnose。

白名单：考场用该目录 `allowlist.json`；否则 `cases/uwb_circular_notch/allowlist.json`。

同名 Parametric 再 `parametric_create` 会 **EditSetup**（树上那个节点被改掉，不删除）。粗扫改成精扫可以沿用名字；换一组变量建议换名字，免得和用户原来的扫参混在一起。

开场那张单迹 `S11` **不会**因为后来扫了参就自动变成一簇。矩阵跑完后必须再建一份人看得到的报告（例如 `<Parametric名>_S11`），`families` 或 `parametric=` 把扫过的量设成 All，再 `report_export`。导出的 CSV 是 `freq_ghz,variation,s11_db`。不要把开场那条单迹当成矩阵结果。

## Loop

1. `health` / `session_list`。没有 Desktop 就让用户先打开工程。
2. `allowlist_load`。`snapshot`。不熟则 `variable_map` + `view_capture`。
3. 写清这一轮在调匹配还是相位。按上一节排出分组和采样，写入日志，再 `parametric_create`（须在树上能看见；看返回的 `points`）→ `parametric_start` → **`analyze_status` 直到 `done`**。不要把 start 的 `ok` 当成扫完。
4. `parametric_export_table` 是组合表。再 `report_create` 一份带 family 的 Results 图并 `report_export`。看哪条曲线随哪个量动、哪个量几乎不动。
5. 敏感的留下；对剩余 GOAL 无害的才钉死。某一格让带宽/匹配变好、却删掉 GOAL 仍要的中频特征、阻带、相位差，那一格不是候选。钉点前列出：这一格让哪一项变好、哪一项变差。不要为了「和 Round 000 可比」把已经在搬 GOAL 特征的量退回开场值。下一轮可以换一组、或同一组收窄加密。钉点时才 `variables_set`。钉住之后如需单条曲线，再导出不含 family 的报告（或 `families=[]`）。
6. 重复。达标、连续两轮看不出新的影响、或该分组的问题已经问完再停。不要用「跑满某几轮」当停手理由，也不要只扫一次就交差。

## Diagnose

先标观察量上的**特征**（鼓包、凹坑、Smith 小环、相位跳变），再问「这一组里谁在搬它」。不要只问某条水平线穿没穿过。

**特征记账（每一轮写进日志）：** 假设是什么机理、该被哪些量搬、这一簇是搬了、变深了、还是死了。某组量在**当前几何**下证伪，只能写「这一副尺寸上不是它」；贴片、地板或馈电尺寸变了，要再问一次。

**阈值不是存在性。** \(S_{11}=-10\,\mathrm{dB}\)、90°、某个 dBi 用来验收深度或间隔。一簇曲线上极值在搬频或变深，机理就还在——下一步问耦合和位置，不要换机理、不要退回开场。

**钉点看全部剩余 GOAL。** 这一轮可以只问一个问题，但 `variables_set` 必须对 GOAL 里还没完成的每一项过一遍。不要「先做最干净通带 / 最深匹配，再把别的加回来」。

**频率在走、深度不走：** 谐振尺寸问完了，电流怎么经过这个局部还没问。把馈电、偏置、缝到电流的距离、地放回同一组，不要把它们钉死之后只扫谐振尺寸。

形状分类仍有用，但不是工序：

- 匹配：\(S_{11}\le -10\,\mathrm{dB}\) 的穿越点。低频**整段**抬起，馈电/地板往往要进**同一组**矩阵，不要先整体缩放贴片。
- 通带中间的抬起才像阻带；GOAL 还要这段特征时，填掉它算退步，即使带宽数字变好。
- 身份不清时看 Smith / `terminal_z`：宽频游走像匹配空洞，小环或急转像谐振器。
- 相位：四个态是否大约隔 90°，谁在转相位、谁在毁匹配。
- 不要用单点跳跃代替矩阵。单点证伪（「改了某个量一次没动」）证据不足。

**场 / 电流。** 结构里凡是靠截断或绕路电流工作的局部（槽、枝节、缝、过孔、寄生、缺口），在认定某个鼓包是它之前、以及钉点之前，看指定面、指定频点的图。`report_create(report_type="field_face", face=<物体或 FaceID>, frequency=<鼓包中心>, quantity="Mag_Jsurf")`；缝里的场用 `quantity="Mag_E"`（默认）。只允许这两个量。同名 overlay 会复用，换量或换频点要换名字（默认名已带上 quantity）。

问三句：

1. 鼓包中心：电流是否绕过或集中在这个局部？没有 → 鼓包不是它，是匹配。
2. 旁边已匹配的通带频点、同一面同一量：通带里它是否相对安静？只看一个频点不够。
3. 准备钉的那一格 vs 鼓包最深的那一格，同一频点：钉死会不会让电流躲开这个局部？躲开的不能钉。

插值扫频常常没存场，指定频点会失败。失败就退回看簇曲线上极值在不在搬，写进日志，不要卡住。不要改 HFSS Setup 去强行存场。

```bash
uv run python skills/tune-hfss-antenna/scripts/plot_s11.py path/to/s11.csv --mark-ghz 60 --mark-peaks --out hfss-tuning-artifacts/round-00N/s11.svg
```

`plot_s11.py` 画 `freq_ghz,variation,s11_db` 的一簇曲线。`--mark-peaks` 标出每条曲线最接近 0 dB 的局部最高点（鼓包），并打印频率；横虚线是 −10 dB。盯峰值怎么搬，不要只盯穿不穿过 −10。

## Demo case

考场：Cursor **只打开**当前这题的 `eval/exams/<id>/`。AEDT 打开该题 README 里的 `sandbox/`。对 Agent 说「执行测试」。不要读 `answer/`。GOAL 里的频点和带宽以那一题为准，不要拿别的考题的指标来做。
