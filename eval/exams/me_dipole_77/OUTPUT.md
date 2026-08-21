# 调参日志模板

复制到 `runs/<run-id>/hfss-tuning-log.md`。只写假设、矩阵设置、从一簇曲线读到的影响。不要自评分数，不要猜标称尺寸。`started` / `stopped` 用本机系统时钟（北京时间）。本场预算是 **求解时间合计 4 小时**：只计 `parametric_start` / `analyze_start` 到 `done`；看图、写日志、导出不算。每轮写 `solve_time`，自己加总到 `solve_total`。累计满了必须写下 `stopped` 并交卷。未达标且还能再开一轮时不要写停。

分组和每轴点数必须是针对**本结构这一轮**的判断。对照例子不是默认值；换到另一副天线仍能原样粘贴的理由不合格。

```markdown
# me_dipole_77 调参日志

- started:
- stopped:
- solve_total:  # 自己把各轮 solve_time 加总；上限 4 小时
- session project_path:
- allowlist: ./allowlist.json

## Round 000（开场，未扫参）

- S11 文件: round-000-s11.csv
- −10 dB 频段（目视）:
- 最靠近 77 GHz 的点是否 ≤ −10 dB:
- 相对带宽目视（含 77 GHz 的那一段通带外沿 \(f_L\)、\(f_H\)，\(2(f_H-f_L)/(f_H+f_L)\)）:
- 本结构里哪些量现在是耦合的（可不止一组）:
- 下一轮矩阵：扫哪一组、为什么是这一组（若拆组：其余组何时扫）:
- 每轴采样点与乘积（为什么是这些点，而不是随便抄一个密度）:

## Round 00N（一轮 Parametric 矩阵）

- 假设（这一组在探什么）:
- 变量与采样点（含乘积；若受 256 点上限而拆组/减密，写明）:
- Optimetrics 名:
- job_id:
- solve_time:  # 本轮求解，例如 12m30s 或 750s；job 的 started_at → finished_at
- 组合表: round-00N-table.csv
- 一簇 S11: round-00N-s11.csv（freq_ghz,variation,s11_db；不要用开场那张单迹冒充）
- 哪个量影响大 / 影响什么:
- 模型看起来有没有错（`variables_set` 之后看过；该藏的藏、该 fit 的 fit）:
- 哪个量可先钉死:
- 下一轮：换组、收窄、把互斥量放进同一张联合矩阵；仅两项达标或再开一轮会超 4 小时才停:
```
