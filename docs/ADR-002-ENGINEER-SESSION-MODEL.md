# ADR-002: Engineer session model

- Status: Accepted
- Date: 2026-08-13
- Supersedes: `ADR-001-AUTONOMY-EXECUTION-MODEL.md` (partial; remaining clauses listed there)
- Scope: The default Host-Agent path for AI-assisted HFSS antenna tuning
- Code status: **Target design.** Shipped MCP (2026-07-29) still implements ADR-001 / `ARCHITECTURE_V0.md`. Do not read V0 docs as this decision.

## Context

V0 proved a constrained closed loop on AEDT 2023 R2: workspace copy, exclusive worker Desktop, `trial_*` (apply + solve + three S11 scalars), SQLite jobs, checkpoint. That is a valid unattended optimizer harness. It is the wrong default for a human sitting at an already-open HFSS.

The product thesis: models are already capable; the work is a **toolchain + a Skill that encodes a human engineer's workflow**. The agent should think like an engineer at an open AEDT, not like an optimizer sampler.

2023–2025 "LLM-as-optimizer" surveys (OPRO / LLAMBO and similar) do not govern this project. That survey is archived at `docs/archive/LLM-TUNING-RESEARCH.md`.

## Decision

The **main path** is: attach the user's already-open AEDT session. The Host Agent hypothesizes, changes one or two related allowlisted variables, solves once, inspects the plot the hypothesis needs, compares, then replans or stops.

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
| Expensive | `Analyze` / solve | Async job: start / status / result / cancel. Do it once per hypothesis. |
| Cheap | Create or export a report against an existing solution | Sync or short job. Many queries per solve are expected. |
| Cheap | Apply 1–2 variables, read-back, snapshot | Sync. No solve implied. |

The agent decides *which* plot the current hypothesis needs. The server does not decide "the metric is S11@target".

### 4. Reports: HFSS report-type surface, few tools

HFSS already has a finite set of report types (Modal S Parameter, Terminal Z, far-field 2D cuts, fields on a face, …). Custom expression is **one** quantity type inside that set, not an unbounded exec channel.

- The agent **may create** reports, not only export ones the user already made.
- The MCP surface stays **small**: a handful of typed tools (`report_types`, `report_create`, `report_export`, …), not one tool per quantity.
- The catalog of report types, quantity names, and typical setups lives in the **Skill**, loaded by progressive disclosure. Do not flood the MCP tool list.

### 5. Artifacts: curves vs fields

- **Curves** (S11, Z, 2D pattern cuts, and similar 1-D / 2-D traces): export **CSV** so the agent can plot, compare, and argue numerically.
- **Fields / surface current**: do **not** dump a whole-field CSV. Export a **visual** (color plot / image) on a **specified face + frequency**.
- Touchstone remains a valid network-data export; it is not the only result channel.

### 6. Save: agent decides, no autosave

- The server never autosaves.
- Default habit (encode in the Skill; user may override with "just save"):
  - After **clear progress only**, `Save As`, version **+1**, then continue on the new file.
  - Do not overwrite the file the user opened, unless the user explicitly says so.
- Checkpoint/restore of a run workspace remains valid for unattended mode. It is not a substitute for this Save As habit on the live project.

### 7. Skill owns the human loop

The Skill teaches:

1. Hypothesize from the current plot (why is the min off the target? which dimension?).
2. Change **one or two related** allowlisted variables — not a full vector shotgun.
3. Solve once.
4. Inspect **whatever report the hypothesis needs** (not a fixed S11 triple).
5. Compare to the previous curve / image.
6. Replan, or stop and tell the user.

The Skill must not tell the agent to call `run_start` / seeded random search. Server-side multi-trial random search is an unattended leftover, not the interactive path.

### 8. Still forbidden (from ADR-001)

- Arbitrary Python, VBScript, generic object traversal, `exec`.
- Forking or wrapping `ansys/pyaedt-mcp` as the product runtime.
- Geometry / material / port mutation from the agent (until a later ADR).

## Consequences

- Next code milestone (V1) must split `trial_*`, add report create/export (CSV vs image), make live attach the default, and add explicit Save / Save As. Until then, V0 tools and the current Skill remain the runnable surface.
- README, `ARCHITECTURE_V0.md`, and `STATUS.md` describe **what shipped**, not this decision.
- Benchmark `siw_feed_l1` stays the demo case; the demo is a Host Agent session, not a scripted optimizer probe.
- Adding a report type is a Skill catalog + allowlist change, not a new MCP tool per quantity.
