# Implementation status (V1 live COM attach)

Last updated: 2026-08-13

Live constitution: `ADR-002-ENGINEER-SESSION-MODEL.md`.
V0 decision (superseded, keep clauses): `ADR-001-AUTONOMY-EXECUTION-MODEL.md`.
V0 architecture snapshot (not the running MCP): `ARCHITECTURE_V0.md`.

## Done (code-enforced + verified this machine)

- [x] Live attach via COM ROT / `Dispatch` + `oDesktop.RunScript`. **Does not** construct PyAEDT `Desktop()` / `Hfss()`.
- [x] Will not launch a second AEDT; will not quit the user's Desktop on MCP/`AppContext.close()`.
- [x] 15 MCP tools. **Not registered:** `trial_*`, `run_*`, setup CRUD, checkpoint, `exec`.
- [x] Slim allowlist. `variables_set` is a partial update; no solve; no save.
- [x] `snapshot` is cheap JSON. `view_capture` and `variable_map` are on-demand.
- [x] Reports: `modal_s` and `terminal_z` CSV via `ExportNetworkData`; `farfield_2d` CSV via ReportSetup; `field_face` image on a named face/object + frequency.
- [x] V0 optimizer package removed (`jobs/`, checkpoint, workspace, `run_optimizer`, `adapter/pyaedt_adapter.py`).
- [x] Skill `skills/tune-hfss-antenna/` matches the V1 loop.
- [x] Offline FakeAdapter tests + **real AEDT 2023 R2** live attach.

## Known limits (honest)

1. **Far-field / field plots need solved data.** `farfield_2d` needs an infinite sphere and saved radiation fields. `field_face` needs a field solution at that frequency. The tools export when the design has the data; they do not auto-solve and they do not invent a plot.
2. **Analyze cancel** is best-effort. It will not kill the user's `ansysedt.exe`.
3. **Do not treat `.aedt.lock` ListenPort as gRPC.** User-style `ansysedt.exe` is COM.
4. **On this machine** tests need a redirected temp dir (`TMP/TEMP/TMPDIR` → repo-local, e.g. `.tmp_pytest`); delete `.tmp_pytest/gen_py` before `ruff check .` if pywin32 wrote a cache there.

## Real AEDT acceptance (this machine, 2026-08-13)

```powershell
$env:TMP = "$PWD\.tmp_pytest"; $env:TEMP = $env:TMP; $env:TMPDIR = $env:TMP
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt -v
```

Live attach: COM attach to existing PID, snapshot, `variables_set` on `gap`, `view_capture`, `variable_map`; Desktop still alive after `ctx.close()`; golden SHA-256 unchanged.

## How to run

```powershell
uv run hfss-mcp

$env:TMP = "$PWD\.tmp_pytest"; $env:TEMP = $env:TMP; $env:TMPDIR = $env:TMP
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt
uv run ruff check src/hfss_mcp tests
uv run mypy
```

Data directory: `HFSS_MCP_DATA_DIR` (default `~/.hfss-mcp`).
