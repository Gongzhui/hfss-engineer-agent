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
- `variables_set` 用来把矩阵里的一组点写进活模型。不要求解、不要保存。返回 `needs_solve: true`：Results 仍是上一份已解的 variation，不是刚写入的值。几何会立刻跟着变，看模型不必 Analyze。
- **每次改完参数都要看模型。** 怎么看是你的判断（看哪几个零件、什么角度、看几张都不是清单），但有一条底线：模型已经不像原来那副天线，这组点就不能留。可用的看图工具见「看模型」一节。
- `variables_set` 的参数键是 `name` 或 `variable`；`parametric_create` 的扫参键同样是 `variable` 或 `name`。两种写法等价。
- `parametric_start` / `analyze_start` 的 `ok: true` **只表示任务已受理**，不是扫完。看 `done`。未 `done` 就必须 `analyze_status`（里面有 Message Manager 最近几行，这就是进度）。`failed` 时读 `job.error` 和 `messages`，不要空等。
- `analyze_status` 返回 `job_not_found`：job 注册表在 MCP 服务内存里，宿主（idle 超时）重启过服务就会丢句柄。此时**不要重开扫**——AEDT 里的扫描还在跑，改用 `report_export` 数迹线/`optimetrics_list` 判断扫完。根治法：宿主的 mcp.json 给 hfss-mcp 设 `lifecycle: "keep-alive"`。
- **钉固定量必须在 `parametric_start` 之前完成。** 求解进行中调用 `variables_set` / `parametric_create` / `report_create` 会被服务器直接拒绝（`solve_in_progress`）——这是保护：AEDT 会把它们推迟到扫完才执行，期间连 `analyze_status` 都会排在后面卡死。求解中只发 `analyze_status`（进度）和 `report_export`（数迹线，允许）。
- **禁止** `trial_*` / `run_*`。
- 不自动保存。有明显进展才 `project_save(mode="save_as")`。用户说「直接保存」才 `mode="save"`。
- 推理写在 `hfss-tuning-log.md`。开扫前必须写清：**为什么是这一组、为什么是这些采样点**。写不出结构理由就还没到 `parametric_create`。
- **不要并行调用 hfss-mcp 的 HFSS 工具。** AEDT 的 COM / `RunScript` 同一时刻只能进一个；并行 `health`+`snapshot` 或几个 `report_*` 会在 `SetActiveProject` 上卡死。同一轮里这些调用要串行。求解期间轮询 `analyze_status` 除外。

## 看模型

截图不依赖用户的 GUI 状态：每次 `view_capture` 都是导出时按名单现渲染的，你看到的图就是当时的真实几何。这几个工具怎么组合用由你定：

- `snapshot` 的 `objects` 列出全部零件名，先认名字。
- `view_hide(names)` / `view_show`：纯记账的排除名单。被排除的物体之后每张截图都完全不渲染（适合辐射盒、大地板、基板、接头这类占画面的东西——以**这一副**为准，工具不会替你猜哪个是空气盒）。不动用户的 GUI；`view_show(all_objects=true)` 清空名单。
- `view_capture`：`orientation` 只能是 isometric/top/bottom/front/back/left/right（其它值直接被拒）；传 `fit=["零件名"]` 则这一张**只渲染**这些零件并框满它们，适合盯某一块铜。不传就渲染「全部 − 排除名单」。

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

`health` → `session_list` → `allowlist_load` → `snapshot` → `variable_map` / `view_hide` / `view_capture` / `view_show` → `optimetrics_list` → `parametric_create` → `parametric_start`（`analyze_status` 轮询）→ `parametric_export_table` + **新的** Results 报告 `report_create(..., parametric=<该矩阵名>)` → `report_export`。钉点时 `variables_set`，随后再看模型。

白名单：考场用该目录 `allowlist.json`；否则 `cases/uwb_circular_notch/allowlist.json`。

同名 Parametric 再 `parametric_create` 会 **EditSetup**（树上那个节点被改掉，不删除）。粗扫改成精扫可以沿用名字；换一组变量建议换名字，免得和用户原来的扫参混在一起。

开场那张单迹 `S11` **不会**因为后来扫了参就自动变成一簇。矩阵跑完后必须再建一份人看得到的报告（例如 `<Parametric名>_S11`），用 `parametric=<该矩阵名>`（或显式 `families`）把扫过的量设成 All——和 GUI 里把 Family 设成 All 一样，同一量历史上解过的点都会出现在这簇里。其它量钉在 Nominal。`report_export` 走的是 GUI 右键 **Export Data**（Separate Columns 关掉）：原生表是每个扫过的量一列，再加 Freq 和 \(S_{11}\)。交给 Agent 的 CSV 是 `freq_ghz,variation,s11_db`，**variation 就是那几列拼成的参数组合**（例如 `g1='8.5mm' l2='1mm' lw='1.75mm'`），和图例一致。`labeled: true` 表示能分清每条线是哪一组点；不要按 Optimetrics 表的行序去对。不要把开场那条单迹当成矩阵结果。同名报告若已经在 Results 里，再带 family / Nominal 钉死会报 `report_exists`——换个新名字。

钉住之后若要单条曲线，新建一份报告：省略 `families`/`parametric`，或传 `families=[]`。两者都把已知 Parametric 量钉在 Nominal，不会把所有矩阵当成 All。若刚 `variables_set` 还没 Analyze，`report_export` 会带 `stale_solution`：那条 CSV 仍是上一份已解的点。

`field_face` 需要 `face` 和 `frequency`。插值扫频常常没存场，失败就继续看簇曲线，不要改 HFSS Setup 去强行存场。

## Loop

1. `health` / `session_list`。没有 Desktop 就让用户先打开工程。
2. `allowlist_load`。`snapshot`。不熟则 `variable_map`，并自己 `view_hide` / `view_capture`。
3. 写清这一轮在调匹配还是相位。按上一节排出分组和采样，写入日志，再 `parametric_create`（须在树上能看见；看返回的 `points`）→ `parametric_start` → **`analyze_status` 直到 `done`**。不要把 start 的 `ok` 当成扫完。
4. `parametric_export_table` 是组合表。再 `report_create` 一份带 family 的 Results 图并 `report_export`。看哪条曲线随哪个量动、哪个量几乎不动。
5. 敏感的留下，不敏感的可以钉死。下一轮换一组，或同一组收窄加密。钉点时才 `variables_set`。**改完就看模型**（自己 `view_hide` / `view_capture(fit=…)`，看出几何错误就不要留这组点）。钉住之后如需单条曲线，再导出不含 family 的新报告（省略 `families`，或 `families=[]`）。不要复用开场那张 `S11` 来「钉死」。
6. 重复。停手只有：观察量已经达标；或（考场）再开一轮会超过求解时间上限。没达标且时间还够，就必须再开一轮。上一轮看出互斥，下一轮把互斥的量放进同一张联合矩阵（或改中间值再问）。不要用「连续两轮看不出新的影响」「该问的耦合已经问完」「跑满某几轮」当停手理由，也不要只扫一次就交差。

## Diagnose

从**一簇**曲线看谁在搬带宽、谁在搬通带中间的抬起，不要只看钉住之后的一条，也不要只看三个标量。曲线好看但模型已经错了的点，不要当答案。

- 匹配：\(S_{11}\le -10\,\mathrm{dB}\) 的穿越点。低频**整段**抬起，馈电/地板往往要进**同一组**矩阵，不要先整体缩放贴片。
- 通带中间回到 −10 dB 以上的抬起才像阻带，不要和匹配失败混在一起。
- 身份不清时看 Smith / `terminal_z`：宽频游走像匹配空洞，小环或急转像谐振器。
- 相位：四个态是否大约隔 90°，谁在转相位、谁在毁匹配。
- 不要用单点跳跃代替矩阵。单点证伪（「改了某个量一次没动」）证据不足。

```bash
uv run python skills/tune-hfss-antenna/scripts/plot_s11.py path/to/s11.csv --mark-ghz 60 --out hfss-tuning-artifacts/round-00N/s11.svg
```

`plot_s11.py` 画 `freq_ghz,s11_db` 或 `freq_ghz,variation,s11_db` 的一簇曲线。

## Demo case

考场：宿主 Agent（Pi / Cursor）**只打开**当前这题的 `eval/exams/<id>/` 目录。AEDT 打开该题 README 里的 `sandbox/`。对 Agent 说「执行测试」。不要读 `answer/`。GOAL 以那一题为准。
