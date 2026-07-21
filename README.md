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
- `connection_mode`: `worker_process_exclusive_desktop`

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
| `manifest_validate` | read | Schema 1.1 + structured metrics; persists for workers |
| `design_snapshot` | open workspace copy | Checks project_name + design_name |
| `trial_start` | enqueue | Returns job_id quickly; worker runs AEDT |
| `trial_status` / `trial_result` / `trial_cancel` | job control | Durable SQLite |
| `checkpoint_list` / `checkpoint_restore` | recovery | Restore only inside run workspace |
| `run_start` / `run_status` / `run_result` / `run_cancel` / `run_resume` | multi-trial | Seeded random search; enforces budgets |

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
- Each real trial runs in a **worker process** with its own Desktop (`new_desktop=True`).
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
