# 人工：Adaptive Single-Objective (Gradient)

Optimetrics → Add → Optimization... → Optimizer 选 **Adaptive Single-Objective (Gradient)**（OSF + Kriging + MISQP）。不要用 Legacy 的 SNLP / Quasi-Newton，也不要 GA。

工程 Save As 到仓库 `scratch/uwb_circular_notch_aso.aedt`，不要写 `sandbox/`。开场九点与考场相同。

一局一个时间戳文件夹。适应度或 Setup 改了就新开一局。把 `notes.md` 拷进去填：适应度、Initial Samples、Maximum Number of Evaluations、起止时间、最终尺寸、铜有没有探出基板。结束后导出 S11 为 `s11.csv`。
