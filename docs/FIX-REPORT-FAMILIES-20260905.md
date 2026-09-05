# Family 多选与报告旧解误报修复

2026-09-05。在 AEDT 2023 R2 的真实 ME-dipole 数据副本上，通过新 MCP stdio 进程验证；未对原考试工程求解、改参或保存。

## 原因与行为

旧实现只要调用 variables_set 就将进程布尔标志设为 dirty，导出任何报告时据此宣称 stale_solution，与 HFSS 报告是否打叉无关。现在参数修改返回 parameters_changed=true、needs_solve=null、solution_validity=unknown；不再断言必须重算。

Family 兼容原接口，并补齐每个参数多选值：

```json
{"families":{"l1":["1.05mm","1.3mm"],"lp":["0.8mm","1mm"],"d1":["0.35mm"]}}
```

- 多参数按组合选择，非 Optimetrics 显式表的逐行配对；实际返回哪些已解组合见 solution_status.traces 中的 variations。
- 数值按白名单单位解释；字符串支持带单位数值；All/Nominal 必须单独使用。旧的变量名列表仍表示 All，空列表/默认仍为 Nominal。
- report_get 从每条 trace 读取真实的 Solution/Families；不再从报告根节点猜测。trace 设置不一致时，顶层 families/solution 不提供误导性的共同值，逐条见 trace_details。
- 空闲时导出 Modal 频率报告，按实际 trace 请求 GetSolutionDataPerVariation；Nominal 在请求时解析成参数值。查询失败返回 report_solution_query_failed，不导出旧缓存。成功后 UpdateReports，再按 GUI ExportToFile 导出。
- 存在已知进行中求解时不查询、刷新报告，维持原来的缓存导出用于查看部分进度；标记 not_checked，避免将刷新调用排进求解队列。
- Z 族转换为 freq_ghz,variation,re,im；多组 re/im 的宽表保留原始带标签列，禁止静默截取第一组。

## 真实对照结果

| 情况 | 实测结果 |
|---|---|
| l1 两值 × lp 两值，其他六量显式固定 | S11 与 Z 各 4 个组合、400 行；report_get 保留两值选择 |
| 改到未解 l1=0.9137mm，全部 Nominal | HFSS 查询失败；MCP 不导出缓存 |
| 当前模型未解，但显式 Family 固定已解组合 | 4 组 Z 仍可导出，参数标签完整 |
| 切回已解最佳点，无 Analyze | Nominal 恢复可取，导出单迹与本场交卷 CSV 逐点差 0 |
| 改 Setup 的 Frequency 为 76.123GHz | 仍返回已有数据，所以有效性必须保持 unknown |
| 改铜片材料为 aluminum | Nominal 与显式 Family 查询均失败，不导出缓存 |

前置直接 COM 试验还观察到：修改 MaxDeltaS 后仍返回数据；材料改回 copper 不会自动恢复已失效的数据。不能将“参数恢复”泛化成任何模型编辑都可恢复结果。

**数据可用不等于解对当前完整模型和 Setup 有效。** 枚举报告、trace、curve 的只读属性及 COM 方法未找到原生打叉状态；GetSolutionDataPerVariation 的成功也不是替代证明。因此 solution_validity 保持 unknown，不应据此重复求解，也不能据 available 宣称 Setup 改动后的旧数据已验证。

## 验证与复现

- 103 项离线测试通过；新增 Family 多选、非法选择、Z 标签、查询失败、求解期间不刷新等回归。
- 本次实现及新增测试的 Ruff 检查通过。所查模块仍有 3 项既有 mypy 问题（live 字典值类型、fake 重复局部变量声明、app 可空列表赋值），不宣称仓库类型检查全通过。
- examples/verify_report_families_live.py 使用真实 MCP schema 和 stdio 完成 16 次接口调用，含上述正反例；不启动求解。运行前要求 AEDT 空闲，源数据是本场已完成考试的磁盘工程与结果。
- 完整调用证据：validation/report-families-20260905/evidence.json；同目录保存 MultiS.csv、MultiZ.csv、restored.csv、setup-changed.csv。
- Skill 及两套考场的旧解说明已同步；旧场日志和冻结清单保留原样。

运行中的 MCP 进程需重启才能加载新代码。代码改动尚未提交。

测试副本已关闭，原工程已重新激活并核对最终八参数。清理副本 .aedtresults 的命令被自动审批策略拒绝，约 5.5 GB 临时结果保留在仓库 .tmp-report-validity/ 下；原工程结果未删除。
