# HFSS MCP

A constrained MCP bridge for AI-assisted HFSS simulation and antenna tuning.

The v0 implementation is a **tune-only** vertical slice: inspect the environment, validate a project-specific parameter manifest, apply complete allowlisted parameter vectors with checkpointing, run approved setups as **durable asynchronous jobs**, and return traceable metrics. Arbitrary script execution and unrestricted geometry edits are **not** part of the default tool surface.

Architecture decisions: `docs/ADR-001-AUTONOMY-EXECUTION-MODEL.md`, `docs/ARCHITECTURE_V0.md`, `docs/STATUS.md`.

## Local development

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy
uv run hfss-mcp
```

Optional data directory (job DB + checkpoints):

```powershell
$env:HFSS_MCP_DATA_DIR = "D:\hfss-mcp-data"
```

The current development machine has AEDT 2023 R2 at `C:\Program Files\AnsysEM\v232`.

## MCP tools (v0)

| Tool | Kind | Description |
|---|---|---|
| `health` | read | Bridge health, version, tool list |
| `environment_status` | read | AEDT install discovery (version, root, exe, running) without launching AEDT |
| `manifest_validate` | read | Validate tune-only manifest; returns stable `manifest_id` (SHA-256) |
| `design_snapshot` | open approved project | Snapshot project/design identity, revision, variables |
| `trial_start` | mutate + solve | Start one allowlisted trial job (idempotent) |
| `trial_status` | read | Durable job state |
| `trial_result` | read | Metrics, checkpoint path, structured errors |
| `trial_cancel` | best-effort | Cancel queued/running trial |
| `checkpoint_list` | read | List pre-mutation checkpoints |

**Not registered:** `run_python_code`, `run_python_script`, `exec`, generic invoke/object traversal, unrestricted geometry, clear/close of arbitrary user projects.

## Manifest (tune-only contract)

A run is governed by an immutable JSON manifest that includes:

- schema version, absolute project path (`.aedt` / `.aedtz`)
- project/design identity
- allowed setup/sweep pairs
- complete allowlisted parameters with unit and min/max
- allowed metrics
- stop conditions (`max_trials`, `max_runtime_seconds`)
- concurrency and checkpoint policy

Candidates must supply a **complete parameter vector**. The server rejects unauthorized variables, missing variables, unit mismatches, NaN/Infinity, out-of-range values, unsafe paths, unauthorized setups, and manifest ID mismatches **before** any adapter mutation.

## Trial job model

Jobs are stored in SQLite and support `start` / `status` / `result` / `cancel` with states:

`queued`, `running`, `completed`, `failed`, `cancel_requested`, `cancelled`, `interrupted`

- Duplicate `idempotency_key` returns the original job (no re-mutate / re-solve).
- On process restart, leftover `running` jobs become `interrupted`.
- First mutation auto-creates a hashed project checkpoint (never overwrites the original path).

Default MCP process uses a **FakeAdapter** so tools and jobs can be exercised without a license. A `PyAedtAdapter` is available for real host work; live cancel and metric extraction still have known limits on AEDT 2023 R2 (documented in `docs/STATUS.md`).

## Repository roles

- This repository (`Gongzhui/hfss-mcp`) is the only active implementation and the public agent interface.
- [`Gongzhui/hfss-cli`](https://github.com/Gongzhui/hfss-cli) is the preserved first-party legacy implementation (migration input).
- Blender MCP, EDA Agent, and community HFSS MCP clones under `../hfss-mcp-references/` are **read-only** references — this project does **not** fork or deploy `ansys/pyaedt-mcp`.

See `SOURCE_SNAPSHOTS.md`, `docs/MIGRATION_FROM_HFSS_CLI.md`, and `docs/COMMUNITY_HFSS_MCP_REVIEW.md`.

## Package layout

```
src/hfss_mcp/
  server.py           # MCP tools (narrow surface)
  app.py              # Application context
  manifest.py         # Manifest schema + canonical hash
  policy.py           # Authorization / validation
  domain.py           # Jobs, snapshots, vectors
  environment.py      # AEDT discovery
  checkpoint.py       # Checkpoint service
  adapter/            # Protocol, Fake, PyAEDT
  jobs/               # SQLite store + trial runner
```
