---
name: tune-hfss-antenna
description: Tune allowlisted parameters on an existing HFSS/AEDT antenna via the hfss-mcp MCP server. Diagnose from S11 and the 3D view, change one hypothesis per solve, Save As only after clear progress. Use when the user wants to recover matching, tune S11, or run the siw_feed_l1 sandbox. Do not use to build geometry from scratch.
---

# Tune HFSS antenna

Host Agent 当工程师，挂用户**已经打开**的 AEDT：看图、下假设、改 1–2 个相关变量、求解一次、再看。不要当优化器采样器。

## Hard rules

- 只调 allowlist 里的变量；禁改几何、材料、端口、setup。
- `variables_set` 是**部分更新**（只传要改的量）。不要求解、不要保存。
- **禁止**调用不存在的 `trial_*` / `run_*`。
- 求解失败 = 记下该区域、换假设。不要同一点重试。
- 不自动保存。有明显进展才 `project_save(mode="save_as", path=新版本)`，默认不覆盖用户打开的那份。用户说「直接保存」才 `mode="save"`。
- 推理写在 `hfss-tuning-log.md`。

## Tools

`health` → `session_list` → `allowlist_load` → `snapshot` → `variable_map` → `view_capture` →（改参）`variables_set` → `analyze_start` / `analyze_status` → `report_create` + `report_export`。

白名单文件：`examples/golden_manifest.json` 或 `benchmark/cases/siw_feed_l1/case.json`（或同等瘦 JSON）。

轮询 Analyze：15–30s，直到 `completed` / `failed`。不要并行求解。

## Loop

1. `health`：`real_hfss_ready` 为 true，且 `session_list` 能看见当前 Desktop。否则让用户先打开 AEDT 和工程。
2. `allowlist_load`。
3. `snapshot` 看变量和 setup。不熟的工程先 `variable_map` + `view_capture`（需要时 `isolate` 相关物体）。
4. 写一条假设。只改与假设相关的 1 个变量（最多 2 个强耦合）。
5. `variables_set` → 需要时再 `view_capture` → `analyze_start` → 等完成。
6. `report_create` + `report_export`：
   - `modal_s` → S11 CSV（`freq_ghz,s11_db`）
   - `terminal_z` → Z CSV（`freq_ghz,re,im`）
   - `farfield_2d` → 2D 方向图 CSV（需要工程里已有 infinite sphere，且求解保存了辐射场）
   - `field_face` → 指定物体/面 + 频点的场/电流图（`face` 与 `frequency` 必填）
   有 `.s1p`/CSV 就画图。
7. 证实或推翻假设，追加日志。达标、预算用尽、或连续两轮无进展则停。

## Diagnose

看 S11 曲线，不要只看三个标量：

- 最低点频点 **高于** 目标 → 电长度偏短。
- 最低点频点 **低于** 目标 → 电长度偏长。
- 频点已靠近但目标频 S11 仍差 → 动馈电/匹配，不要整体缩放。

```bash
uv run python skills/tune-hfss-antenna/scripts/plot_s11.py path/to.s1p --mark-ghz 60 --out hfss-tuning-artifacts/round-00N/s11.svg
```

CSV（`freq_ghz,s11_db`）同样可用。对比两轮加 `--overlay`。

## Demo case

`benchmark/cases/siw_feed_l1/`：白名单 `fl fw fx fy t1`，Setup1 / Sweep，目标 60 GHz。阈值见 `case.json`。不要读 `answer/`。
