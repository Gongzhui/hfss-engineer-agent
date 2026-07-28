# HFSS MCP

Constrained MCP bridge for AI-assisted HFSS antenna tuning on **Ansys Electronics Desktop**.

v0 delivers a **real closed loop** on AEDT 2023 R2: workspace copy → allowlisted parameter apply with read-back → exclusive worker Desktop → solve → Touchstone S11 metrics → durable SQLite jobs → checkpoint / recovery. Arbitrary script execution is **not** exposed.

Architecture: `docs/ADR-001-AUTONOMY-EXECUTION-MODEL.md`, `docs/ARCHITECTURE_V0.md`, `docs/STATUS.md`.

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

- User original projects are **copied** into a run workspace; originals are never written.
- Each real trial runs in a **worker process** with its own Desktop (`new_desktop=True`), solving the workspace copy.
- Mutating the *live* GUI project is opt-in only (`HFSS_MCP_ATTACH_LIVE=1`); it rewrites the original `.aedt` and is meant for interactive sessions, not automation.
- Only worker-owned `ansysedt` PIDs are killed on cancel.
- Policy rejections happen in code before mutation.

## Development / tests

```powershell
uv run pytest                 # offline + real_aedt if AEDT present
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt    # requires AEDT 2023 R2
uv run ruff check .
uv run mypy
```

## Package layout

```
src/hfss_mcp/
  server.py app.py config.py
  manifest.py policy.py metrics_spec.py metrics.py
  workspace.py checkpoint.py real_project.py
  adapter/   # Protocol, Fake, PyAEDT
  jobs/      # SQLite store, supervisor, worker, trial_exec
  run_optimizer.py
```
