# hfss-mcp benchmark 设施

用「故意调错的真实天线工程」给 Host Agent 当沙箱。评分用的答案册在 `answer/`，给 Agent 的失配工程在 `sandbox/`。

V1 不再用 `trial_*` 脚本跑分。演示是：打开 `sandbox/` 工程，加载 `case.json` 当 allowlist，按 Skill `tune-hfss-antenna` 调。

- **答案册**（`answer/`）：标称值、Touchstone 与指标——只给评分/对照用。不要让 Agent 读。
- **沙箱**（`sandbox/`）：剥掉存解后的失配工程。
- **审计**（`verify_case.py`）：确认沙箱零泄露。

## 现有 case

`cases/siw_feed_l1/`：白名单 `fl fw fx fy t1`，Setup1 / Sweep，目标 60 GHz。阈值见 `case.json`。
