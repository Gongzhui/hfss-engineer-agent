# BLOCKED — 待裁决清单（benchmark 设施目标）

随交付提交。分类：A = 基线核对出入（证据+处置）；B = 顺手活（按任务书不做）；C = 已自行裁决（按任务书意图，备查）。

> 上一目标（真实 AEDT V0 演示）的 BLOCKED 全文在 git 历史（末次 8369a2a）。

## A · 基线核对出入

- **ruff 2 errors 来自可再生缓存**：按任务书顺序先跑 pytest 后，`ruff check .` 报
  I001/E701 两条，定位在 `.tmp_pytest/gen_py/3.12/__init__.py`——pywin32 COM 缓存
  （文件头自述 "this directory may be deleted to reset the COM cache"），由
  test_real_aedt 的 COM 调用生成。删除该目录后 ruff 回到 0，与任务书基线一致。
  非代码问题，未改任何产品/配置文件。

## B · 顺手活（按任务书一律不做，列此待裁决）

1. ~~旧运行产物 `.tmp_pytest/`、`examples/demo_output/`、`examples/golden_patch.aedtresults/`~~
   **已处置（2026-08-11）**：三个目录及 benchmark 游离时间戳 run 目录已删除（可再生），
   并补入 `.gitignore`；正式验收证据 `run_probe_main`/`run_probe_failcheck` 早已入库未动。
2. 产品无「删除 design / 删除报告 / 剥除存解记录」原语（benchmark authoring 需要，
   运行期不需要）——按规矩未改产品，记录于 `benchmark/FINDINGS.md` F4。
3. pyaedt 1.3 两处缺陷：post 层对含历史报告的工程初始化即崩；异常退出残留
   `.aedt.lock` 致后续 `Project is locked`——升级依赖属产品决策，未动（FINDINGS F3）。
4. MCP `trial_start` 的 `parameters` 存在 list 与 `{"values": [...]}` 两种合法形态，
   文档未写明——文档改动属产品范围，记 FINDINGS F4 备查。

## C · 已自行裁决（按任务书意图，备查）

1. **「沙箱不得出现任何标称值」的解释**：14 个非白名单变量必须保持标称值——
   它们是题面（被调坏天线的固定结构），否则 design 本身就变了。审计强制的是：
   白名单 5 变量的标称值不得以任何形式出现（值槽 + oa/sa/ta 元数据 + 报告/存解）。
   见 FINDINGS F5。
2. **阈值数据驱动（两轮标定）**：case.json 先写占位值建骨架；答案册出来后改 -3.5/-14.0
   （按「probe 接近标称」估计）；主跑 v2 实测 probe 在 6 trial（含 1 次候选区域不可解）
   恢复到 -2.0051/-13.13——6 trial 预算 + 一个不可解区域下部分恢复才是本 case 的真实
   难度，最终标定为 **S11@60GHz ≤ -1.9、S11_min ≤ -13.0**（对探针实测值余量 ≥0.1dB，
   探针确定性可复现：同条件重跑 cross-check 差 0.0）。属 case 数据设计，全程留痕。
3. **答案册求解形态**：走 in-process `AppContext`（产品 manifest/trial 机制本体），
   未走 MCP stdio——任务书要求「优先仓库自有 manifest/trial 机制」，in-process 即
   该机制本身且少一层进程开销；MCP stdio 协议路径由任务 4 的 run_case 全覆盖。
4. **白名单区间设计**：区间 = 标称×[0.65, 1.45]（中点≈标称×1.05）。probe 探针策略
   （坐标下降朝区间中点）因此确定性收敛；「区间设计即难度设计」已写进 README，
   未来更严 case 可偏移区间中心。
5. **任务 4 反向验证省钱法**：不可能阈值 + `--max-trials 1`（1 次真实 trial 即触发
   runner 的 FAIL 判定路径），不烧满 6 trial；反向验证目标的是 runner 判定逻辑，
   不是调参物理。
