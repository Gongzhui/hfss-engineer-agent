# hfss-mcp benchmark 设施

用「故意调错的真实天线工程」检验 hfss-mcp 工具链能否把天线调回来。

- **答案册**（`answer/`）：标称值、真实求解的标称/失配 Touchstone 与指标——只给评分用。
- **沙箱**（`sandbox/`）：剥掉存解、报告、兄弟 design 与文档引用后的失配工程——只给被测工具用。
- **运行器**（`run_case.py`）：经 MCP stdio 真调 manifest/trial 工具链，在预算内调参并出 `report.json`。
- **审计**（`verify_case.py`）：确认沙箱零泄露，发现即非零退出。

## 添加一个新 case（不改任何代码）

1. 新建目录 `benchmark/cases/<case_id>/`（`<case_id>` 匹配 `[a-z0-9_]+`）。
2. 写 `case.json`（唯一的手工文件），字段：
   - `source`：`project_path`（原始工程，只读）、`design_name`、`setup`、`sweep`、`port`、
     `sibling_designs`（必须从沙箱删除的兄弟 design，它们持有同名标称值）。
   - `variables`：白名单 `[{name, unit, min, max}]`——运行器只允许调这些；
     `[min, max]` 必须覆盖 标称值×(1±max_pct)。
   - `perturbation`：`seed` + `min_pct`/`max_pct`。确定性算法：按 variables 顺序
     `pct~U(min,max)`、`sign~{±1}`（`random.Random(seed)`），
     `value=round(nominal*(1+sign*pct/100), 4)`。
   - `metrics`：`band_ghz`、`target_ghz`、`primary`、`thresholds`
     （键是指标名，值是 `<=` 阈值；S11 越低越好）。
   - `budget`：`max_trials`、`max_runtime_seconds`（也用作单次求解超时）。
3. 建议先侦察源工程（只读、文本解析，不启动 AEDT）：
   `uv run python benchmark/build_case.py --case <case_id> --stage probe`
4. 构建：`uv run python benchmark/build_case.py --case <case_id>`
   （answer 阶段走 hfss-mcp 自己的 trial 机制真实求解；sandbox 阶段用 PyAEDT 剥离+扰动）
5. 审计：`uv run python benchmark/verify_case.py --case <case_id>` → 必须打印 `LEAK-FREE`。
6. 冒烟：`uv run python benchmark/run_case.py --case <case_id> --policy probe`

## 目录约定

```
cases/<case_id>/
  case.json            # 手工：case 定义（唯一输入）
  answer/              # 生成：nominal_values.json / perturbation.json / metrics.json / *.sNp
  sandbox/             # 生成：<case_id>_sandbox.aedt（剥净+扰动后的工程）
  manifest.json        # 生成：锁定沙箱工程的 hfss-mcp manifest（白名单=case variables）
  build/               # 生成：中间产物（可再生，不入库）
  runs/<run_id>/       # 生成：report.json 与 trial Touchstone 取证
```

## 不变量

- 源工程只读；一切 AEDT 操作作用于副本。
- 沙箱不得含：Soln 存解记录、Report2D/ReportManager、Documentation 引用、ProjectPreview、
  兄弟 design、白名单变量的标称值、答案册路径。由 `verify_case.py` 强制。
- 运行器只碰沙箱与 manifest；答案册仅用于评分对比。
- 每个脚本结束自清理自己 spawn 的 ansysedt.exe（不碰别人的会话）。

## 首个 case：siw_feed_l1（L1）

源：AEDT 2023 R2 自带范例 `5G_SIW_Aperture_Antenna.aedt` 的 `SIW Feed Structure`
（Driven Modal、2 波端口、Setup1@60GHz、Sweep 56–67GHz/0.1 步进、19 个字面值变量）。
白名单 5 个馈电变量 `fl fw fx fy t1`（±40% 区间，约以标称值为中心——区间设计即难度设计，
更严的 case 可偏移区间中心），seed=42 扰动 ±10–30%，预算 6 trial。
probe 策略：t1 测失配基线，之后每变量一次坐标移动（取区间中点，优则留、劣则弃；
候选求解失败 = 消耗一次预算并弃置该移动，不中断运行）。
