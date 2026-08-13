---
name: tune-hfss-antenna
description: Tune allowlisted parameters on an existing HFSS/AEDT antenna via the hfss-mcp MCP server. Diagnose from S11 (dip frequency vs target, matching depth), change one hypothesis per trial, and keep a markdown log. Use when the user wants to recover matching, tune S11, or run the siw_feed_l1 sandbox demo. Do not use to build geometry from scratch.
---

# Tune HFSS antenna

Host Agent 当工程师：看曲线、下假设、改一刀、再看。hfss-mcp 只执行白名单 trial。单次求解约 6 分钟，预算按 manifest 的 `max_trials`。

## Hard rules

- 只调 manifest 白名单变量；禁改几何、材料、端口、setup。
- `trial_start` 必须提交**完整**参数向量（每个白名单变量都带 `name` / `value` / `unit`）。
- **禁止**调用 `run_start` / `run_resume`（那是随机搜索，不是本 Skill）。
- 求解失败 = 消耗一次预算、记下该区域、换假设。不要同一点重试。
- 推理只写在 `hfss-tuning-log.md`，不要只留在聊天里。

## Tools

用：`health` → 读仓库里的 manifest JSON → `manifest_validate` → `design_snapshot` → `trial_start` → 轮询 `trial_status` → `trial_result`。

`trial_start.parameters` 形态：`[{"name":"fx","value":3.255,"unit":"mm"}, ...]`（全部白名单，不是增量）。

轮询间隔 15–30s，直到 `completed` / `failed` / `cancelled`。不要并行 trial。

## Loop

1. `health`：`real_hfss_ready` 必须为 true。否则停下来告诉用户启动 AEDT/检查 MCP。
2. 读 case 的 `manifest.json`，`manifest_validate`，记下 `manifest_id`。
3. `design_snapshot` 拿当前值和单位。未改参先跑一次 baseline trial。
4. 看结果，写一条假设（例如「最低点在带沿 67 GHz，谐振偏高，优先动馈电偏移 fx」）。
5. 只改与该假设相关的 1 个变量（最多 2 个强耦合变量），其余保持上一轮最佳。
6. `trial_start` → 等结果 → 用曲线或三个标量证实/推翻 → 追加日志。
7. 达标、预算用尽、或连续两轮无物理进展则停。

## Diagnose

`trial_result.metrics` 至少有：`S11_at_target_dB`、`S11_min_dB`、`S11_min_freq_GHz`。

- 最低点频点 **高于** 目标频 → 电长度偏短，优先动控制谐振的尺寸。
- 最低点频点 **低于** 目标频 → 电长度偏长。
- 频点已靠近目标但目标频 S11 仍差 → 动馈电/匹配类变量，不要再整体缩放。
- 标量几乎不动 → 换一组变量，不要加大同方向步进。

若本轮有 `.s1p`，先画图再下结论：

```bash
uv run python skills/tune-hfss-antenna/scripts/plot_s11.py path/to.s1p --mark-ghz 60 --out hfss-tuning-artifacts/round-00N/s11.svg
```

在 hfss-mcp 仓库根执行。全局入口与本文件同内容：`~/.agents/skills/tune-hfss-antenna/`。

对比两轮时加 `--overlay path/to/previous.s1p`。MCP 若设置了 `HFSS_MCP_TOUCHSTONE_KEEP_DIR`，用目录里最新的 `sparams_*.s1p`。

## Artifacts

工作目录（打开的 hfss-mcp 仓库根）：

- `hfss-tuning-log.md` — 会话头 + 每轮：假设、动了哪个量、指标、结论。
- `hfss-tuning-artifacts/round-00N/` — 图和摘录。

## Demo case

`benchmark/cases/siw_feed_l1/`：沙箱馈电失配，白名单 `fl fw fx fy t1`，Setup1 / Sweep，目标 60 GHz，预算 6 trial。阈值见 `case.json`（不要读 `answer/`，那是评分答案册）。
