# Implementation status (v0 real AEDT)

> **Historical snapshot of the code shipped 2026-07-29.** The checklist below is what the current Python package actually does.
>
> Live design: `ADR-002-ENGINEER-SESSION-MODEL.md` (not implemented in code yet).
> V0 decision record (superseded): `ADR-001-AUTONOMY-EXECUTION-MODEL.md`.
>
> Known V0/V1 gaps vs ADR-002: bundled `trial_*` (apply+solve+S11); no report create/export tools; live GUI attach is opt-in (`HFSS_MCP_ATTACH_LIVE=1`) and saves the original; no agent-controlled Save / Save As; `run_*` seeded random is registered (Skill already forbids it).

Last updated: 2026-07-29 (banner added 2026-08-13; body not rewritten)

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
- [x] One-command demo (`examples/run_demo.py`): stdio MCP client → 6 whitelist trials → Touchstone-backed S11 table → `results.json`; golden project hash verified unchanged; self-cleans spawned AEDT processes
- [x] Reproducible golden project (`examples/build_golden.py` → `golden_patch.aedt` + `golden_manifest.json`)

## Known limits (honest)

1. **Cancel**: terminates only worker-owned AEDT PIDs (not user desktops). In-solve graceful AEDT interrupt remains best-effort.
2. **PyAEDT 1.3 quirks on 2023.2**: `post.get_solution_data` / `osolution` can be broken for Modal Network; v0 uses native `GetModule("Solutions").ExportNetworkData` instead.
3. **Interrupted jobs** are marked, not auto-replayed; `run_resume` continues multi-trial runs without redoing completed trials.
4. **Optimizer** is seeded random only (interface ready for Bayesian/AI later).
5. Smoke geometry is a minimal modal network fixture for CI-speed solves, not a production antenna.
6. **Live-GUI tuning is opt-in**: `HFSS_MCP_ATTACH_LIVE=1` mutates (and saves) the original project — interactive use only; default trials always work on a workspace copy.
7. **GUI attach to a user's existing COM session** is best-effort: PyAEDT 1.3 cannot attach-by-PID to COM-created Desktops (`grpc_plugin`), and a fallback new Desktop cannot open a file locked by that session. With no running AEDT, hfss-mcp opens its own PyAEDT-owned GUI Desktop instead (clean-machine default).
8. **Stdio server startup**: `main()` pre-imports numpy/win32com/pyaedt before `mcp.run()`; without this, the first tool call in a stdio subprocess can deadlock in importlib locks.
9. **On this machine** tests need a redirected temp dir (`TMP/TEMP/TMPDIR` → repo-local, e.g. `.tmp_pytest`); the pywin32 `gen_py` cache created there is scanned by ruff — delete `.tmp_pytest/gen_py` before linting (or see BLOCKED.md).

## Real AEDT acceptance (this machine)

Command:

```powershell
uv run pytest -m real_aedt -v
```

Result on 2026-07-21: **PASSED** (~44–50s including Desktop start) — later found to
have been run with `HFSS_MCP_SESSION_MODE=new`; the *default* (auto) path was broken.

**Correction on 2026-07-29**: on the default path the same test **failed** two ways —
(a) from a clean machine, `design_snapshot` could not attach (COM-created session is
not attachable by PyAEDT 1.3 `grpc_plugin`; fallback new Desktop hit the COM-held
file lock), and (b) trials ran against the *live* original project
(`attach_live_project` default on), so the original `.aedt` hash changed.
Fixed without touching tests: trials now always solve a workspace copy in an
exclusive worker Desktop (`attach_live_project` is opt-in via
`HFSS_MCP_ATTACH_LIVE=1`); clean-machine GUI attach opens a PyAEDT-owned Desktop
instead of COM-ensure; the stdio server pre-warms heavy imports to avoid an
import-lock deadlock in tool threads.

Verified 2026-07-29 (clean machine, no pre-running ansysedt.exe):

| Check | Result |
|---|---|
| `pytest` (full, incl. real_aedt) | **61 passed** (~62 s) |
| `ruff check .` | **0 errors** |
| `mypy` | **0 errors** |
| `python examples/run_demo.py` | **exit 0**: 6 trials on `gap`, S11@2.4 GHz −0.1166 → −0.2351 dB, golden SHA-256 unchanged, zero ansysedt.exe residue |

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

# Demo (real closed loop, ~6 min)
uv run python examples/build_golden.py
uv run python examples/run_demo.py
```

Data directory: `HFSS_MCP_DATA_DIR` (default `~/.hfss-mcp`).
