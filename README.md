# HFSS MCP

Constrained MCP bridge for AI-assisted HFSS antenna tuning on **Ansys Electronics Desktop**. Arbitrary script execution is **not** exposed.

**Live design:** `docs/ADR-002-ENGINEER-SESSION-MODEL.md` — attach the user's already-open AEDT; Host Agent thinks like an engineer (hypothesize → 1–2 variables → solve once → inspect the plot the hypothesis needs); curves as CSV, fields as images; no autosave. **Not implemented in code yet.**

**Shipped code (v0, 2026-07-29):** workspace copy → allowlisted apply → exclusive worker Desktop → bundled `trial_*` (solve + Touchstone S11 scalars) → SQLite jobs → checkpoint. See `docs/ARCHITECTURE_V0.md` and `docs/STATUS.md`. V0 decision record (superseded): `docs/ADR-001-AUTONOMY-EXECUTION-MODEL.md`.

## Documents

| File | Role |
|---|---|
| `docs/ADR-002-ENGINEER-SESSION-MODEL.md` | Current constitution |
| `docs/ADR-001-AUTONOMY-EXECUTION-MODEL.md` | Superseded V0 decision (kept) |
| `docs/ARCHITECTURE_V0.md` / `docs/STATUS.md` | What the running package actually does |
| `docs/COMMUNITY_HFSS_MCP_REVIEW.md` | 2026-07-20 review of public HFSS MCPs |
| `docs/MIGRATION_FROM_HFSS_CLI.md` | Relation to frozen `hfss-cli` |
| `SOURCE_SNAPSHOTS.md` | Pinned third-party clones |
| `docs/archive/LLM-TUNING-RESEARCH.md` | Archived 2023–25 LLM-as-optimizer survey; does not govern V1 |

## Production start (this machine)

```powershell
cd C:\Users\Gongzhui\Documents\Projects\hfss-mcp
uv sync
# Optional overrides:
# $env:HFSS_MCP_ADAPTER = "pyaedt"   # default when AEDT is installed
# $env:HFSS_MCP_DATA_DIR = "D:\hfss-mcp-data"
# $env:HFSS_MCP_AEDT_VERSION = "2023.2"
uv run hfss-mcp
```

`health` must report:

- `adapter`: `pyaedt`
- `real_hfss_ready`: `true` when `ansysedt.exe` is present
- `connection_mode`: `ensure_graphical_gui_session` in auto session mode (GUI attach serves snapshot/setup tools; trials still run in exclusive worker Desktops — see Safety model)

## Demo: one-command real closed loop

Requires AEDT 2023 R2 (`C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe`) and `uv sync`.

```powershell
uv run python examples/build_golden.py   # builds examples/golden_patch.aedt + golden_manifest.json
uv run python examples/run_demo.py       # the live demo (several minutes, 6 real solves)
```

`run_demo.py` spawns the MCP server as a stdio subprocess and drives the whole loop through MCP tools only. It prints the golden project SHA-256 before/after, runs 6 whitelist trials on the `gap` variable (each solved in an exclusive worker Desktop on a workspace copy), re-parses the persisted Touchstone exports into a trial/S11 table, and writes `examples/demo_output/results.json`. Exit code 0 requires all of: best S11 beats the baseline, golden hash unchanged, and no leftover `ansysedt.exe`.

Fake mode (tests/demo only):

```powershell
$env:HFSS_MCP_ADAPTER = "fake"
$env:HFSS_MCP_DEMO = "1"
uv run hfss-mcp
```

### Minimal MCP client config (stdio)

```json
{
  "mcpServers": {
    "hfss-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Users\\Gongzhui\\Documents\\Projects\\hfss-mcp", "hfss-mcp"],
      "env": {
        "HFSS_MCP_ADAPTER": "pyaedt",
        "HFSS_MCP_AEDT_VERSION": "2023.2"
      }
    }
  }
}
```

## MCP tools

| Tool | Kind | Notes |
|---|---|---|
| `health` | read | Adapter + real readiness (honest) |
| `environment_status` | read | Install discovery, no launch |
| `session_list` | read | Running AEDT sessions + open projects |
| `manifest_validate` | read | Schema 1.1 + structured metrics; persists for workers |
| `design_snapshot` | attach | Variables, setups, revision; identity-checked |
| `setup_schema` | read | Setup/sweep types + property aliases |
| `setup_list` | read | Setups with full property bag |
| `setup_get` | read | One setup by name |
| `setup_create` | mutate | New setup (+ optional sweeps) |
| `setup_update` | mutate | Any native property key; optional rename |
| `setup_delete` | mutate | Remove setup |
| `setup_sweep_create` | mutate | Add frequency sweep |
| `setup_sweep_update` | mutate | Edit sweep properties |
| `setup_sweep_delete` | mutate | Remove sweep |
| `trial_start` | enqueue | Returns job_id quickly; worker runs AEDT |
| `trial_status` | job control | Poll durable job state |
| `trial_result` | job control | Metrics + checkpoint + apply diff |
| `trial_cancel` | job control | Kills only worker-owned AEDT PIDs |
| `checkpoint_list` | recovery | Per-run checkpoint records |
| `checkpoint_restore` | recovery | Restore only inside run workspace |
| `run_start` | multi-trial | Seeded random search over whitelist |
| `run_status` | multi-trial | Run-level progress |
| `run_result` | multi-trial | Best-so-far and trial history |
| `run_cancel` | multi-trial | Stop scheduling, cancel active trial |
| `run_resume` | multi-trial | Continue without redoing finished trials |

25 tools, all narrow and typed.

**Not registered:** `run_python_code`, `run_python_script`, `exec`, generic invoke.

## Manifest (schema 1.1)

- Absolute `.aedt` / `.aedtz` path, project/design identity
- Complete parameter allowlist (unit, min, max)
- Structured metrics, e.g. `s11_min_in_band`, `s11_at_freq`, `s11_min_freq`
- Stop conditions: `max_trials`, `max_runtime_seconds`, `metric_targets`
- Concurrency (serial default) and checkpoint policy

Candidates must be **full parameter vectors**. Idempotency keys store a **payload hash**; same key + different body → `idempotency_conflict`.

## Safety model

v0 (current code):

- User original projects are **copied** into a run workspace; originals are never written.
- Each real trial runs in a **worker process** with its own Desktop (`new_desktop=True`), solving the workspace copy.
- Mutating the *live* GUI project is opt-in only (`HFSS_MCP_ATTACH_LIVE=1`); it rewrites the original `.aedt` and is meant for interactive sessions, not automation.
- Only worker-owned `ansysedt` PIDs are killed on cancel.
- Policy rejections happen in code before mutation.

ADR-002 target: live attach is the **default** interactive path; no autosave; Save / Save As is the agent's decision (prefer Save As, version +1, after clear progress). Unattended worker copies remain a separate mode.

## Development / tests

```powershell
uv run pytest                 # offline + real_aedt if AEDT present
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt    # requires AEDT 2023 R2
uv run ruff check .
uv run mypy
```

## Agent Skill

Procedural tuning knowledge lives in `skills/tune-hfss-antenna/` (not inside the Python package). On this machine it is linked from `~/.agents/skills/tune-hfss-antenna` so Cursor and other hosts can discover it without a `.cursor/` folder in the repo.

The current Skill is **V0-shaped** (trial loop, `siw_feed_l1`). Rewrite it to the ADR-002 engineer loop after the MCP tools change.

## Package layout

```
src/hfss_mcp/          # MCP server
skills/tune-hfss-antenna/   # Host Agent skill + plot script
benchmark/             # leak-free cases and eval runner
```
