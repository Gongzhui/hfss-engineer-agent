# Implementation status (v0 real AEDT)

Last updated: 2026-07-21

## Done (code-enforced + verified)

- [x] Production adapter selection: `HFSS_MCP_ADAPTER=pyaedt|fake`; Windows + AEDT install defaults to **pyaedt**
- [x] `health` reports `adapter`, `real_hfss_ready`, `connection_mode`, AEDT version; fake never claims real HFSS ready
- [x] Worker-process exclusive AEDT sessions (`connection_mode=worker_process_exclusive_desktop`); MCP tools return durable job IDs without blocking on solves
- [x] Real solve via `odesign.Analyze` + durable start/status/result/cancel
- [x] Real S11 metrics from Touchstone (`Solutions.ExportNetworkData`) — min in band, min frequency, at target frequency
- [x] Structured MetricSpec (no arbitrary Python expressions)
- [x] Safe workspace copies; original `.aedt` never mutated; original SHA-256 verified
- [x] Per-trial checkpoints; restore restricted to run workspace; failure attempts checkpoint restore
- [x] Project/design identity checks (both `project_name` and `design_name`)
- [x] Idempotency with payload hash → `idempotency_conflict` on key reuse with different body
- [x] Per-project locks; atomic job claim; SQLite durability; restart marks leftover running as interrupted
- [x] Multi-trial run orchestrator: `run_start/status/result/cancel/resume` with seeded random search; enforces max_trials / max_runtime / metric_targets / serial concurrency
- [x] Offline tests (FakeAdapter) + **real AEDT 2023 R2 e2e** (`pytest -m real_aedt`)

## Known limits (honest)

1. **Cancel**: terminates only worker-owned AEDT PIDs (not user desktops). In-solve graceful AEDT interrupt remains best-effort.
2. **PyAEDT 1.3 quirks on 2023.2**: `post.get_solution_data` / `osolution` can be broken for Modal Network; v0 uses native `GetModule("Solutions").ExportNetworkData` instead.
3. **Interrupted jobs** are marked, not auto-replayed; `run_resume` continues multi-trial runs without redoing completed trials.
4. **Optimizer** is seeded random only (interface ready for Bayesian/AI later).
5. Smoke geometry is a minimal modal network fixture for CI-speed solves, not a production antenna.

## Real AEDT acceptance (this machine)

Command:

```powershell
uv run pytest -m real_aedt -v
```

Result on 2026-07-21: **PASSED** (~44–50s including Desktop start).

Evidence sample (see also scratch `real_aedt_evidence.json`):

| Field | Example |
|---|---|
| adapter | `pyaedt` |
| real_hfss_ready | true |
| job_id | `job_04fd3f2061634c21bd2317cb1e8a4d01` |
| run_id | `run_real` |
| metrics | S11_min_dB, S11_min_freq_GHz, S11_at_target_dB from Touchstone |
| original hash | verified unchanged |

## How to run

```powershell
# Production MCP (defaults to pyaedt when AEDT installed)
uv run hfss-mcp

# Force fake demo
$env:HFSS_MCP_ADAPTER = "fake"
$env:HFSS_MCP_DEMO = "1"
uv run hfss-mcp

# Tests
uv run pytest
uv run pytest -m real_aedt
uv run ruff check .
uv run mypy
```

Data directory: `HFSS_MCP_DATA_DIR` (default `~/.hfss-mcp`).
