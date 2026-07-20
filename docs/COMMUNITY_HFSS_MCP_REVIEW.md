# Review of public HFSS/AEDT MCP implementations

Reviewed on 2026-07-20 from full Git clones pinned in `SOURCE_SNAPSHOTS.md`.

## Conclusion

Several projects meet the basic Blender-MCP-level bar: they implement a real MCP transport, keep an AEDT/HFSS connection alive, and expose structured tools that can drive the host. None meets the full EDA-Agent-level bar required by this project: a constrained tool surface, durable asynchronous jobs, checkpoint and recovery semantics, auditable runs, tool maturity metadata, and layered automated verification.

The official `ansys/pyaedt-mcp` has the strongest repository engineering and should become the primary implementation reference. It is not a drop-in foundation for this product because arbitrary Python and script execution are first-class tools, and its non-blocking solve options do not provide a durable `start/status/result/cancel` job protocol. The current `hfss-mcp` rewrite remains justified.

## Evaluation bar

The comparison uses the two previously selected references as two levels rather than treating all MCP servers as equivalent.

- Basic host-control bar (Blender MCP): real MCP transport, a live host connection, structured calls, clean protocol output, and enough lifecycle handling to operate interactively.
- Production workflow bar (EDA Agent): modular typed tools, deliberately constrained permissions, batching/catalog metadata, durable state and audit artifacts, checkpoint/recovery, asynchronous cancellable jobs, and layered offline/integration/real-host tests.

Legend: **Strong** is implemented and evidenced in source/tests; **Partial** exists but lacks the required semantics or coverage; **No** is absent; **Conflict** directly contradicts this project's tune-only policy.

| Repository | MCP/session | Modular typed tools | Tune-only safety | Durable jobs/cancel | Checkpoint/recovery | Catalog/metadata | Audit/observability | Automated tests | Assessment |
|---|---|---|---|---|---|---|---|---|---|
| `ansys/pyaedt-mcp` | Strong | Strong | Conflict | Partial | No | Strong | Partial | Strong | Best engineering reference; not the desired permission model |
| `LaplaceYoung/ansys-aedt-mcp` | Strong | Strong | Conflict | No | No | Partial | Partial | Strong | Broad tested API wrapper; too open and too large a tool surface |
| `K-13ROBOT/HFSS_MCP` | Strong | Strong | Partial | No | No | Partial | Strong | Partial | Best HFSS-native COM/action reference; still blocking and weakly tested |
| `Kk5212/Multi_Agent_Design_with_HFSS_MCP_Server` | Strong | Strong | Partial | No | Partial | Partial | Partial | No tracked tests | Closest conceptual match for adapter/workspace/checkpoints, but incomplete |
| `leonardwy/HFSS_McpServer` | Strong | Partial | Partial | No | No | No | Partial | No | Persistent-session prototype in one large module |
| `NedaEmami123/hfss-mcp` | Strong | Partial | Conflict | Partial | No | No | Partial | No | Useful recipe/job demo, unsafe and non-durable |
| `jessega0/HFSS-mcp` | Strong | Strong | Conflict | No | No | No | No | Minimal | Clean small COM adapter, but includes raw Python/VBScript escape hatches |
| `gfgf2023/hfss-mcp-server` | Strong | Strong | Conflict | No | No | No | Partial | No | Broad modular toolbox, but explicitly exposes `exec`-based arbitrary code |

## Findings by priority

### 1. `ansys/pyaedt-mcp` — primary upstream reference

Strengths:

- Official Ansys/Synopsys repository, Apache-2.0, conventional packaging, CI/security/documentation structure, 99 commits at the reviewed revision.
- Uses the shared `ansys-common-mcp` base, a typed application context, lifecycle hooks, stdio and streamable HTTP transports, timeouts, CORS configuration, and Docker-aware behavior.
- Discovers running local gRPC sessions and asks for an explicit selection instead of silently attaching or launching another AEDT instance.
- Tags tools by lifecycle requirements and can dynamically hide AEDT-only tools until a session is connected.
- Publishes a `toolsets://definition` resource with lifecycle, project, simulation, scripting, inspection, results, and guideline groups.
- Includes unit, integration, system, and real-AEDT test markers. The offline unit selection completed with 138 passing tests on this machine; Ruff also passed.
- Supports screenshots as MCP image content, PyAEDT log retrieval, configuration export, and explicit disconnect choices.

Gaps against this project:

- `run_python_code` uses `exec`, and `run_python_script` calls AEDT `RunScript`; the system prompt recommends generated Python as the normal fallback. This conflicts with the tune-only boundary.
- The public surface has project creation, design creation, full analysis, and clearing/closing operations rather than an allowlisted parameter-only capability set.
- `analyze_design` exposes PyAEDT `blocking=False` and `run_in_thread`, but returns no durable job ID, pollable state, cancellation contract, or restart recovery record.
- There is no automatic pre-mutation project checkpoint or per-run artifact manifest.
- Toolsets describe logical groups but do not carry EDA-Agent-style maturity and interaction-risk metadata.

Adopt: lifecycle/context patterns, session discovery and explicit selection, dynamic tool gating, transport setup, toolset resource, screenshot/log patterns, test taxonomy, and Apache-licensed helper ideas. Do not adopt the arbitrary-code tools or broad default permissions.

### 2. `LaplaceYoung/ansys-aedt-mcp` — broad wrapper and test reference

Strengths:

- Separates session, operations, serialization, and MCP registration; serializes stateful PyAEDT return objects; uses an `RLock` around the active session.
- Contains 109 dedicated MCP tools plus resources, batching, allowlisted domain operation tables, and both PyAEDT and native AEDT access paths.
- Offline tests completed with 39 passing tests and Ruff passed.

Gaps:

- The generic `aedt_call`/`aedt_batch_call` path can traverse and invoke arbitrary public attributes, and callers can set `allow_private=True`. This defeats a strict capability boundary even though many domain methods have allowlists.
- All 109 tools are directly exposed; there is no maturity/risk catalog or staged discovery comparable to EDA Agent.
- Solves are calls, not durable jobs; there is no checkpoint, cancellation, recovery state, or durable audit log.
- PolyForm Noncommercial licensing prevents treating it like an ordinary permissive source dependency.

Adopt selectively: JSON serialization, session locking, fake-backed operation tests, small allowlist tables, and batch result envelopes. Do not copy the generic invocation surface.

### 3. `K-13ROBOT/HFSS_MCP` — strongest HFSS-native action reference

Strengths:

- Uses native COM rather than PyAEDT and reports real testing across AEDT 2019.2 and 2025.2, which is useful for native API compatibility and PyAEDT gaps.
- Data-driven registry exposes 66 tools covering sessions, parameterized geometry, ports, periodic boundaries/Floquet ports, sweeps, optimization, S-parameters, input impedance, and radiation results.
- Correctly isolates stdout for MCP stdio and retains the user's AEDT process on server shutdown.
- Writes append-only JSONL tool traces with arguments, outcomes, errors, and duration.
- Its MCP smoke test passed on this machine and verified 66 tool schemas plus the no-active-design guard.

Gaps:

- Analysis, parametric sweeps, and optimization are explicitly blocking and cannot be cancelled.
- Client confirmation is relied on for expensive tools; the server sets auto-confirm under stdio. Safety therefore depends on client configuration.
- Variable mutation accepts arbitrary names/expressions without a project-specific allowlist, unit/range constraints, or atomic multi-variable rollback.
- No checkpoint/recovery workflow and only a two-assertion smoke test are tracked.

Adopt selectively: native COM connection fallback, stdout isolation, action schemas, periodic/Floquet and report extraction compatibility patterns, and JSONL tracing.

### 4. `Kk5212/Multi_Agent_Design_with_HFSS_MCP_Server` — closest product-shape prototype

Strengths:

- Separates `HfssAdapter`, manager, model reader, controller, context, and configuration; includes an in-memory fake adapter.
- Uses a workspace copy and versioned `.aedt` checkpoints, can restore the newest checkpoint when a workspace file is locked, and batches variable changes.
- Keeps a narrow 18-tool interface oriented around reading, setting variables, simulation, metrics, DRC, checkpoints, and final export.

Gaps:

- The advertised tests and template/manifest assets are not present in the reviewed Git tree; its default template path points into a missing `tests` subtree.
- Variable setters do not enforce an allowlist or configured ranges and may create new variables.
- Simulation is synchronous, checkpoints are user-invoked rather than automatic before mutation/solve, and there is no durable job or audit model.

Adopt selectively: adapter protocol, in-memory fake concept, workspace-copy model, checkpoint naming, and focused tool granularity. Reimplement and test rather than importing the unfinished code.

### 5. Remaining prototypes

- `leonardwy/HFSS_McpServer`: useful persistent-session and reconnect metadata plus local documentation search, but it is a large monolith, globally suppresses `atexit.register` during import, has no automated tests, and lacks jobs/checkpoints.
- `NedaEmami123/hfss-mcp`: demonstrates background thread IDs for complete antenna recipes and arbitrary scripts, but jobs are in-memory only, share global PyAEDT state without a lock, cannot be cancelled, and disappear on restart.
- `jessega0/HFSS-mcp`: a readable small native-COM adapter with 44 structured tools and three passing helper tests; raw Python and VBScript tools, synchronous solves, and no recovery model make it only a prototype reference.
- `gfgf2023/hfss-mcp-server`: modular 61-tool FastMCP server with several transports and resources, but it explicitly executes arbitrary Python with `exec`; warnings replace enforcement, and no automated tests are tracked.

## Verification performed

- Parsed all 70 Python files in the first seven community clones successfully; the official clone added 25 more Python files and was inspected separately.
- `ansys/pyaedt-mcp`: 138 offline unit tests passed; Ruff passed. Integration/system/real-AEDT tests were intentionally not run because they can launch or mutate AEDT.
- `LaplaceYoung/ansys-aedt-mcp`: 39 offline tests passed; Ruff passed.
- `jessega0/HFSS-mcp`: 3 helper tests passed.
- `K-13ROBOT/HFSS_MCP`: MCP stdio smoke test passed and listed 66 tools.
- Repositories without tracked automated tests were not credited based only on README claims.

## Decision for `hfss-mcp`

Keep the current narrow rewrite and combine proven patterns rather than forking any one implementation:

1. Use official `ansys/pyaedt-mcp` as the main reference for MCP lifecycle, transport, dynamic discovery, toolsets, screenshots/logs, packaging, and test organization.
2. Port first-party `hfss-cli` session identity, locking, proven actions, result extraction, and regression fixtures behind an internal adapter.
3. Use `K-13ROBOT/HFSS_MCP` only as a reference for native COM compatibility and specific HFSS actions where PyAEDT is weak.
4. Implement the adapter/fake/workspace concepts demonstrated by the Kk5212 project, but enforce a project-specific parameter manifest and automatic checkpointing.
5. Add what no reviewed HFSS implementation provides: durable `start/status/result/cancel` jobs, restart recovery, immutable run manifests, parameter allowlists and ranges, and an evaluation harness.
6. Never register arbitrary Python, VBScript, generic object traversal, unrestricted geometry, or project-clearing operations in the default MCP surface.

This makes the public implementations valuable source material without weakening the product boundary that motivated the rewrite.
