# hfss-mcp benchmark 设施

评测脚本留在这里。真实天线工程（范例 + 沙箱 + 答案册）在仓库根目录 `cases/`。

V1 不再用 `trial_*` 脚本跑分。演示是：打开某个 case 的 `sandbox/`，加载 `allowlist.json` / `case.json`，按 Skill `tune-hfss-antenna` 调。

- **答案册**（`cases/<id>/answer/`）：标称值与参考曲线——只给评分/对照用。不要让 Agent 读。
- **沙箱**（`cases/<id>/sandbox/`）：失配工程。
- **审计**（`verify_case.py`）：确认沙箱零泄露。

## 现有 case

- `cases/uwb_circular_notch/`：论文 §3.1 圆形单极子 + U 槽。nominal 有端口并已求解；sandbox 是 Save As 后再拧 8 个参数（≤50%）。
- `benchmark/cases/siw_feed_l1/`：厂商例题沙箱（尚未迁到 `cases/`）。白名单 `fl fw fx fy t1`，Setup1 / Sweep，目标 60 GHz。
