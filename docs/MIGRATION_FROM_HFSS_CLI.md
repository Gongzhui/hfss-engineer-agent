# Migration from `hfss-cli`

Recorded on 2026-07-20. This document defines the relationship between the existing first-party CLI implementation and the new MCP implementation so that the old repository is preserved without creating two competing products.

## Repository map

| Role | Local path | Remote / source | Pinned commit |
|---|---|---|---|
| Active implementation | `../hfss-mcp` | `Gongzhui/hfss-mcp` | This repository |
| Legacy first-party implementation | `../hfss-cli` | `Gongzhui/hfss-cli` | `f2d6a796427d5742ba97b6dfbaa5bf1c6f58ec02` |
| Legacy first-party tuning workflow | `../hfss-cli-optimize-skill` | `Gongzhui/hfss-cli-optimize-skill` | `e40976c17747cb8aa0a24f091b1dea1f6e0b36cb` |
| Third-party references | `../hfss-mcp-references` | Blender MCP and EDA Agent upstreams | See `SOURCE_SNAPSHOTS.md` |

`hfss-cli` is retained with its full Git history and original remote. It is not abandoned or mixed into the third-party reference directory. New feature development belongs in `hfss-mcp`; changes to `hfss-cli` should normally be limited to critical maintenance or migration-support fixes.

## Reuse and rewrite boundary

Port selectively from `hfss-cli`:

- AEDT installation discovery and PyAEDT version/session normalization.
- Attachment to an already-running AEDT session, target identity checks, locking, and project history.
- Structured model, boundary, excitation, setup, parametric, solve, post-processing, variable, project, and material actions.
- Result extraction, reproducibility fixtures, protocol guardrails, and applicable unit tests.
- Evidence-driven optimization concepts from the companion Skill: durable artifacts, parameter groups, staged hypotheses, and verification gates.

Rewrite for the MCP architecture:

- Replace the large CLI parser and command dispatcher with small, typed MCP tools and an internal AEDT adapter.
- Do not expose `run-script` or arbitrary Python/script execution in the default MCP tool surface.
- Add allowlisted parameter updates with unit/range validation, project/design identity, checkpointing, run IDs, and auditable artifacts.
- Model long simulations as asynchronous `start/status/result/cancel` jobs.
- Keep any future CLI as a thin client of the same application layer rather than a second implementation.
- Revisit the WinUI monitor after the bridge, tool contract, job model, and recovery semantics are stable; it is not part of the first MCP milestone.
- Rewrite the optimization Skill only after the MCP tools and evaluation harness stabilize.

## Migration phases

1. Specify the MCP v0 tool schemas, adapter boundary, error envelope, and host/session identity model.
2. Port read-only discovery and inspection behavior with tests.
3. Port allowlisted parameter mutation, checkpointing, and durable run records.
4. Port solve/post-processing behavior behind asynchronous jobs.
5. Adapt the optimization workflow and build a golden parameterized antenna evaluation project.
6. Decide whether the legacy WinUI monitor and thin CLI provide enough value to maintain.

## Legacy baseline

The legacy repository contains 110 tracked files, including 26 Python files and 9 test files. A read-only test run on this machine with Python 3.12 produced:

- 151 passed
- 4 failed
- 7 subtests passed

The four failures are recorded as migration baseline issues, not regressions in this repository: two preview/snapshot tests did not produce an optional preview artifact in the current environment, and two CLI parser tests reject a negative comma-separated coordinate value as an option under the current Python/argparse behavior. They should be covered by typed MCP arguments rather than copied unchanged.

## Decision

There is one active product: `hfss-mcp`. The legacy repositories remain authoritative historical inputs until each relevant capability and test has an explicit migrated replacement. They may be archived later only after that coverage is demonstrated; no archive or deletion decision is implied by this migration plan.
