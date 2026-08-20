# ADR-002: Engineer session model

- Status: Accepted
- Date: 2026-08-13
- Supersedes: `ADR-001-AUTONOMY-EXECUTION-MODEL.md` (partial; remaining clauses listed there)
- Scope: The default Host-Agent path for AI-assisted HFSS antenna tuning
- Code status: **Implemented (interactive path, 2026-08-13).** Live COM attach, split Analyze vs reports, Optimetrics Parametric (HFSS tree), `view_capture` / `variable_map`, explicit Save / Save As. V0 optimizer tools are not registered. See `docs/STATUS.md`.

## Context

V0 proved a constrained closed loop on AEDT 2023 R2: workspace copy, exclusive worker Desktop, `trial_*` (apply + solve + three S11 scalars), SQLite jobs, checkpoint. That is a valid unattended optimizer harness. It is the wrong default for a human sitting at an already-open HFSS.

The product thesis: models are already capable; the work is a **toolchain + a Skill that encodes a human engineer's workflow**. The agent should think like an engineer at an open AEDT, not like an optimizer sampler.

2023–2025 "LLM-as-optimizer" surveys (OPRO / LLAMBO and similar) do not govern this project. That survey is archived at `docs/archive/LLM-TUNING-RESEARCH.md`.

## Decision

The **main path** is: attach the user's already-open AEDT session. The Host Agent judges which allowlisted knobs are **coupled for this structure this round**, runs HFSS **Optimetrics Parametric** as a joint matrix, reads the family of curves, freezes what does not move, and repeats (new group, or same group finer). Grouping and sample density are not constants. It does not jump one variable to a new value and Analyze once. It does not call genetic / particle-swarm Optimization.

The exclusive-worker + workspace-copy + bundled-`trial` path remains a possible **unattended** mode. It is not the interactive constitution.

### 1. Session

- Default: attach the Desktop the user already has open. Do not spawn a second exclusive worker Desktop for interactive tuning.
- The agent operates on the live project the user is looking at.
- Unattended worker copies may still exist for overnight / batch jobs; they are a separate mode, not the Skill's default.

### 2. Tune-only (unchanged)

- The agent does not create or edit geometry, materials, or ports.
- Only allowlisted design variables may change, with unit and range checks.
- Setup/sweep CRUD already in V0 may stay; it is not the tuning inner loop.

### 3. Split expensive from cheap

Do **not** bundle apply + `Analyze` + S11 scalars into one `trial`.

| Kind | Examples | Contract |
|---|---|---|
| Expensive | Optimetrics Parametric matrix, or a single Analyze after pinning a point | Async job. The inner-loop unit is **one matrix**, not one `variables_set`. |
| Cheap | Create or export a report against an existing solution | Sync or short job. Many queries per matrix are expected. |
| Cheap | Pin the chosen matrix row (`variables_set`), snapshot | Sync. No solve implied. |

The agent decides *which* plot the current question needs (S11 / Smith / phase). The server does not decide "the metric is S11@target". "Do it once per hypothesis" means once per **sweep setup**, not once per scalar guess.

### 4. Reports: HFSS report-type surface, few tools

HFSS already has a finite set of report types (Modal S Parameter, Terminal Z, far-field 2D cuts, fields on a face, …). Custom expression is **one** quantity type inside that set, not an unbounded exec channel.

- The agent **may create** reports, not only export ones the user already made.
- The MCP surface stays **small**: a handful of typed tools (`report_types`, `report_create`, `report_export`, …), not one tool per quantity.
- The catalog of report types, quantity names, and typical setups lives in the **Skill**, loaded by progressive disclosure. Do not flood the MCP tool list.

### 5. Artifacts: curves vs fields

- **Curves** (S11, Z, 2D pattern cuts, and similar 1-D / 2-D traces): export **CSV** from the report that exists under **Results**. If the plot is not in Results, the agent cannot see it — same as a human. `report_create` adds a real HFSS report; `report_export` is `ExportToFile` on that name (GUI Export Data; Separate Columns off so each swept variable has its own column).
- **Fields / surface current**: do **not** dump a whole-field CSV. Export a **visual** (color plot / image) on a **specified face + frequency**. `quantity` is a finite set (`Mag_E`, `Mag_Jsurf`). The overlay must remain visible in the GUI.
- Touchstone / `ExportNetworkData` is **not** an agent-visible S11 channel. It can disagree with Modal `dB(S(1,1))` on a wave port.

### 6. Save: agent decides, no autosave

- The server never autosaves.
- Default habit (encode in the Skill; user may override with "just save"):
  - After **clear progress only**, `Save As`, version **+1**, then continue on the new file.
  - Do not overwrite the file the user opened, unless the user explicitly says so.
- Checkpoint/restore of a run workspace remains valid for unattended mode. It is not a substitute for this Save As habit on the live project.

### 7. Skill owns the human loop

The Skill teaches the **generic** procedure (matching antennas and 2-bit phase units share it; only the observable changes):

1. Name the question (impedance bandwidth / stopband, or reflection-phase spacing).
2. Decide which knobs are coupled **for this structure this round**. Split a large coupled set into physically meaningful groups; do not OFAT; do not dump the whole allowlist into one grid.
3. Decide sample density from what this round needs to show (wide/sparse when the range is unknown; tighter when it is not).
4. Run HFSS **Optimetrics Parametric**. Write the grouping and density **before** `parametric_create`. A rationale that would paste onto a different antenna is not a rationale.
5. Read the **family of curves**: which knob moves the observable, which can be frozen.
6. Next round: new group, or same group finer. If the last round showed a trade-off, put those knobs in one joint matrix (or try an intermediate value). Stop when the named question is met; an exam may also stop when another sweep would exceed its solve budget. Do not stop because coupled groups "feel done" or two rounds looked flat. Pin a point with `variables_set` only after the matrix says so. After any parameter write, look at the live model (`view_capture`). Geometry with an obvious CAD error is not a keepable point. How many views is judgment, not a checklist.

The Skill must **not** bake a default N or default samples-per-axis. Suggested numbers make the agent copy them instead of judging. Worked counts belong only as labeled illustrations, not as the procedure. "Not an optimizer sampler" forbids genetic / PSO **and** one-factor-at-a-time value jumps. It does **not** forbid a human-scale Parametric matrix, and it does not prescribe the grid.

### 8. Optimetrics: native Parametric only

Sweeps a human would run under **Optimetrics → Parametric**. Same WYSIWYG rule as reports: the node must appear in the Optimetrics tree; the agent does not run a hidden sampler of `variables_set` + Analyze.

- Allowed now: `optimetrics_types`, `optimetrics_list`, `parametric_create`, `parametric_start`, `parametric_export_table`.
- `parametric_create` is real `InsertSetup('OptiParametric')` on first use and `EditSetup` if the name already exists. Never delete the user's setups.
- `parametric_start` is `Optimetrics.SolveSetup(name)` as an async job. It is **not** `oDesign.Analyze` — that looks in Analysis Setup and reports "Solution was not found". `ok: true` on start means accepted; poll `analyze_status` until `done`. `analyze_status` returns Message Manager lines (what a human sees) as `messages` / `progress`.
- Sweeps only on allowlisted variables. **Current cap is 256 points** — a safety rail against dumping the whole allowlist (e.g. \(2^{10}\)), not a recommended grid. A 4-variable joint sweep can fit; a 10-way factorial cannot. If the physically right grid is larger, split or coarsen and say so in the log.
- After a parametric solve, the family of curves must be a **Results** plot the human can see. `report_create(..., parametric=<setup>)` (or `families=[...]`) puts those variables to All on a **new** report. `parametric_export_table` is the combination table, not Modal S11. Reusing the pre-sweep single-trace `S11` does not magically grow a family.
- Same-name `parametric_create` **edits** that Optimetrics node (`EditSetup`). It never deletes.
- Not registered: OptiOptimization, Sensitivity, Statistical, DOE, DesignXplorer.

### 9. Still forbidden (from ADR-001)

- Arbitrary Python, VBScript, generic object traversal, `exec`.
- Forking or wrapping `ansys/pyaedt-mcp` as the product runtime.
- Geometry / material / port mutation from the agent (until a later ADR).

## Consequences

- V1 MCP surface is the 20 engineer-session tools in `STATUS.md`. `trial_*` / `run_*` / setup CRUD / Optimetrics Optimization are not registered.
- `modal_s` / `terminal_z` / `farfield_2d` are real ReportSetup objects under Results. `field_face` is a real Field Overlays plot. `report_list` is `GetAllReportNames` plus `GetFieldPlotNames`. `report_export` is `ExportToFile` / `ExportFieldPlot`. There is no `ExportNetworkData` bypass and no modeler-screenshot fallback for fields. Missing plot → `report_not_in_results`.
- V0 optimizer modules (`jobs/`, checkpoint, `run_optimizer`, PyAEDT worker adapter) are removed from the package.
- Benchmark `siw_feed_l1` stays the demo case; live exams are the folders under `eval/exams/` (Cursor opens one exam directory, not the repo root).
- Adding a report type is a Skill catalog + allowlist change, not a new MCP tool per quantity.
- Parametric setups are real Optimetrics tree nodes (`InsertSetup` / `EditSetup`). Missing node → `report_not_in_results`. The Optimetrics table is not a substitute for Modal S11. Family curves are a Results plot created with `parametric=` / `families=`.
- One-factor-at-a-time `variables_set` + Analyze is not the Skill inner loop. Genetic / PSO Optimization stays unregistered.
