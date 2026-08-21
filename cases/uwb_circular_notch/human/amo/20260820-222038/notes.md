# 人工 Adaptive Multiple-Objective

- 工程（Save As，不要用 sandbox）: `C:\Users\Gongzhui\Documents\Projects\hfss-mcp\scratch\uwb_circular_notch_amo.aedt`
- Desktop: PID 32212（`ansysedt -grpcsrv 61887`），Optimetrics 名 `AMO_12h`
- 开始: 2026-08-20 22:20（北京时间；`SolveSetup("AMO_12h")` 已进入，OPTICOMENGINE + HFSSCOMENGINE 已起来，首点 DV129 已在写 profile）
- 结束:
- Optimizer: Adaptive Multiple Objective（HFSS `OptiOptimization`，不是 DesignXplorer 那条分支）
- 适应度（三条 Goal，不要合成一个 Cost）:
  - Setup1 : Sweep1, `max(dB(S(1,1)))` 2.5–6.3 GHz, `<= -10`, Weight 1
  - Setup1 : Sweep1, `dB(S(1,1))` 6.6 GHz, `>= -7`, Weight 1
  - Setup1 : Sweep1, `max(dB(S(1,1)))` 6.8–12 GHz, `<= -10`, Weight 1
- Number of Initial Samples: 产品默认（未改 OSF/AMO 初值个数）
- Maximum Number of Evaluations / Max elapsed: MaxNumIteration 1000，Elapsed 12 h（`MaxSolTimeInSec=43200`），Acceptable_Cost 0
- 变量（Include）: patch_r 4–12, slot_length 10–30, sw 0.5–1.5, lw 1.75–5.25, l1 8.15–24.45, l2 1–3, g1 8–24, g2 1.95–5.85, g3 2.6–7.8 mm
- 开场九点: patch_r=5.6, slot_length=12, sw=1.5, lw=5.25, l1=10, l2=1.2, g1=8.5, g2=2.0, g3=2.6
- 启动脚本: `scratch/run_amo_12h.py`（独立进程，不经卡住的 pyaedt-mcp）
- 最终变量:
- 俯视图：导体是否探出基板:
