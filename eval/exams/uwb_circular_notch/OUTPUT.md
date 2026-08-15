# 调参日志模板

复制到 `runs/<run-id>/hfss-tuning-log.md`。只写假设、矩阵设置、从一簇曲线读到的影响。不要自评分数，不要猜标称尺寸。

分组和每轴点数必须是针对**本结构这一轮**的判断。对照例子不是默认值；换到另一副天线仍能原样粘贴的理由不合格。

```markdown
# uwb_circular_notch 调参日志

- started:
- session project_path:
- allowlist: ./allowlist.json

## Round 000（开场，未扫参）

- S11 文件: round-000-s11.csv
- −10 dB 频段（目视）:
- 阻带是否可辨:
- 本结构里哪些量现在是耦合的（可不止一组）:
- 下一轮矩阵：扫哪一组、为什么是这一组（若拆组：其余组何时扫）:
- 每轴采样点与乘积（为什么是这些点，而不是随便抄一个密度）:

## Round 00N（一轮 Parametric 矩阵）

- 假设（这一组在探什么）:
- 变量与采样点（含乘积；若受 256 点上限而拆组/减密，写明）:
- Optimetrics 名:
- job_id:
- 组合表: round-00N-table.csv
- 一簇 S11: round-00N-s11.csv（freq_ghz,variation,s11_db；不要用开场那张单迹冒充）
- 哪个量影响大 / 影响什么:
- 哪个量可先钉死:
- 下一轮：换组、收窄加密、还是停（结构理由）:
```
