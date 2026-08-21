# 人工 Adaptive Single-Objective

- 工程（Save As，不要用 sandbox）: `C:\Users\Gongzhui\Documents\Projects\hfss-mcp\scratch\uwb_circular_notch_aso_run.aedt`（`uwb_circular_notch_aso.aedt` 被另一份 GUI 锁住，实际求解在这份拷贝上）
- Desktop: PID 17968（`ansysedt -grpcsrv 57377`），Optimetrics 名 `ASO_12h`
- 开始: 2026-08-20 13:57（北京时间；`SolveSetup("ASO_12h")` 已进入，HFSSCOMENGINE 已起来）
- 结束:
- Optimizer: Adaptive Single-Objective (Gradient)
- 适应度（写明计算式或 GUI 里怎么填）:
  - Setup1 : Sweep1, `max(dB(S(1,1)))` 2.5–6.3 GHz, `<= -10`, Weight 1
  - Setup1 : Sweep1, `dB(S(1,1))` 6.6 GHz, `>= -7`, Weight 1
  - Setup1 : Sweep1, `max(dB(S(1,1)))` 6.8–12 GHz, `<= -10`, Weight 1
  - 若 ASO 只允许一个 Goal：6.6 GHz 当 Goal，两条通带改 Constraint
- Number of Initial Samples: 55（九变量默认 `(n+1)(n+2)/2`）
- Maximum Number of Evaluations: 600（12 小时预算，约 1 分钟/点）
- 变量（Include）: patch_r 4–12, slot_length 10–30, sw 0.5–1.5, lw 1.75–5.25, l1 8.15–24.45, l2 1–3, g1 8–24, g2 1.95–5.85, g3 2.6–7.8 mm
- 开场九点: patch_r=5.6, slot_length=12, sw=1.5, lw=5.25, l1=10, l2=1.2, g1=8.5, g2=2.0, g3=2.6
- 可选约束: l1 + 2*patch_r <= 33 mm
- 最终变量:
- 俯视图：导体是否探出基板:
