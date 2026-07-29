# FINDINGS — benchmark 构建过程中的产品与生态发现

随 benchmark 设施交付。产品（src/）一律未改；需要产品侧跟进的列在最后。

## F1 · 产品 trial 机制直接吃得下真实范例（正面）

`build_case.py --stage answer` 全程走 in-process `AppContext` + supervisor worker +
workspace 副本：2 trial（nominal/broken）均 completed，Touchstone 真导出（2 波端口
工程导出为 .s1p，S11 列解析正确），metrics 与重解析一致（1e-6 容差）。
**benchmark 答案册求解无需任何降级或产品改动。**

## F2 · AEDT 2023 重存引入的新型泄露：oa/sa/ta 调优元数据

2018 年的范例原文 `VariableProp('fl', 'UD', 'desc', '0.3mm')` 无附加信息；
AEDT 2023 R2 保存后变成 `VariableProp('fl', 'UD', '', '0.2316mm', oa(Min='0.15mm',
Max='0.45mm', ...), sa(...), ta(...))`——白名单变量的 (Min+Max)/2 **恰等于标称值**。
沙箱构建必须把白名单变量的 VariableProp 行重写回纯 4 参数形式，
verify_case.py 有对应检查（check 5）。**这是任务书列举之外的第 5 类泄答案源。**

## F3 · pyaedt 1.3 两个坑（沙箱 authoring 侧已规避）

1. **先文本剥离再打开**（预先删掉 ReportManager/Report2D/Documentation 块）会让
   pyaedt 初始化报 `AttributeError: 'NoneType'.GetName`（拿不到 active design）。
   规避：先 API（删 design/删报告/改值/保存），文本剥离殿后；最终剥净的文件
   pyaedt 能正常打开（validate reopen 证明，trial worker 同款打开路径）。
2. `hfss.post` 层在该工程上初始化即崩（枚举 plots → `variables.GetObjType` 深处
   AttributeError）——pyaedt 1.3 的 PostProcessor 对含历史报告的工程不健壮。
   规避：`hfss.odesign.GetModule("ReportSetup")` COM 直调 `GetAllReportNames` /
   `DeleteReports`。产品 metrics 模块走 Touchstone 导出，不经过 post 层，不受影响。
3. pyaedt 异常退出残留 `.aedt.lock` 与 `.aedtresults/`，后续打开报
   `Project is locked`；脚本需先清锁再开。

## F4 · 产品缺口（benchmark authoring 需要、产品没有；未顺手改）

- 无「删除 design / 删除报告 / 剥除存解记录」类工具——沙箱 authoring 只能用
  PyAEDT 直连（属一次性构建，不进运行期路径）。若未来 benchmark 要扩到
  「在线修复泄露工程」类 case，产品需补这些原语。
- `trial_start` 的 `parameters` 经 MCP 传 list、in-process 传 `{"values": [...]}`，
  两种形态并存；文档未写明，靠读源码确认。不影响功能。

## F5 · 已知边界（不构成泄露）

- 沙箱中 14 个非白名单变量保持标称值——它们是题面（被调坏天线的固定结构），
  审计只强制白名单 5 变量 ≠ 标称。任务书「不得出现任何标称值」按此意图执行。
- AEDT 打开工程即重建空 `.aedtresults/` 与 `.pyaedt/` 目录（无内容）；构建结束时清除，
  verify 把它们列为 finding（check 7）。
