# HFSS Engineer Agent

Turn a Host Agent into an **HFSS antenna engineer**: decide which knobs are coupled, run joint **Optimetrics Parametric** matrices on a live Desktop, read the family of \(S_{11}\) curves, and repeat. Grouping and sample density are the agent's call — not a baked N, not genetic/PSO, and not one-factor-at-a-time value jumps.

This is **not** a generic HFSS/PyAEDT code-execution MCP (including the official-style “run any script” bridges). Arbitrary script execution is **not** exposed. The product is a **Skill + constrained tool surface**: attach the already-open AEDT over COM, pin allowlisted variables, export Results the human can see, and look at the model after each write. MCP is the I/O layer. Constitution: `docs/ADR-002-ENGINEER-SESSION-MODEL.md`.

The Python package / MCP server entry remains `hfss-mcp` for existing host configs.

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
| `cases/` | Antenna examples + benchmark (nominal / sandbox / answer). `examples/` is MCP smoke only. |
| `eval/` | Host Agent exam packs. Open `eval/exams/<id>/` in Cursor, not the repo root. |
| `docs/FUTURE-UNATTENDED-EXAM.md` | Deferred: unattended N-run exam harness (not implemented) |

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

Antenna cases live in `cases/` (see `cases/README.md`). Current first-party geometry: `cases/uwb_circular_notch/` (ported, solved nominal; sandbox is the exam). Host Agent exam: open Cursor on `eval/exams/uwb_circular_notch/` with AEDT on the sandbox. The older Skill demo `siw_feed_l1` remains under `benchmark/cases/`.

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
      },
      "lifecycle": "keep-alive"
    }
  }
}
```

Set `lifecycle: "keep-alive"` (or an `idleTimeout` of hours) on hosts that
support it. Long sweeps are watched with sleeps between polls; if the host
idle-closes the stdio server (pi-mcp-adapter default: 10 minutes), the job
registry / allowlist / view-hide bookkeeping — all in-memory — are lost while
AEDT keeps solving unattended. The server self-heals allowlist and view-hide
state from `~/.hfss-mcp/session-state.json` after a restart, but job handles
cannot be resurrected.

## MCP tools

| Tool | Kind | Notes |
|---|---|---|
| `health` | read | Adapter + COM-visible sessions (does not launch AEDT) |
| `session_list` | read | ROT desktops and open projects |
| `allowlist_load` | policy | Slim JSON / old manifest / `case.json` |
| `snapshot` | read | Variables, setups, identity. No screenshot |
| `variables_set` | mutate | Partial allowlisted update; `name` or `variable`; no solve; no save; returns `needs_solve` |
| `analyze_start` / `analyze_status` / `analyze_cancel` | job | `ok` on start = accepted, not solved. Status includes Message Manager lines |
| `report_types` / `report_list` / `report_create` / `report_export` | reports | List/create/export **Results** plots. After a parametric, pass `parametric` so that matrix is All and other swept vars stay Nominal. Omit / `families=[]` pins all known parametric vars. Reusing a name to apply families/pins → `report_exists`. `report_export` is GUI Export Data (`ExportToFile` 3rd arg False): variable columns become `variation`. Includes `traces`/`labeled`/`csv_format`; `stale_solution` if unsaved `variables_set`. `modal_s` is Modal `dB(S(1,1))`. `field_face` takes `face`, `frequency`, and `quantity` (`Mag_E` or `Mag_Jsurf`). |
| `view_hide` / `view_show` | visual | Exclude/include 3D objects for subsequent captures. Bookkeeping only — the GUI is not touched (no GUI-hide API on 2023 R2). `view_show(all_objects=true)` clears the set |
| `view_capture` | visual | Screenshot, always freshly rendered (warm-up export trick). Renders only the `fit=["name"]` parts — or everything minus the hidden set — via export-time `Selections`, framed by `FitToSelections`. `orientation` one of isometric/top/bottom/front/back/left/right |
| `variable_map` | read | Find-references: variable → object/expression |
| `project_save` | save | `save` or `save_as`; never automatic |
| `optimetrics_types` / `optimetrics_list` | read | Catalog + setups currently under **Optimetrics** |
| `parametric_create` | mutate | Real `OptiParametric` node. Sweep key `variable` or `name`. Allowlisted variables; **cap 256 points** (safety rail, not a recipe). Same name edits the node; never deletes |
| `parametric_start` | job | `Optimetrics.SolveSetup`. `ok` = accepted. Poll `analyze_status` |
| `parametric_export_table` | read | `ExportParametricSetupTable` (combination table, not Modal S11). Family S11 is a Results report |

**Not registered:** `exec`, `trial_*`, `run_*`, setup CRUD, checkpoint, `run_python_code`, Optimetrics Optimization / Sensitivity / Statistical / DOE.

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

The current Skill matches the V1 engineer loop: live attach, joint Optimetrics Parametric whose grouping and density the agent must justify from the structure, family curves via a Results plot, pin with `variables_set` after the matrix, and look at the live model after changing parameters. One-factor-at-a-time `variables_set` + Analyze is not the inner loop. The Skill does not ship a default N or samples-per-axis.

## Package layout

```
src/hfss_mcp/          # MCP server
skills/tune-hfss-antenna/   # Host Agent skill + plot script
benchmark/             # leak-free cases and eval runner
```

## License

MIT. See [LICENSE](LICENSE).
