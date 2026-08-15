# 执行测试

用户说「执行测试」时，按本文件做完并停。先读 GOAL.md、OUTPUT.md 和 Skill `tune-hfss-antenna`。本考场目标是阻抗带宽 + 清晰阻带；**手续**必须是 Optimetrics 联合扫参，不是单点改值。

## 禁止

- 读取或打开本文件夹以外的工程说明、`cases/`、`answer/`、`nominal/`、`eval/keys/`、源码。
- 读取 `runs/` 里已有的旧场次。只写自己新建的 `runs/<时间戳>/`。
- 把最低 \(S_{11}\) 当目标。
- 调用不存在的 `trial_*` / `run_*`。
- 改几何、材料、端口、HFSS Setup。
- 用 `variables_set` + `analyze_start` 一次改一个数来冒充调参。内环必须是树上的 Parametric 矩阵。
- Optimetrics Optimization / 遗传 / 粒子群。
- 在日志里给自己打分或猜测标称尺寸。
- 把 Skill 或本文件里的对照例子当成「本轮必须用的个数 / 点数 / 轮数」。分组和密度由本结构决定，开扫前写进日志。

## 步骤

1. `health` 与 `session_list`。路径必须含 `sandbox`、不含 `nominal`。否则停下来让用户改开。
2. `allowlist_load`，路径为本目录 `allowlist.json`。
3. `snapshot`。新建 `runs/<YYYYMMDD-HHMMSS>/`，按 OUTPUT.md 写 `hfss-tuning-log.md`。
4. 导出开场 `S11` 为 `round-000-s11.csv`（单迹）。写 Round 000：当前 −10 dB 频段、阻带是否可辨；**这一轮**准备扫哪一组（几个量、为什么耦合、若拆组怎么拆）、每轴取哪些点、乘积多少。写不出结构理由就不要 `parametric_create`。
5. 每一轮矩阵：
   - 看 `parametric_create` 返回的 `points`。一轮最多 256 点（安全阀，不是推荐网格）。物理上该更大时拆组或减密，并写明是被上限卡住。
   - `parametric_create` → 确认出现在 Optimetrics → `parametric_start` → **`analyze_status` 直到 `done`**（`ok` 不是扫完；失败看 `job.error` / `messages`）。同名会改树上那个节点，不删除。
   - `parametric_export_table` 存成 `round-00N-table.csv`。
   - **另建** Results 报告（不要复用开场那张单迹 `S11`）：`report_create(report_type="modal_s", name="<该Parametric名>_S11", parametric="<该Parametric名>")`，再 `report_export` 为 `round-00N-s11.csv`（应为 `freq_ghz,variation,s11_db` 一簇）。
   - 日志写清：哪个量搬带宽/阻带，哪个量几乎不动，下一轮换组、收窄、还是钉死。
6. 至少做一轮联合矩阵。不要把预算理解成一串单点 Analyze。钉点时才 `variables_set`，不要为此单独 Analyze，除非矩阵已经指出那一组点。
7. 达标、连续两轮看不出新的影响、或该问的耦合已经问完则停。不要因为「好像该停在某几轮」而停，也不要只扫一次就交差。最后钉住的设计再导出**单迹** `s11.csv`（`families=[]` 或钉点后的当前设计）。不要覆盖用户的 sandbox，除非用户说保存。

## 曲线怎么读

阻抗带宽 = \(S_{11}\le -10\,\mathrm{dB}\) 的频段。先标穿越点。从**一簇**曲线看参数影响，不要只看钉住之后的一条。
