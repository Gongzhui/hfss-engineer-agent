# 执行测试

用户说「执行测试」时，按本文件做完并停。先读 GOAL.md、OUTPUT.md 和 Skill `tune-hfss-antenna`。本考场目标是 **77 GHz 落入 −10 dB 通带 + 该段相对阻抗带宽 > 30%**；**手续**必须是 Optimetrics 联合扫参，不是单点改值。**求解时间合计不得超过 12 小时**（只计求解，自己加总），到点必须交卷。

## 禁止

- 读取或打开本文件夹以外的工程说明、`cases/`、`answer/`、`nominal/`、`eval/keys/`、源码。
- 读取 `runs/` 里已经存在的时间戳目录。开考时那里应只有 `.gitkeep`。若已有别的场次，停下来告诉用户考场不干净，不要打开那些文件夹。只写自己新建的 `runs/<时间戳>/`。
- 把最低 \(S_{11}\) 当目标。
- 调用不存在的 `trial_*` / `run_*`。
- 改几何、材料、端口、HFSS Setup。
- 用 `variables_set` + `analyze_start` 一次改一个数来冒充调参。内环必须是树上的 Parametric 矩阵。
- Optimetrics Optimization / 遗传 / 粒子群。
- 在日志里给自己打分或猜测标称尺寸。
- 把 Skill 或本文件里的对照例子当成「本轮必须用的个数 / 点数 / 轮数」。分组和密度由本结构决定，开扫前写进日志。
- 求解时间加总已满 12 小时还继续开新的扫。到点必须交卷。看图、写日志、导出不计入这 12 小时。
- 同一轮并行调用多个会进 HFSS 的 MCP 工具（`health` / `session_list` / `snapshot` / `report_*` / `variable_map` / `view_hide` / `view_show` / `view_capture` / `parametric_*`）。必须一个完成再调下一个。`allowlist_load` 可以和读文件并行，不要和 `snapshot` 并行。

## 步骤

0. Codex 开考前读取本目录 `.codex/config.toml`，确认 `health.data_dir` 与其中 `HFSS_MCP_DATA_DIR` 一致；加载白名单后检查 `solved_points_list` 没有旧场次记录。若配置不一致或出现历史记录，停止并报告，不使用旧解。开考前已有的起点解不计入考生求解预算。
1. `health` 与 `session_list`。路径必须含 `sandbox`、不含 `nominal`。否则停下来让用户改开。
2. `allowlist_load`，路径为本目录 `allowlist.json`。
3. `snapshot`。新建 `runs/<YYYYMMDD-HHMMSS>/`，按 OUTPUT.md 写 `hfss-tuning-log.md`。`started` 写本机系统时钟（北京时间）。`solve_total` 从 0 起，自己加总各轮 `solve_time`，上限 12 小时。
4. 导出开场 `S11` 为 `round-000-s11.csv`（单迹）。写 Round 000：当前 −10 dB 频段、77 GHz 附近是否已匹配；**这一轮**准备扫哪一组（几个量、为什么耦合、若拆组怎么拆）、每轴取哪些点、乘积多少。写不出结构理由就不要 `parametric_create`。
5. 每一轮矩阵**开扫前**把已记下的 `solve_time` 加总，写入 `solve_total`。累计已满 12 小时，或再开一轮会超过：不要再 `parametric_create`，按第 8 步交卷。还在扫的那一轮可以等它结束（这一轮仍计入），写完日志就收。预估不够再开一轮时，也交卷，不要赌。
6. 每一轮矩阵：
   - 看 `parametric_create` 返回的 `points`。一轮最多 256 点（安全阀，不是推荐网格）。物理上该更大时拆组或减密，并写明是被上限卡住。
   - `parametric_create` → 确认出现在 Optimetrics → `parametric_start` → **`analyze_wait` 直到 `done`**（`ok` 不是扫完；失败看 `job.error` / `messages`）。等待按 Skill 的 `analyze_wait` 规则执行：超时继续等待同一任务，失败或未验证状态先处理；利用宿主后台等待，避免无新信息时反复 sleep 或播报。同名会改树上那个节点，不删除。扫完立刻用 job 的 `started_at` / `finished_at`（或自己记下的起止）写出本轮 `solve_time`，再加进 `solve_total`。单独 `analyze_start` 同样要记一笔 `solve_time`。
   - `parametric_export_table` 存成 `round-00N-table.csv`。
   - **另建** Results 报告（不要复用开场那张单迹 `S11`）：`report_create(report_type="modal_s", name="<该Parametric名>_S11", parametric="<该Parametric名>")`，再 `report_export` 为 `round-00N-s11.csv`（`freq_ghz,variation,s11_db`）。variation 是 Export Data 表里各变量列拼成的参数组合（和图例同一句话），用来认出每条线是哪一组点。All 里出现同一量的历史取值是正常的。
   - 日志写清：哪个量搬带宽/中心，哪个量几乎不动，下一轮换组、收窄、还是钉死。`variables_set` 之后看模型：从 `snapshot` 的 `objects` 认名字，用 `view_hide` 藏占画面的东西，要盯某一块就 `view_capture(fit=["那块的名字"])`。看出来几何错了就写进日志，不要留那组点。看完 `view_show` 还原。
7. 至少做一轮联合矩阵。不要把预算理解成一串单点 Analyze。钉点时才 `variables_set`，不要为此单独 Analyze，除非矩阵已经指出那一组点。改完参数就看模型。
8. **只有**两项都达标、或第 5 步已经判定再开一轮会超过 12 小时：停并交卷。没达标且预算还够，**不准停**。不要用「连续两轮看不出新的影响」「该问的耦合已经问完」「好像该停在某几轮」当停手理由，也不要只扫一次就交差。上一轮看出两个量互斥，下一轮就要把它们放进同一张联合矩阵（或改到中间值再问），这不叫问题已经问完。交卷：钉住当时最好的一组（`variables_set` 的键是 `name` 或 `variable`，返回 `needs_solve`）。模型已经明显错了的点不要交。导出**单迹** `s11.csv` 用新报告名 + `families=[]`，不要复用开场 `S11`。报告的 Family 选择与数据可用性按 Skill 核对；`solution_validity=unknown` 不等于旧解，不要为清除该状态重算。日志写 `stopped`（本机时钟）和最终 `solve_total`。不要覆盖用户的 sandbox，除非用户说保存。

## 曲线怎么读

阻抗带宽 = 包含 77 GHz 的那段连续 \(S_{11}\le -10\,\mathrm{dB}\)。相对带宽用这段的两端外沿，不要拼不相邻的段。77 GHz 仍高于 −10 的浅凹不算。从**一簇**曲线看参数影响，不要只看钉住之后的一条。
