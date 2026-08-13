# HFSS MCP

Constrained MCP bridge for AI-assisted HFSS antenna tuning on **Ansys Electronics Desktop**. Arbitrary script execution is **not** exposed.

**Live path (V1):** attach the user's already-open AEDT over COM (ROT). Host Agent hypothesizes → sets 1–2 allowlisted variables → Analyze once → exports the plot it needs. Curves as CSV, geometry as `view_capture`. No autosave. Constitution: `docs/ADR-002-ENGINEER-SESSION-MODEL.md`.

V0 optimizer tools (`trial_*`, `run_*`, workspace copies, exclusive worker Desktops) are **removed** from the MCP surface.

## Documents

| File | Role |
|---|---|
| `docs/ADR-002-ENGINEER-SESSION-MODEL.md` | Current constitution |
| `docs/ADR-001-AUTONOMY-EXECUTION-MODEL.md` | Superseded V0 decision (kept) |
| `docs/STATUS.md` | What the running V1 package actually does |
| `docs/ARCHITECTURE_V0.md` | V0 code snapshot (2026-07-29) |
| `docs/COMMUNITY_HFSS_MCP_REVIEW.md` | 2026-07-20 review of public HFSS MCPs |
| `docs/MIGRATION_FROM_HFSS_CLI.md` | Relation to frozen `hfss-cli` |
| `SOURCE_SNAPSHOTS.md` | Pinned third-party clones |
| `docs/archive/LLM-TUNING-RESEARCH.md` | Archived 2023–25 LLM-as-optimizer survey; does not govern V1 |

## Production start (this machine)

```powershell
cd C:\Users\Gongzhui\Documents\Projects\hfss-mcp
uv sync
# Optional overrides:
# $env:HFSS_MCP_ADAPTER = "pyaedt"   # default when AEDT is installed
# $env:HFSS_MCP_DATA_DIR = "D:\hfss-mcp-data"
# $env:HFSS_MCP_AEDT_VERSION = "2023.2"
uv run hfss-mcp
```

`health` must report:

- `adapter`: `pyaedt`
- `real_hfss_ready`: `true` when `ansysedt.exe` is present
- `connection_mode`: `com_attach_live`

Open Electronics Desktop with your project **before** connecting the MCP. The server will not launch a second Desktop, and it will not quit yours on exit.

## Demo / acceptance

Open Electronics Desktop (user-style, no extra flags) and keep a project open. Then:

```powershell
uv run python examples/build_golden.py   # if golden_patch.aedt is missing
$env:TMP = "$PWD\.tmp_pytest"; $env:TEMP = $env:TMP; $env:TMPDIR = $env:TMP
uv run pytest -m real_aedt -v
```

That attaches the already-open Desktop over COM, snapshots, sets `gap`, captures a view, and asserts AEDT is still alive. It does not Save the golden file.

The interactive demo is a Host Agent session with Skill `tune-hfss-antenna` on `benchmark/cases/siw_feed_l1/`.

Fake mode (tests/demo only):

```powershell
$env:HFSS_MCP_ADAPTER = "fake"
$env:HFSS_MCP_DEMO = "1"
uv run hfss-mcp
```

### Minimal MCP client config (stdio)

```json
{
  "mcpServers": {
    "hfss-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Users\\Gongzhui\\Documents\\Projects\\hfss-mcp", "hfss-mcp"],
      "env": {
        "HFSS_MCP_ADAPTER": "pyaedt",
        "HFSS_MCP_AEDT_VERSION": "2023.2"
      }
    }
  }
}
```

## MCP tools

| Tool | Kind | Notes |
|---|---|---|
| `health` | read | Adapter + COM-visible sessions (does not launch AEDT) |
| `session_list` | read | ROT desktops and open projects |
| `allowlist_load` | policy | Slim JSON / old manifest / `case.json` |
| `snapshot` | read | Variables, setups, identity. No screenshot |
| `variables_set` | mutate | Partial allowlisted update; no solve; no save |
| `analyze_start` / `analyze_status` / `analyze_cancel` | job | Analyze on the live design |
| `report_types` / `report_list` / `report_create` / `report_export` | reports | `modal_s` / `terminal_z` / `farfield_2d` → CSV; `field_face` → image (needs face+frequency) |
| `view_capture` | visual | 3D modeler screenshot; optional isolate |
| `variable_map` | read | Find-references: variable → object/expression |
| `project_save` | save | `save` or `save_as`; never automatic |

**Not registered:** `exec`, `trial_*`, `run_*`, setup CRUD, checkpoint, `run_python_code`.

## Allowlist

Writable variables only: project/design identity, name/unit/min/max, optional default setup. Load from `examples/golden_manifest.json` or `benchmark/cases/siw_feed_l1/case.json`.

## Safety model

- Attaches the already-open COM Desktop. Will not start a second AEDT, and will not quit yours on MCP exit.
- Writes only allowlisted variables. Does not insert designs, edit geometry, or autosave.
- Analyze cancel will not kill the user's `ansysedt.exe`.
- Policy rejections happen in code before mutation.

## Development / tests

```powershell
uv run pytest                 # offline + real_aedt if AEDT present
uv run pytest -m "not real_aedt"
uv run pytest -m real_aedt    # requires AEDT 2023 R2
uv run ruff check .
uv run mypy
```

## Agent Skill

Procedural tuning knowledge lives in `skills/tune-hfss-antenna/` (not inside the Python package). On this machine it is linked from `~/.agents/skills/tune-hfss-antenna` so Cursor and other hosts can discover it without a `.cursor/` folder in the repo.

The current Skill matches the V1 engineer loop (live attach, partial `variables_set`, Analyze, reports, `view_capture`, `variable_map`).

## Package layout

```
src/hfss_mcp/          # MCP server
skills/tune-hfss-antenna/   # Host Agent skill + plot script
benchmark/             # leak-free cases and eval runner
```
