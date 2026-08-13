# hfss-mcp v0 architecture (real AEDT)

> **Historical snapshot of the V0 code shipped 2026-07-29.** Not the running MCP.
>
> Running package: `docs/STATUS.md`. Live constitution: `ADR-002-ENGINEER-SESSION-MODEL.md`.
> V0 decision record (superseded): `ADR-001-AUTONOMY-EXECUTION-MODEL.md`.

Aligns with `ADR-001-AUTONOMY-EXECUTION-MODEL.md` (the decision V0 implemented).

## Layers

```
Agent
  │ MCP tools (typed, narrow)
  ▼
AppContext
  ├─ RuntimeConfig (HFSS_MCP_ADAPTER, data dir, version)
  ├─ policy + TuneManifest (1.1, MetricSpec)
  ├─ JobStore / RunStore (SQLite, payload-hash idempotency)
  ├─ Supervisor (claims jobs, spawns workers)
  ├─ RunOrchestrator (seeded random multi-trial)
  ├─ WorkspaceService (never write original .aedt)
  └─ CheckpointService
        │
        ▼ worker process (one job)
     exclusive PyAedtAdapter + Desktop
     analyze → ExportNetworkData → metrics → SQLite
```

## Production vs fake

| Mode | When | Execution |
|---|---|---|
| `pyaedt` | Default if AEDT exe found, or `HFSS_MCP_ADAPTER=pyaedt` | Worker processes, blocking analyze inside worker |
| `fake` | `HFSS_MCP_ADAPTER=fake` or missing AEDT / demo | In-process FakeAdapter (tests) |

`health.real_hfss_ready` is true only for pyaedt + existing `ansysedt.exe`.

## Job / run states

Jobs: `queued` → `running` → `completed|failed|cancelled`  
Also: `cancel_requested`, `interrupted` (restart recovery).

Runs: multi-trial optimization journal with `run_resume`.

## Metric extraction

Structured MetricSpec only. Real path:

1. `odesign.Analyze(setup)`
2. `odesign.GetModule("Solutions").ExportNetworkData(...)` → Touchstone
3. Parse S11 magnitude → dB; evaluate min / min-freq / at-target

No arbitrary expression evaluation.

## Concurrency

- Default serial per project lock key
- Atomic SQLite claim (`state=queued` → `running`)
- One worker process per job; no shared mutable PyAEDT adapter across jobs
