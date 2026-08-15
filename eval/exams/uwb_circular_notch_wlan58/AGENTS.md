# 执行测试

用户说「执行测试」时，按本文件做完并停。先读 GOAL.md、OUTPUT.md 和 Skill `tune-hfss-antenna`。本考场目标是 **5.8 GHz 被占频段上的阻带** + 宽度 + 相对带宽；**手续**必须是 Optimetrics 联合扫参，不是单点改值。**预算是墙钟**：北京时间 **2026-08-14 00:00** 之前可以调；到点停。开扫前读本机系统时间，不要靠猜。

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
- 过了 **2026-08-14 00:00 北京时间** 还开新的 Parametric。时限到了必须停。

## 步骤

1. `health` 与 `session_list`。路径必须含 `sandbox`、不含 `nominal`。否则停下来让用户改开。
2. `allowlist_load`，路径为本目录 `allowlist.json`。
3. `snapshot`。新建 `runs/<YYYYMMDD-HHMMSS>/`，按 OUTPUT.md 写 `hfss-tuning-log.md`。日志写上 `started`（本机此时钟）和 `deadline: 2026-08-14 00:00 +08:00`。
4. 导出开场 `S11` 为 `round-000-s11.csv`（单迹）。写 Round 000：当前 −10 dB 频段、阻带是否可辨、**目视的阻带中心/宽度/相对带宽**（对照 GOAL，不要自评及格）；**这一轮**准备扫哪一组（几个量、为什么耦合、若拆组怎么拆）、每轴取哪些点、乘积多少。写不出结构理由就不要 `parametric_create`。若开场时已经过了时限：只交 Round 000，写 `stopped_reason: 时限已过`，停。
5. 每一轮矩阵：
   - **先看本机时钟**。已经 ≥ 2026-08-14 00:00 +08:00：不要 `parametric_create`，转入收尾。
   - 看 `parametric_create` 返回的 `points`。一轮最多 256 点（安全阀，不是推荐网格）。物理上该更大时拆组或减密，并写明是被上限卡住。矩阵要能在时限前跑完再开；开不完就拆组或减密，并写明是被墙钟卡住。
   - `parametric_create` → 确认出现在 Optimetrics → `parametric_start` → **`analyze_status` 直到 `done`**（`ok` 不是扫完；失败看 `job.error` / `messages`）。同名会改树上那个节点，不删除。
   - `parametric_export_table` 存成 `round-00N-table.csv`。
   - **另建** Results 报告（不要复用开场那张单迹 `S11`）：`report_create(report_type="modal_s", name="<该Parametric名>_S11", parametric="<该Parametric名>")`，再 `report_export` 为 `round-00N-s11.csv`（应为 `freq_ghz,variation,s11_db` 一簇）。
   - 日志写清：哪个量搬带宽/阻带频率/阻带宽度，哪个量几乎不动，下一轮换组、收窄、还是钉死。
6. 时限还没到时，至少做一轮联合矩阵。不要把预算理解成一串单点 Analyze。钉点时才 `variables_set`，不要为此单独 Analyze，除非矩阵已经指出那一组点。
7. 达标、连续两轮看不出新的影响、该问的耦合已经问完、**或墙钟到点**则停。不要因为「好像该停在某几轮」而停。时限到了：正在 `analyze_status` 的那一轮等到 `done`，写完日志，**不要再开下一轮**。最后把当前钉住的设计（没有钉点就用当前变量）导出**单迹** `s11.csv`。日志写 `stopped` 和 `stopped_reason`（达标 / 时限到点 / 问完）。不要覆盖用户的 sandbox，除非用户说保存。

## 曲线怎么读

阻抗带宽 = \(S_{11}\le -10\,\mathrm{dB}\) 的频段。先标穿越点。阻带中心看缺口里 \(S_{11}\) 最高的那个频点，不要把通带里的失配当成 5.8 GHz 阻带。从**一簇**曲线看参数影响，不要只看钉住之后的一条。
