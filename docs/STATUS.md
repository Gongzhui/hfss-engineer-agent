# Implementation status (V1 live COM attach)

Last updated: 2026-08-19

Live constitution: `ADR-002-ENGINEER-SESSION-MODEL.md`.
V0 decision (superseded, keep clauses): `ADR-001-AUTONOMY-EXECUTION-MODEL.md`.
V0 architecture snapshot (not the running MCP): `ARCHITECTURE_V0.md`.

## Done (code-enforced + verified this machine)

- [x] Live attach via COM ROT / `Dispatch` + `oDesktop.RunScript`. **Does not** construct PyAEDT `Desktop()` / `Hfss()`.
- [x] Will not launch a second AEDT; will not quit the user's Desktop on MCP/`AppContext.close()`.
- [x] 20 MCP tools. **Not registered:** `trial_*`, `run_*`, setup CRUD, checkpoint, `exec`, Optimetrics Optimization / Sensitivity / Statistical / DOE.
- [x] Slim allowlist. `variables_set` is a partial update; no solve; no save. Accepts `name` or `variable`. Returns `needs_solve`.
- [x] `snapshot` is cheap JSON. `view_capture` and `variable_map` are on-demand.
- [x] Reports: `report_list` = Results + Field Overlays; `report_create` adds a visible HFSS plot (`parametric=` Alls that matrix; omitted/`families=[]` pins other parametric vars at Nominal). Reusing a name to apply families/pins returns `report_exists`. `field_face` quantity is a finite set (`Mag_E` default, `Mag_Jsurf`). `report_export` = `ExportToFile` (3rd arg False = GUI Export Data, Separate Columns off: one column per swept variable) / `ExportFieldPlot`, then `freq_ghz,variation,s11_db` with those combinations as `variation`. `traces`/`labeled`/`csv_format`; `stale_solution` if unsaved `variables_set`. No Touchstone bypass, no hidden `hfss_mcp_*` plots.
- [x] Optimetrics Parametric: `optimetrics_list` / `parametric_create` / `parametric_start` / `parametric_export_table`. Real `OptiParametric` node; `parametric_start` is **SolveSetup**, not `oDesign.Analyze`. Same name **edits** the node. Cap **256** points. `analyze_status` returns Message Manager lines.
- [x] V0 optimizer package removed (`jobs/`, checkpoint, workspace, `run_optimizer`, `adapter/pyaedt_adapter.py`).
- [x] Skill `skills/tune-hfss-antenna/` matches the V1 loop: joint Optimetrics Parametric whose grouping/density the agent must justify; not OFAT `variables_set` + Analyze; no baked default N. After changing parameters, look at the model (`view_capture`); do not keep an obviously broken geometry. Visual check is a habit, not a new MCP primitive or a fixed view checklist.
- [x] Offline FakeAdapter tests + **real AEDT 2023 R2** live attach.
- [x] `cases/` tree: `uwb_circular_notch` nominal is ported and solved; sandbox is Save As + 9-param detune including `lw`. Do not rebuild with `build.py` (wipes the port).
- [x] Exam pack `eval/exams/uwb_circular_notch/`: isolated Cursor workspace, log-only agent output, hidden `eval/score_run.py` + `eval/keys/`. Finished runs live in `eval/archive/` (outside the exam folder). Spec is 6.6 GHz stopband (no frequency slack), width ≤ 0.5 GHz, envelope rel BW ≥ 130%. Solve-time budget 3 hours (sum of log `solve_time`; thinking/export do not count); `protocol.on_time` is separate from RF pass. Inner loop is joint matrices, not a fixed round count.

## Known limits (honest)

1. **Far-field / field plots need solved data.** `farfield_2d` needs an infinite sphere and saved radiation fields. `field_face` needs a field solution at that frequency. Interpolating sweeps often have no stored fields — export then fails; the Skill says to fall back to the family of curves. The tools do not auto-solve and they do not invent a plot.
2. **No plot in the tree → no data.** Curves must exist under Results; field images must exist under Field Overlays. Same as a human. Create first.
3. **Analyze cancel** is best-effort. It will not kill the user's `ansysedt.exe`.
4. **Do not treat `.aedt.lock` ListenPort as gRPC.** User-style `ansysedt.exe` is COM.
5. **On this machine** tests need a redirected temp dir (`TMP/TEMP/TMPDIR` → repo-local, e.g. `.tmp_pytest`); delete `.tmp_pytest/gen_py` before `ruff check .` if pywin32 wrote a cache there.
6. **Parametric Analyze is a full sweep.** Creating the Optimetrics node is cheap; `parametric_start` is not. Do not smoke-test it on a long UWB solve. `parametric_export_table` works before the sweep has results.
7. **256-point cap is a safety rail, not a recommended grid.** Four coupled variables can joint-sweep; a 10-way factorial cannot. If the physically right grid is larger, split or coarsen and say so in the log.
8. **Family curves need a new Results plot.** `parametric_export_table` is the combination table. After a sweep, `report_create(..., parametric=<name>)` then `report_export`. Reusing the pre-sweep single-trace `S11` is still one curve, and reusing that name to apply families/pins fails (`report_exists`). Omitting `families` after later rounds does **not** All every Parametric setup; other swept vars are pinned at Nominal. `families=[]` is the explicit pin. `report_export` is the same table as GUI Export Data with Separate Columns unchecked; `variation` is the parameter combination. All mixing historical values of the same knobs is expected.
9. **Progress is Message Manager text, not the GUI progress bar.** `analyze_status` returns recent HFSS messages. There is no pixel scrape of "Show Progress". Engine-died lines (no setup name) are treated as parametric job failure.
10. **Do not parallelize HFSS MCP tools.** AEDT COM/`RunScript` is not reentrant. Concurrent `snapshot` + `health`/`report_list` hangs at `SetActiveProject`. The server serializes RunScript and project listing; Host Agents must still call those tools one at a time. `analyze_status` during a solve is the exception.
11. **`variables_set` does not refresh Results.** The CSV after a pin is the last solved variation until Analyze (or a family export that already contains that point). `report_export` flags this with `stale_solution`.
12. **Finished exam runs must leave the exam folder.** `eval/exams/<id>/runs/` is visible to the Host Agent. After scoring, move the timestamp directory to `eval/archive/`. A written "do not read old runs" rule is not isolation.
13. **`view_capture` is one orientation per call.** Default is isometric. After `variables_set`, look at the model; extra angles (including 3D) catch CAD errors that S11 will not. Allowlist boxes are independent; coupled CAD constraints are not expressed in the MCP. This is the agent's eyes, not a solver flag.

## Not started (deferred)

- Unattended N-run exam harness: proctor resets sandbox, launches one isolated Host Agent per run, scores, archives, repeats. Stall nudge only when HFSS is idle and the candidate has been silent 20 minutes. Cursor SDK local adapter only for now; do not `force` a run unless Stop is actually required. Spec: `docs/FUTURE-UNATTENDED-EXAM.md`. Do not implement until asked.

## Real AEDT acceptance (this machine, 2026-08-13)

```powershell
$env:TMP = "$PWD\.tmp_pytest"; $env:TEMP = $env:TMP; $env:TMPDIR = $env:TMP
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt -v
```

Live attach: COM attach to existing PID, snapshot, `variables_set` on `gap`, `view_capture`, `variable_map`; Desktop still alive after `ctx.close()`; golden SHA-256 unchanged.

## How to run

```powershell
uv run hfss-mcp

$env:TMP = "$PWD\.tmp_pytest"; $env:TEMP = $env:TMP; $env:TMPDIR = $env:TMP
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt
uv run ruff check src/hfss_mcp tests
uv run mypy
```

Data directory: `HFSS_MCP_DATA_DIR` (default `~/.hfss-mcp`).
