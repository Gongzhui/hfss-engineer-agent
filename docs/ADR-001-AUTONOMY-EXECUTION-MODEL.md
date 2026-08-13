# ADR-001: Autonomy execution model

- Status: **Superseded**
- Date: 2026-07-20
- Superseded on: 2026-08-13
- Superseded by: `ADR-002-ENGINEER-SESSION-MODEL.md`
- Scope: HFSS antenna tuning and later autonomous design workflows

This file is kept as the V0 decision record. Do not treat it as the live product constitution.

## What remains in force (carried into ADR-002)

- No arbitrary `exec` / `run_python_code` / unrestricted host-process execution on the default MCP surface.
- Typed, narrow tools; a new capability needs a schema, authorization, postcondition, and audit before it ships.
- Do not deploy, fork, or wrap `ansys/pyaedt-mcp` as the product runtime (see the re-evaluation below).
- Allowlisted parameter mutation with unit/range checks and project/design identity.
- Expensive solves are asynchronous jobs with durable `start/status/result/cancel`.
- PyAEDT is the supported AEDT execution library; the official repo remains an engineering reference.

## What is superseded

- A numerical optimizer owns the inner candidate-selection loop.
- Extract only pre-approved scalar metrics; no agent-created reports.
- Default path never writes the user's original `.aedt`; live GUI attach is a dangerous opt-in that saves the original.
- The tune loop is bundled as apply-full-vector + solve + S11 scalars (`trial_*`).
- GUI automation is only a declared fallback, not the primary session model.

The original accepted text follows unchanged.

## Decision

The public MCP surface will implement a hierarchical closed-loop system:

1. The agent owns engineering intent, hypotheses, search-space changes, and exception strategy.
2. A server-side policy broker owns authorization, project/design identity, parameter bounds, resource budgets, and stopping conditions.
3. A durable workflow state machine owns sequencing, stage gates, bounded retries, checkpoints, and restart recovery.
4. A numerical optimizer owns the repetitive candidate-selection loop for expensive HFSS evaluations.
5. Typed domain tools execute semantic transactions through PyAEDT or a narrowly scoped native AEDT adapter.
6. Structured AEDT state, solver status, logs, result data, and selected screenshots provide ground truth.

GUI automation is a declared fallback for operations that have no stable API. It is not the primary actuator for unattended runs. An operation that requires a modal dialog or cannot prove its postcondition is blocked in unattended mode.

Model-generated code may be used only as sandboxed orchestration over typed, broker-authorized tools. Arbitrary Python, VBScript, generic object traversal, and unrestricted host-process execution are not registered in the default MCP surface.

Verification happens after semantic state transitions, not after every mouse or API primitive. Cheap structural checks follow every mutation; expensive validation, solve, result, and visual checks are stage gates.

## Required runtime shape

The initial tune-only loop is:

1. Read an authoritative project/design snapshot and revision.
2. Validate a candidate against an immutable run manifest and parameter allowlist.
3. Create or confirm a recoverable project checkpoint.
4. Apply all candidate parameters as one semantic transaction.
5. Read the values back and verify the expected revision and units.
6. Start an asynchronous solve and return a durable job ID.
7. Support status, progress, result, cancellation, timeout, and restart recovery.
8. Verify convergence and extract only approved metrics.
9. Append the candidate, artifacts, metrics, and outcome to the run journal.
10. Let the numerical optimizer select the next candidate until a declared stop condition is met.

Every mutating or expensive call must be attributable to a run ID and idempotency key. Repeated delivery of the same request must not duplicate a solve or mutation.

## Re-evaluation of `ansys/pyaedt-mcp`

The official Ansys/Synopsys implementation was re-evaluated at `main` commit `eb2fd030ac50de2d77282a43bdf9262a7d773485` on 2026-07-20. The remote `main` branch had not advanced beyond the previously reviewed commit.

It is a strong general-purpose interactive PyAEDT assistant, but it does not implement this decision:

- It is API-first and has good AEDT lifecycle handling, gRPC session discovery, dynamic tool gating, stdio/HTTP transports, screenshots, logs, toolsets, and layered tests.
- Its intended escape hatch is also its central workflow mechanism: the system prompt directs the model to generate PyAEDT and call `run_python_code` whenever no dedicated tool exists.
- `run_python_code` executes supplied code with direct access to both the PyAEDT `desktop` and native `odesktop` handles. The documentation warns that generated code can close or destabilize a project.
- Its official patch-antenna example performs geometry, ports, boundaries, setup, solve, report creation, file parsing, and result extraction through repeated arbitrary-code calls. The agent, rather than the server, therefore owns most sequencing and invariants.
- `analyze_design` can request non-blocking or threaded PyAEDT execution, but the MCP contract returns no durable job ID and provides no status, cancellation, result retrieval, or restart-recovery protocol.
- It has no project-specific parameter manifest, allowlist/range policy, automatic checkpoint/restore, immutable trial journal, idempotency contract, or server-side optimization state machine.
- Its checks are useful interactive practices—read text errors, split code into short calls, save frequently, and capture screenshots—but they are not enforced postconditions over authoritative HFSS state.

## Adoption boundary

Do not deploy, fork, or wrap `ansys/pyaedt-mcp` as the product runtime. Its control boundary is deliberately broader than this project and narrowing it would require replacing the central workflow model while carrying upstream coupling.

Continue the independent `hfss-mcp` implementation and use:

- PyAEDT as the supported AEDT execution library.
- The official repository as the primary reference for lifecycle context, session discovery, explicit connection selection, dynamic tool visibility, transport configuration, screenshots/logs, packaging, and test organization.
- Apache-licensed helper ideas or small adapted components only when they remain behind this project's policy and job abstractions.
- The first-party `hfss-cli` code as migration input for proven session identity, locking, actions, result extraction, and regression fixtures.

`ansys-common-mcp` may be evaluated as an infrastructure dependency later, but adopting it must not expose the official arbitrary-code or broad project-mutation surface.

## Consequences

- The project owns more workflow and persistence code, but safety and unattended reliability are enforceable rather than prompt-dependent.
- The first release remains intentionally narrow: inspect, tune allowlisted variables, run approved setups, and return traceable results.
- Adding a new capability requires a typed schema, authorization rule, postcondition, recovery behavior, audit record, and evaluation case before it enters the default tool surface.
