# me_dipole_77 调参日志

- started: 2026-09-05 10:27:25
- stopped:
- solve_total: 0s
- session project_path: C:/Users/Gongzhui/Documents/Projects/hfss-mcp/cases/me_dipole_77/sandbox/me_dipole_77.aedt
- allowlist: ../../allowlist.json
- 开考检查：runs 只有 .gitkeep；health.data_dir 与 .codex/config.toml 一致；solved_points_list count=0。
- 上下文（mm）：l1=0.9, l2=0.7, w=1.8, wp=0.4, lp=1, d1=0.2, g3=0.3, e1=0.16。
- 表达式：via_offset=l2/2+d1；ws=wp+g3；ls=lp+offset=lp-0.01mm。槽必须位于铜内，具体对应方向待模型确认。
- 覆盖表：全部白名单量尚未扫参。

## Round 000（开场，未扫参）

- S11 文件: round-000-s11.csv（待导出）
- 起点无 −10 dB 频段；76.9697 GHz 为 −9.21712 dB，不匹配，相对带宽无。
- 已看 S11 和 Z 图：浅凹只有一处，但 X 在约 66.5、81 GHz 两次过零，不能从浅凹数断言模式数。低频 R 约 13–25 Ohm 偏低；77 GHz X 约 +39 Ohm，较高频 R 隆起至约 124 Ohm，随后电容性偏强。
- 模型：两块铜辐射体、短路通孔和中间馈电结构可辨，未见破损。结合槽位保守约束 ws=wp+g3 < l1，留 0.02 mm 裕量；当前 wp+g3=0.7，因此本背景 l1 下端只能取 0.72。将来降低 wp/g3 后补试 l1=0.6。
- 第一组 l1/l2/d1：辐射长度改变电流路径，l2 和 d1 通过 via_offset=l2/2+d1 联合改变短路位置及两侧耦合，必须一起观察低边电阻和电抗的变化。第二组准备 w/wp/lp/g3/e1，按第一轮时间与馈电槽约束再拆，覆盖整个可达区间。
- 首轮轴：l1=[0.72,1.35,2]，l2=[0.25,0.625,1]，d1=[0.1,0.45] mm，3×3×2=18 点。长度与间距各取端点及中间点辨认频率搬移的非线性，偏移先用两端辨影响方向；无需触及 256 点安全阀。

## Round 001（一轮 Parametric 矩阵）

- 阶段：侦察，未正式钉定任何量。
- 假设：上述辐射长度/间距/短路偏移共同控制低边电阻与模式位置，先问宽区间响应，避免在浅凹附近微调。
- 变量与采样点：l1=[0.72,1.35,2], l2=[0.25,0.625,1], d1=[0.1,0.45] mm，共 18。
- 上下文：w=1.8, wp=0.4, lp=1, g3=0.3, e1=0.16 mm；其余保持开场。
- 覆盖表：本轮待覆盖 l1=0.72–2（受槽约束），l2=0.25–1，d1=0.1–0.45；w/wp/lp/g3/e1 未覆盖。
- 开扫前 solve_total: 0s。无本场单点计时，首轮只设 18 点作为宽疏侦察并取得实测耗时，后续据实缩放预算；保留约 3h 给逃逸。
- Optimetrics 名: Exam001_Radiator
- job_id: job_5c834f7beced46589106247d98bfcfba
- started_at: 2026-09-05T02:30:15Z
- 建立记录：首次 values 使用带单位字符串遭拒（未求解），改为数值加 unit 后成功，points=18；optimetrics_list 已确认树上节点。
- solve_time: 待完成
- 组合表: round-001-table.csv
- 一簇 S11: round-001-s11.csv
