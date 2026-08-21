# 人工对照（不经过 Agent）

人在 AEDT 里用 Optimetrics **Optimization** 调这副天线。不是考场、不用 MCP、不写 Agent 日志。

```
cases/uwb_circular_notch/human/
  README.md
  aso/                       # Adaptive Single-Objective (Gradient)
    README.md
    notes.md
    <YYYYMMDD-HHMMSS>/
      notes.md
      s11.csv
      table.csv              # 可选
      top.jpg                # 可选
  amo/                       # Adaptive Multiple-Objective (Kriging + MOGA)
    README.md
    notes.md
    <YYYYMMDD-HHMMSS>/
      notes.md
      s11.csv
      table.csv
  ga/                        # 已弃用内置 GA (Random search)
    README.md
    notes.md
    <YYYYMMDD-HHMMSS>/
  pso/                       # 以后若用手点或外挂粒子群，再开
```

工程请 **Save As** 到仓库 `scratch/`，不要在应试用的 `sandbox/` 上直接优化。开场九点与考场相同。三项指标仍按那张卷看：6.6 GHz 须高于 −7 dB、宽度 ≤ 0.5 GHz、包络相对带宽 ≥ 130%。求解记下墙钟即可，不必套 Agent 的 `solve_time` 格式。
