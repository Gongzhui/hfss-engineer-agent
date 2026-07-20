# hfss-mcp v0 architecture

Status: implemented (tune-only vertical slice).  
Aligns with `ADR-001-AUTONOMY-EXECUTION-MODEL.md`.

## Layers

```
Agent (intent / hypotheses)
        │ MCP tools (typed, narrow)
        ▼
  AppContext (hfss_mcp.app)
        │
        ├─ policy + manifest (authorize candidates)
        ├─ JobStore (SQLite durable jobs)
        ├─ TrialRunner (stage machine for one trial)
        ├─ CheckpointService (pre-mutation project copy)
        └─ AedtAdapter Protocol
               ├─ FakeAdapter (offline e2e)
               └─ PyAedtAdapter (real host; partial v0)
```

## Control boundary

| Layer | Owns |
|---|---|
| Agent | Engineering intent, search hypotheses, exception strategy |
| Policy / manifest | Project identity, allowlisted parameters, units, ranges, setups, metrics, budgets |
| Job state machine | Sequence, checkpoint, start/status/result/cancel, restart recovery, idempotency |
| Adapter | Semantic transactions only (no arbitrary code) |

Prompt text is **not** a substitute for these checks. Rejections happen in `policy.py` and adapter revision/read-back logic.

## Manifest identity

`TuneManifest` is versioned (`schema_version: "1.0"`). Canonical JSON (sorted keys, no notes field) is hashed with SHA-256 to produce a stable `manifest_id`. Candidates must be **complete parameter vectors**; partial updates are rejected so trials never depend on hidden AEDT session state.

## Trial sequence

1. `manifest_validate` — parse, policy-check path/extension, register, return `manifest_id`.
2. `design_snapshot` — attach approved project/design, return revision + variables.
3. `trial_start` — authorize vector → durable job (idempotency key) → auto checkpoint → apply vector (expected revision + batch write + read-back + diff) → validate setup → solve → extract approved metrics → complete.
4. `trial_status` / `trial_result` — read durable store (survives process restart).
5. `trial_cancel` — queued → cancelled; running → `cancel_requested` then adapter cancel hook (honest if host cannot interrupt).
6. `checkpoint_list` — list hashed project copies (public restore deferred).

## Job states

`queued` → `running` → `completed` | `failed` | `cancelled`  
Also: `cancel_requested`, `interrupted` (leftover `running`/`cancel_requested` on process restart).

SQLite file: `$HFSS_MCP_DATA_DIR/jobs.sqlite3` (default `~/.hfss-mcp/jobs.sqlite3`).

## MCP public tools

| Tool | Risk | Purpose |
|---|---|---|
| `health` | read | Package + environment summary |
| `environment_status` | read | Structured AEDT install/exe/running probe (no launch) |
| `manifest_validate` | read | Validate + register tune-only manifest |
| `design_snapshot` | open approved project | Authoritative snapshot |
| `trial_start` | mutate + solve | Durable allowlisted trial |
| `trial_status` | read | Job state |
| `trial_result` | read | Metrics / artifacts / errors |
| `trial_cancel` | best-effort cancel | Cancel request |
| `checkpoint_list` | read | List checkpoints |

### Explicitly not registered

`run_python_code`, `run_python_script`, `exec`, generic `invoke` / object traversal, unrestricted geometry, clear/close arbitrary user projects.

## Adapters

- **FakeAdapter**: full semantic protocol for automated tests and offline demos.
- **PyAedtAdapter**: attach/open, variable apply with read-back, project copy, solve start (best-effort). Live metric extraction and reliable cancel are limited on AEDT 2023 R2 — see known limits.

## Known limits (v0)

1. Default server uses FakeAdapter (`use_fake=True`) so MCP clients can exercise the full tool surface without AEDT licenses.
2. PyAEDT cancel is best-effort; jobs must not forge `cancelled` if the host cannot interrupt.
3. Live PyAEDT metric extraction is not fully implemented; FakeAdapter returns synthetic metrics for e2e.
4. Checkpoint **restore** is internal scaffolding only (list is public).
5. No numerical optimizer loop yet — agent or a later skill owns candidate selection.
6. GUI / computer-use fallback is out of scope.
