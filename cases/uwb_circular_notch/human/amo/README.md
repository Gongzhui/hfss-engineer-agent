# 人工：Adaptive Multiple-Objective

本想走 GUI：**HFSS → Optimetrics → Add Screening & Optimization**，Optimizer = **Adaptive Multiple Objective (Random-search)**（Kriging + MOGA）。2023 R2 脚本里 `OptiDesignExplorer` 插得进去，但 Initial Samples / Samples Per Iteration 写不进节点，求解只会打开场那一个点。

12 小时全局对照改用同门的 in-Desktop **Design of Experiments / Optimal Space-Filling**（`OptiDXDOE`，User-Defined 1080 点）。这是 AMO 的 Screening 阶段，不是后续 Kriging 加点。三条 \(S_{11}\) 目标仍分开填。

工程 Save As 到仓库 `scratch/uwb_circular_notch_dxamo.aedt`，不要写 `sandbox/`。开场九点与考场相同。墙钟上限 12 小时。

一局一个时间戳文件夹。结束后导出 S11 为 `s11.csv`，能导出 Optimetrics 表就放 `table.csv`。
