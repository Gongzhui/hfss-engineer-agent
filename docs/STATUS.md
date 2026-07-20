# Implementation status (v0)

Last updated: 2026-07-20

## Done

- [x] AEDT environment discovery (structured install/exe/running status)
- [x] Versioned tune-only manifest + canonical SHA-256 ID
- [x] Policy validation (unknown/missing vars, units, bounds, NaN/Inf, path, setup, identity)
- [x] Adapter Protocol + FakeAdapter (full trial path)
- [x] PyAedtAdapter skeleton (attach/apply/copy/solve start; honest cancel limits)
- [x] Automatic pre-mutation checkpoint with SHA-256 (never overwrites original path)
- [x] SQLite durable jobs: start/status/result/cancel, idempotency, restart → interrupted
- [x] Narrow MCP tools (9 tools); no arbitrary code execution tools
- [x] Offline test suite (pytest) + ruff + mypy

## Not done / deferred

- [ ] Public checkpoint restore tool
- [ ] Full live PyAEDT metric extraction (S-params, gain, etc.)
- [ ] Reliable AEDT solve cancel on 2023 R2
- [ ] Background (non-inline) trial threads as default production mode
- [ ] Numerical optimizer / multi-trial run journal UX
- [ ] Real AEDT unattended smoke with temp project (attempted only when safe; see notes)

## Real AEDT smoke

Attempt policy: temp project only, no long EM solves, no user project opens, no closing foreign AEDT processes.

**2026-07-20 result:**

- Environment discovery on this machine: AEDT 2023.2 at `C:\Program Files\AnsysEM\v232`, `ansysedt.exe` present, process **not running**.
- PyAEDT import: `ansys.aedt.core` **1.3.0** OK.
- Live Desktop launch / temp-project session **not started** in unattended smoke (license/gRPC/startup risk). FakeAdapter e2e + injected-Hfss PyAedtAdapter unit tests remain the hard gate.
- Cancel limitation on 2023 R2 recorded honestly in `PyAedtAdapter.CANCEL_LIMITATION`.

## How to run

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy
uv run hfss-mcp
```

Set `HFSS_MCP_DATA_DIR` to relocate the job DB and checkpoint workspace.
