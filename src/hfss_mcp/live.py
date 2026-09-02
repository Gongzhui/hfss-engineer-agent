# ruff: noqa: E501
"""Attach to the user's already-open AEDT via COM. Never spawn a worker Desktop.

PyAEDT Desktop() is intentionally not used here: its atexit release can quit the
GUI, and Hfss() will insert a design when none is present.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.com_session import (
    desktop_process_id,
    execute_run_script,
    get_desktop,
    iter_rot_desktops,
    list_com_projects,
    load_win32_client,
    normalize_aedt_version,
    open_project_on_desktop,
)
from hfss_mcp.domain import ParameterValue, utc_now_iso
from hfss_mcp.errors import AdapterError
from hfss_mcp.ids import sha256_hex
from hfss_mcp.metrics import normalize_exported_report_csv

_EXPR_GLUED = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z_%µμ]+)$"
)
_VAR_TOKEN = re.compile(r"\$?[A-Za-z_][\w$]*")
_AIRBOX_KEYS = (
    "airbox",
    "air",
    "region",
    "openregion",
    "radiationbox",
    "vacuumbox",
    "airregion",
)


def is_airbox_object_name(name: str) -> bool:
    """Name-heuristic for radiation/air boxes. Capture does not use this automatically."""
    key = "".join(ch for ch in name.lower() if ch.isalnum())
    return key in _AIRBOX_KEYS or "airbox" in key


VIEW_ORIENTATIONS = (
    "isometric",
    "top",
    "bottom",
    "front",
    "back",
    "left",
    "right",
)

_EDITOR_VIS = """
def all_object_names():
    names = []
    for group in ('Solids', 'Sheets', 'Lines'):
        try:
            names.extend([str(x) for x in (oEditor.GetObjectsInGroup(group) or [])])
        except Exception:
            pass
    return names
""".strip()


def view_visibility_script(
    *,
    names: list[str],
    show: bool,
    all_objects: bool = False,
) -> str:
    """IronPython: validate object names for the hidden-set bookkeeping.

    AEDT 2023 R2's 3D Modeler COM interface has no Hide/Show and we do not
    fake it with transparency: this script only checks which names exist.
    The hidden set lives in the app and is applied as export-time Selections
    exclusion by view_capture. The user's GUI is never touched.
    """
    listed = json.dumps([str(x) for x in names], ensure_ascii=True)
    return "\n".join(
        [
            _EDITOR_VIS,
            f"want = {listed}",
            f"all_objects = {bool(all_objects)}",
            "present = all_object_names()",
            "missing = []",
            "if all_objects:",
            "    targets = list(present)",
            "else:",
            "    targets = [n for n in want if n in present]",
            "    missing = [n for n in want if n not in present]",
            "result['names'] = targets",
            "result['missing'] = missing",
            "result['objects'] = present",
        ]
    )


def view_capture_script(
    dest: Path,
    *,
    orientation: str = "isometric",
    fit: list[str] | None = None,
    isolate: list[str] | None = None,
    hidden: list[str] | None = None,
    width: int = 1280,
    height: int = 800,
) -> str:
    """IronPython: screenshot via export-time Selections (true exclusion).

    AEDT 2023 R2's 3D Modeler COM interface has no Hide/Show, so captures do
    not rely on view state at all: SaveImageParams takes `Selections` (the
    object list to render) and `FitToSelections` (frame those objects). With
    fit/isolate, only those parts render, framed tight. Without it, the
    selection is everything minus the persistent view_hide set. A tiny warm-up
    export at a different orientation runs first: the exporter can re-use a
    cached frame when nothing about the request appears to change.
    """
    keep = [str(x) for x in (fit or isolate or [])]
    hidden_names = [str(x) for x in (hidden or [])]
    warm = "top" if orientation.strip().lower() != "top" else "isometric"
    warm_path = Path(dest).resolve().with_name("view_warmup.jpg")
    return "\n".join(
        [
            "import os",
            _EDITOR_VIS,
            f"file_name = {str(Path(dest).resolve())!r}",
            f"warm_name = {str(warm_path)!r}",
            f"orientation = {orientation!r}",
            f"warm_orientation = {warm!r}",
            f"width = {int(width)}",
            f"height = {int(height)}",
            f"keep = {json.dumps(keep, ensure_ascii=True)}",
            f"hidden = {json.dumps(hidden_names, ensure_ascii=True)}",
            "parent = os.path.dirname(file_name)",
            "if parent and not os.path.isdir(parent):",
            "    os.makedirs(parent)",
            "all_names = all_object_names()",
            "missing_keep = [n for n in keep if n not in all_names]",
            "if keep:",
            "    selection = [n for n in keep if n in all_names]",
            "else:",
            "    selection = [n for n in all_names if n not in hidden]",
            "fit_sel = 'True' if selection else ''",
            "sel_text = ','.join(selection)",
            "def _params(o):",
            "    return ['NAME:SaveImageParams',",
            "            'ShowAxis:=', 'False', 'ShowGrid:=', 'False', 'ShowRuler:=', 'False',",
            "            'ShowRegion:=', 'Default',",
            "            'Selections:=', sel_text,",
            "            'FieldPlotSelections:=', '',",
            "            'FitToSelections:=', fit_sel,",
            "            'FitToFieldPlotSelections:=', '',",
            "            'Orientation:=', o,",
            "            'ShowOrientationGadget:=', 'False']",
            # ExportModelImageToFile requires >= 4 args; fewer-arg calls always fail.
            "oEditor.ExportModelImageToFile(warm_name, 64, 40, _params(warm_orientation))",
            "oEditor.ExportModelImageToFile(file_name, int(width), int(height), _params(orientation))",
            "if not os.path.isfile(file_name):",
            "    raise Exception('ExportModelImageToFile did not write ' + file_name)",
            "result['file'] = file_name",
            "result['fit'] = [n for n in keep if n in all_names]",
            "result['missing'] = missing_keep",
            "result['selection'] = selection",
            "result['objects'] = all_names",
        ]
    )

REPORT_TYPES: list[dict[str, str]] = [
    {"id": "modal_s", "kind": "curve", "export": "csv", "label": "Modal S-parameters"},
    {"id": "terminal_z", "kind": "curve", "export": "csv", "label": "Terminal Z"},
    {"id": "farfield_2d", "kind": "curve", "export": "csv", "label": "Far-field 2D cut"},
    {
        "id": "field_face",
        "kind": "field",
        "export": "image",
        "label": "Field or current on a specified face",
    },
]

# Finite FieldsReporter names. Catalog and when-to-use live in the Skill.
FIELD_QUANTITIES: dict[str, str] = {
    "Mag_E": "E Field",
    "Mag_Jsurf": "J Field",
}

DEFAULT_REPORT_NAMES = {
    "modal_s": "S11",
    "terminal_z": "Z11",
    "farfield_2d": "FarField_2D",
}

OPTIMETRICS_TYPES: list[dict[str, str]] = [
    {
        "id": "parametric",
        "label": "Optimetrics Parametric",
        "tree": "Optimetrics",
    },
]
# Safety rail against dumping the whole allowlist into one grid (e.g. 2**10).
# Not a recommended sample count. A 4-variable joint sweep can fit; a 10-way factorial cannot.
PARAMETRIC_MAX_POINTS = 256


def failure_message_for_setup(messages: list[str], setup: str) -> str | None:
    """Pick an HFSS Message Manager line that means this setup already failed."""
    needle = (setup or "").strip().lower()
    if not needle:
        return None
    for line in reversed(messages):
        low = line.lower()
        if needle not in low:
            continue
        if any(
            hint in low
            for hint in (
                "script macro error",
                "was not found",
                "not found",
                "failed",
                "error in command",
            )
        ):
            return line
    return None


def crash_message(messages: list[str]) -> str | None:
    """Engine-died lines that often omit the Optimetrics setup name."""
    for line in reversed(messages):
        low = line.lower()
        if any(
            hint in low
            for hint in (
                "not responding",
                "has been terminated",
                "engine error",
                "fatal error",
                "process was terminated",
                "solver process",
            )
        ):
            return line
    return None


def last_progress_line(messages: list[str]) -> str | None:
    if not messages:
        return None
    return messages[-1][:240]


def ensure_com() -> None:
    try:
        import pythoncom  # type: ignore

        pythoncom.CoInitialize()
    except Exception:
        pass


def parse_expression(name: str, expression: str) -> ParameterValue:
    text = str(expression).strip()
    parts = text.split()
    if len(parts) >= 2:
        try:
            return ParameterValue(name=name, value=float(parts[0]), unit=" ".join(parts[1:]))
        except ValueError:
            pass
    glued = _EXPR_GLUED.match(text)
    if glued:
        return ParameterValue(name=name, value=float(glued.group(1)), unit=glued.group(2))
    try:
        return ParameterValue(name=name, value=float(text), unit="1")
    except ValueError as exc:
        raise AdapterError(
            f"cannot parse {name}={expression!r}",
            code="variable_parse_error",
            details={"name": name, "expression": expression},
        ) from exc


def list_rot_sessions(*, version: str | None = None) -> list[dict[str, Any]]:
    ensure_com()
    client = load_win32_client()
    sessions: list[dict[str, Any]] = []
    for desktop in iter_rot_desktops(client, version):
        pid = desktop_process_id(desktop)
        try:
            projects = list_com_projects(desktop)
        except AdapterError:
            projects = []
        sessions.append(
            {
                "process_id": pid,
                "transport": "com",
                "source": "rot",
                "projects": projects,
            }
        )
    return sessions


class LiveDesign:
    """One open project/design on a COM-visible AEDT PID. Does not own the process."""

    def __init__(
        self,
        *,
        process_id: int,
        project_name: str,
        design_name: str,
        version: str | None = "2023.2",
        project_path: str | None = None,
    ) -> None:
        self.process_id = int(process_id)
        self.project_name = project_name
        self.design_name = design_name
        self.version = normalize_aedt_version(version) or "2023.2"
        self.project_path = project_path
        self._lock = threading.RLock()
        self._mutation_count = 0

    def _desktop(self) -> Any:
        ensure_com()
        desktop = get_desktop(
            version=self.version,
            process_id=self.process_id,
            create_if_missing=False,
        )
        pid = desktop_process_id(desktop)
        if pid != self.process_id:
            raise AdapterError(
                f"COM desktop PID {pid} is not the attached session {self.process_id}",
                code="aedt_pid_mismatch",
                details={"expected": self.process_id, "actual": pid},
            )
        return desktop

    def _script(self, script_text: str, *, timeout_seconds: float = 60.0) -> dict[str, Any]:
        with self._lock:
            return execute_run_script(
                project_name=self.project_name,
                design_name=self.design_name,
                script_text=script_text,
                version=self.version,
                process_id=self.process_id,
                timeout_seconds=timeout_seconds,
            )

    def snapshot(self) -> dict[str, Any]:
        raw = self._script(
            "\n".join(
                [
                    "def _names(owner):",
                    "    try:",
                    "        return [str(x) for x in (owner.GetVariables() or [])]",
                    "    except Exception:",
                    "        return []",
                    "def _items(owner, scope):",
                    "    out = []",
                    "    for name in _names(owner):",
                    "        value = ''",
                    "        try:",
                    "            value = str(owner.GetVariableValue(name))",
                    "        except Exception:",
                    "            value = ''",
                    "        out.append({'name': name, 'value': value, 'scope': scope})",
                    "    return out",
                    "setups = []",
                    "try:",
                    "    setups = [str(x) for x in (oDesign.GetModule('AnalysisSetup').GetSetups() or [])]",
                    "except Exception:",
                    "    setups = []",
                    "path = ''",
                    "try:",
                    "    path = str(oProject.GetPath() or '')",
                    "except Exception:",
                    "    path = ''",
                    "result['project_name'] = str(oProject.GetName())",
                    "result['design_name'] = str(oDesign.GetName())",
                    "result['project_dir'] = path",
                    "result['variables'] = _items(oProject, 'project') + _items(oDesign, 'design')",
                    "result['setups'] = setups",
                    "objects = []",
                    "for group in ('Solids', 'Sheets', 'Lines'):",
                    "    try:",
                    "        objects.extend([str(x) for x in (oEditor.GetObjectsInGroup(group) or [])])",
                    "    except Exception:",
                    "        pass",
                    "result['objects'] = objects",
                ]
            )
        )
        variables: dict[str, ParameterValue] = {}
        for item in raw.get("variables") or []:
            name = str(item.get("name") or "")
            if not name:
                continue
            try:
                variables[name] = parse_expression(name, str(item.get("value") or ""))
            except AdapterError:
                continue
        project_dir = str(raw.get("project_dir") or "")
        project_name = str(raw.get("project_name") or self.project_name)
        project_file = self.project_path
        if project_dir:
            project_file = str((Path(project_dir) / f"{project_name}.aedt").resolve(strict=False))
            self.project_path = project_file
        setups = [str(x) for x in (raw.get("setups") or [])]
        revision = sha256_hex(
            json.dumps(
                {
                    "n": self._mutation_count,
                    "vars": {k: {"v": v.value, "u": v.unit} for k, v in sorted(variables.items())},
                },
                sort_keys=True,
            )
        )[:16]
        return {
            "project_path": project_file,
            "project_name": project_name,
            "design_name": str(raw.get("design_name") or self.design_name),
            "revision": revision,
            "variables": {k: v.model_dump() for k, v in variables.items()},
            "setups": setups,
            "objects": [str(x) for x in (raw.get("objects") or [])],
            "process_id": self.process_id,
            "captured_at": utc_now_iso(),
        }

    def set_variables(self, items: list[ParameterValue]) -> dict[str, Any]:
        assignments = [
            {"name": item.name, "expression": f"{item.value}{item.unit}"} for item in items
        ]
        payload = json.dumps(assignments, ensure_ascii=True)
        raw = self._script(
            "\n".join(
                [
                    "import json",
                    f"assignments = json.loads({payload!r})",
                    "def _apply(owner, tab, server, name, value):",
                    "    changed = ['NAME:' + name, 'Value:=', str(value)]",
                    "    owner.ChangeProperty([",
                    "        'NAME:AllTabs',",
                    "        [",
                    "            'NAME:' + tab,",
                    "            ['NAME:PropServers', server],",
                    "            ['NAME:ChangedProps', changed],",
                    "        ],",
                    "    ])",
                    "readback = []",
                    "for item in assignments:",
                    "    name = str(item['name'])",
                    "    value = str(item['expression'])",
                    "    is_project = name.startswith('$')",
                    "    owner = oProject if is_project else oDesign",
                    "    tab = 'ProjectVariableTab' if is_project else 'LocalVariableTab'",
                    "    server = 'ProjectVariables' if is_project else 'LocalVariables'",
                    "    _apply(owner, tab, server, name, value)",
                    "    confirmed = value",
                    "    try:",
                    "        confirmed = str(owner.GetVariableValue(name))",
                    "    except Exception:",
                    "        pass",
                    "    readback.append({'name': name, 'value': confirmed})",
                    "result['readback'] = readback",
                ]
            )
        )
        self._mutation_count += 1
        readback: dict[str, ParameterValue] = {}
        for item in raw.get("readback") or []:
            name = str(item.get("name") or "")
            if not name:
                continue
            parsed = parse_expression(name, str(item.get("value") or ""))
            readback[name] = parsed
        mismatches = []
        for item in items:
            actual = readback.get(item.name)
            if actual is None or abs(actual.value - item.value) > 1e-6:
                mismatches.append(
                    {
                        "name": item.name,
                        "expected": item.value,
                        "actual": None if actual is None else actual.value,
                    }
                )
        if mismatches:
            raise AdapterError(
                "parameter read-back did not match written values",
                code="readback_mismatch",
                details={"mismatches": mismatches},
            )
        return {
            "ok": True,
            "readback": {k: v.model_dump() for k, v in readback.items()},
            "saved": False,
        }

    def analyze(self, setup: str) -> None:
        """Blocking Analyze of an HFSS Analysis Setup (Setup1, not Optimetrics)."""
        self._script(
            "\n".join(
                [
                    f"setup = {setup!r}",
                    "oDesign.Analyze(setup)",
                    "result['setup'] = setup",
                    "result['ok'] = True",
                ]
            ),
            timeout_seconds=7200.0,
        )

    def analyze_parametric(self, name: str) -> None:
        """Blocking Optimetrics SolveSetup. oDesign.Analyze cannot see this node."""
        self._script(
            "\n".join(
                [
                    f"name = {name!r}",
                    "opt = oDesign.GetModule('Optimetrics')",
                    "names = []",
                    "try:",
                    "    names = [str(x) for x in (opt.GetSetupNames() or [])]",
                    "except Exception:",
                    "    names = []",
                    "if name not in names:",
                    "    raise Exception('Optimetrics setup ' + name + ' is not in the tree')",
                    "opt.SolveSetup(name)",
                    "result['setup'] = name",
                    "result['ok'] = True",
                ]
            ),
            timeout_seconds=7200.0,
        )

    def read_messages(self, *, limit: int = 24) -> list[str]:
        """Message Manager lines via direct COM. Does not take the RunScript lock."""
        ensure_com()
        desktop = get_desktop(
            version=self.version,
            process_id=self.process_id,
            create_if_missing=False,
        )
        project = self.project_name or ""
        design = self.design_name or ""
        raw: Any = None
        for args in (
            (project, design, 0),
            (project, design, 1),
            ("", "", 0),
            ("", "", True),
        ):
            try:
                raw = desktop.GetMessages(*args)
                if raw is not None:
                    break
            except Exception:
                continue
        if raw is None:
            return []
        if isinstance(raw, str):
            lines = [raw]
        else:
            try:
                lines = [str(item) for item in raw]
            except TypeError:
                lines = [str(raw)]
        cleaned = [line.strip() for line in lines if str(line).strip()]
        return cleaned[-max(int(limit), 1) :]

    def list_optimetrics(self) -> list[dict[str, Any]]:
        """Setups currently under Optimetrics. What a human can see in that tree."""
        raw = self._script(
            "\n".join(
                [
                    "opt = oDesign.GetModule('Optimetrics')",
                    "names = []",
                    "try:",
                    "    names = [str(x) for x in (opt.GetSetupNames() or [])]",
                    "except Exception:",
                    "    names = []",
                    "items = []",
                    "for name in names:",
                    "    item = {'name': name, 'tree': 'Optimetrics'}",
                    "    try:",
                    "        obj = opt.GetChildObject(name)",
                    "        props = [str(x) for x in (obj.GetPropNames() or [])]",
                    "        item['properties'] = props",
                    "        if 'Enabled' in props:",
                    "            item['enabled'] = bool(obj.GetPropValue('Enabled'))",
                    "        if 'HasResult' in props:",
                    "            item['has_result'] = bool(obj.GetPropValue('HasResult'))",
                    "        if 'IncludedVariables' in props:",
                    "            item['variables'] = [str(x) for x in (obj.GetPropValue('IncludedVariables') or [])]",
                    "            item['setup_kind'] = 'parametric'",
                    "        else:",
                    "            item['setup_kind'] = 'unsupported'",
                    "    except Exception:",
                    "        item['setup_kind'] = 'unknown'",
                    "    items.append(item)",
                    "result['setups'] = items",
                ]
            )
        )
        setups = raw.get("setups") or []
        return [item for item in setups if isinstance(item, dict)]

    def create_parametric(
        self,
        *,
        name: str,
        sim_setup: str,
        sweeps: list[dict[str, str]],
        sync_indices: list[int] | None = None,
    ) -> dict[str, Any]:
        """Insert or edit an OptiParametric setup under Optimetrics. Never delete.

        ``sync_indices`` (e.g. ``[0, 1, 2]``) asks HFSS to zip those sweeps
        instead of taking their Cartesian product — used for explicit point tables.
        """
        existing_names = {str(item.get("name") or "") for item in self.list_optimetrics()}
        reused = name in existing_names
        sweep_parts = []
        for item in sweeps:
            sweep_parts.append(
                "["
                + "'NAME:SweepDefinition', "
                + f"'Variable:=', {item['variable']!r}, "
                + f"'Data:=', {item['data']!r}, "
                + "'OffsetF1:=', False, 'Synchronize:=', 0"
                + "]"
            )
        sweeps_literal = "[" + ", ".join(sweep_parts) + "]"
        sync = [int(x) for x in (sync_indices or [])]
        if len(sync) >= 2:
            sweep_ops = f"['NAME:Sweep Operations', 'Sync:=', {sync!r}]"
        else:
            sweep_ops = "['NAME:Sweep Operations']"
        raw = self._script(
            "\n".join(
                [
                    f"name = {name!r}",
                    f"sim_setup = {sim_setup!r}",
                    f"sweep_defs = {sweeps_literal}",
                    f"sweep_ops = {sweep_ops}",
                    f"reused = {reused!r}",
                    "opt = oDesign.GetModule('Optimetrics')",
                    "arg = [",
                    "    'NAME:' + name,",
                    "    'IsEnabled:=', True,",
                    "    ['NAME:ProdOptiSetupDataV2', 'SaveFields:=', False, 'CopyMesh:=', False, 'SolveWithCopiedMeshOnly:=', True],",
                    "    ['NAME:StartingPoint'],",
                    "    'Sim. Setups:=', [sim_setup],",
                    "    ['NAME:Sweeps'] + sweep_defs,",
                    "    sweep_ops,",
                    "    ['NAME:Goals'],",
                    "]",
                    "if reused:",
                    "    opt.EditSetup(name, arg)",
                    "else:",
                    "    opt.InsertSetup('OptiParametric', arg)",
                    "still = [str(x) for x in (opt.GetSetupNames() or [])]",
                    "if name not in still:",
                    "    raise Exception('parametric ' + name + ' is not under Optimetrics')",
                    "result['name'] = name",
                    "result['created'] = not reused",
                    "result['reused'] = reused",
                    "result['edited'] = reused",
                ]
            )
        )
        return {
            "name": str(raw.get("name") or name),
            "created": bool(raw.get("created")),
            "reused": bool(raw.get("reused")),
            "edited": bool(raw.get("edited")),
            "tree": "Optimetrics",
            "setup_kind": "parametric",
            "sim_setup": sim_setup,
            "sweeps": sweeps,
            "sync_indices": sync,
        }

    def export_parametric_table(self, name: str, dest: Path) -> Path:
        """Export the Optimetrics parametric sweep table. Same table a human exports."""
        existing = {str(item.get("name") or "") for item in self.list_optimetrics()}
        if name not in existing:
            raise AdapterError(
                f"parametric {name!r} is not under Optimetrics; create it first",
                code="report_not_in_results",
                details={"name": name, "optimetrics": sorted(existing)},
            )
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    f"name = {name!r}",
                    f"dest = {str(dest)!r}",
                    "parent = os.path.dirname(dest)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "opt = oDesign.GetModule('Optimetrics')",
                    "opt.ExportParametricSetupTable(name, dest)",
                    "if not os.path.isfile(dest):",
                    "    raise Exception('ExportParametricSetupTable did not write ' + dest)",
                    "result['path'] = dest",
                ]
            )
        )
        path = Path(str(raw.get("path") or dest))
        if not path.is_file():
            raise AdapterError(
                f"parametric table was not written for {name!r}",
                code="parametric_export_failed",
            )
        return path

    def list_reports(self) -> list[dict[str, Any]]:
        """Names currently under Results. What a human can see in the project tree."""
        raw = self._script(
            "\n".join(
                [
                    "report_module = oDesign.GetModule('ReportSetup')",
                    "names = []",
                    "try:",
                    "    names = [str(x) for x in (report_module.GetAllReportNames() or [])]",
                    "except Exception:",
                    "    names = []",
                    "items = []",
                    "for name in names:",
                    "    item = {'name': name, 'report_id': name, 'in_results': True, 'tree': 'Results'}",
                    "    for method, key in (('GetReportType', 'category'), ('GetDisplayType', 'display_type')):",
                    "        try:",
                    "            item[key] = str(getattr(report_module, method)(name))",
                    "        except Exception:",
                    "            pass",
                    "    try:",
                    "        traces = report_module.GetTraceNames(name)",
                    "        item['traces'] = [str(t) for t in (traces or [])]",
                    "    except Exception:",
                    "        pass",
                    "    items.append(item)",
                    "try:",
                    "    fields_mod = oDesign.GetModule('FieldsReporter')",
                    "    field_names = [str(x) for x in (fields_mod.GetFieldPlotNames() or [])]",
                    "except Exception:",
                    "    field_names = []",
                    "for name in field_names:",
                    "    items.append({'name': name, 'report_id': name, 'in_results': False, 'tree': 'Field Overlays', 'report_type': 'field_face'})",
                    "result['reports'] = items",
                ]
            )
        )
        reports = raw.get("reports") or []
        return [item for item in reports if isinstance(item, dict)]

    def create_results_report(
        self,
        *,
        report_type: str,
        name: str,
        setup: str,
        sweep: str | None,
        frequency: str | None = None,
        family_variables: list[str] | None = None,
        nominal_variables: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a plot under Results if missing. Never delete an existing report.

        family_variables become All; other known parametric vars become Nominal
        so later Optimetrics rounds do not leak into the plot. CreateReport
        failures are raised — there is no silent Freq-only fallback.
        """
        if report_type not in DEFAULT_REPORT_NAMES:
            raise AdapterError(
                f"cannot create Results report of type {report_type!r}",
                code="report_type_unknown",
            )
        preferred = f"{setup} : {sweep}" if sweep else f"{setup} : LastAdaptive"
        freq = frequency or "All"
        family = [str(v) for v in (family_variables or []) if str(v).strip()]
        nominal = [
            str(v)
            for v in (nominal_variables or [])
            if str(v).strip() and str(v).strip() not in family
        ]
        existing_names = {str(item.get("name") or "") for item in self.list_reports()}
        if name in existing_names:
            if family or nominal:
                raise AdapterError(
                    f"report {name!r} already exists; pick a new name to apply "
                    "families or Nominal pins",
                    code="report_exists",
                    details={"name": name},
                )
            return {
                "name": name,
                "report_id": name,
                "report_type": report_type,
                "created": False,
                "reused": True,
                "in_results": True,
                "setup": setup,
                "sweep": sweep,
                "frequency": frequency,
                "family_variables": family,
                "nominal_variables": nominal,
                "families_applied": False,
            }
        family_payload = json.dumps(family, ensure_ascii=True)
        nominal_payload = json.dumps(nominal, ensure_ascii=True)
        raw = self._script(
            "\n".join(
                [
                    "import json",
                    f"report_name = {name!r}",
                    f"report_type = {report_type!r}",
                    f"preferred = {preferred!r}",
                    f"setup = {setup!r}",
                    f"freq = {freq!r}",
                    f"family_vars = json.loads({family_payload!r})",
                    f"nominal_vars = json.loads({nominal_payload!r})",
                    "variation = ['Freq:=', ['All']]",
                    "for var in family_vars:",
                    "    variation += [str(var) + ':=', ['All']]",
                    "for var in nominal_vars:",
                    "    if var not in family_vars:",
                    "        variation += [str(var) + ':=', ['Nominal']]",
                    "families_applied = bool(family_vars)",
                    "report_module = oDesign.GetModule('ReportSetup')",
                    "existing = []",
                    "try:",
                    "    existing = [str(x) for x in (report_module.GetAllReportNames() or [])]",
                    "except Exception:",
                    "    existing = []",
                    "if report_name in existing:",
                    "    raise Exception('report ' + report_name + ' already exists; pick a new name')",
                    "solutions = []",
                    "category = 'Modal Solution Data'",
                    "if report_type == 'modal_s':",
                    "    category = 'Modal Solution Data'",
                    "elif report_type == 'terminal_z':",
                    "    category = 'Terminal Solution Data'",
                    "elif report_type == 'farfield_2d':",
                    "    category = 'Far Fields'",
                    "try:",
                    "    solutions = [str(x) for x in (report_module.GetAvailableSolutions(category) or [])]",
                    "except Exception:",
                    "    solutions = []",
                    "candidates = [preferred, setup + ' : LastAdaptive', setup]",
                    "setup_solution = preferred",
                    "for cand in candidates:",
                    "    if (not solutions) or (cand in solutions):",
                    "        setup_solution = cand",
                    "        break",
                    "if solutions and setup_solution not in solutions:",
                    "    setup_solution = solutions[0]",
                    "created = False",
                    "errors = []",
                    "if report_type == 'modal_s':",
                    "    try:",
                    "        report_module.CreateReport(report_name, 'Modal Solution Data', 'Rectangular Plot', setup_solution, ['Domain:=', 'Sweep'], variation, ['X Component:=', 'Freq', 'Y Component:=', ['dB(S(1,1))']])",
                    "        created = True",
                    "    except Exception as error:",
                    "        errors.append(str(error))",
                    "elif report_type == 'terminal_z':",
                    "    attempts = [('Terminal Solution Data', ['re(Zt(1,1))', 'im(Zt(1,1))']), ('Terminal Solution Data', ['re(Z(1,1))', 'im(Z(1,1))']), ('Modal Solution Data', ['re(Z(1,1))', 'im(Z(1,1))'])]",
                    "    for category, exprs in attempts:",
                    "        try:",
                    "            report_module.CreateReport(report_name, category, 'Rectangular Plot', setup_solution, ['Domain:=', 'Sweep'], variation, ['X Component:=', 'Freq', 'Y Component:=', exprs])",
                    "            created = True",
                    "            break",
                    "        except Exception as error:",
                    "            errors.append(str(error))",
                    "elif report_type == 'farfield_2d':",
                    "    spheres = []",
                    "    try:",
                    "        rad = oDesign.GetModule('RadField')",
                    "        for args in (('Infinite Sphere',), ()):",
                    "            try:",
                    "                spheres = [str(x) for x in (rad.GetSetupNames(*args) or [])]",
                    "                if spheres:",
                    "                    break",
                    "            except Exception:",
                    "                pass",
                    "    except Exception:",
                    "        spheres = []",
                    "    if not spheres:",
                    "        raise Exception('No infinite sphere / far-field setup on this design')",
                    "    ff_solutions = []",
                    "    try:",
                    "        ff_solutions = [str(x) for x in (report_module.GetAvailableSolutions('Far Fields') or [])]",
                    "    except Exception:",
                    "        ff_solutions = []",
                    "    ff_setup = preferred",
                    "    if ff_solutions and preferred not in ff_solutions:",
                    "        adaptive = [s for s in ff_solutions if 'LastAdaptive' in s]",
                    "        ff_setup = adaptive[0] if adaptive else ff_solutions[0]",
                    "    variation = ['Theta:=', ['All'], 'Phi:=', ['0deg'], 'Freq:=', [freq]]",
                    "    for sphere in spheres:",
                    "        context = ['Context:=', sphere]",
                    "        for expression in ['dB(GainTotal)', 'GainTotal', 'dB(RealizedGainTotal)']:",
                    "            try:",
                    "                report_module.CreateReport(report_name, 'Far Fields', 'Rectangular Plot', ff_setup, context, variation, ['X Component:=', 'Theta', 'Y Component:=', [expression]])",
                    "                created = True",
                    "                break",
                    "            except Exception as error:",
                    "                errors.append(str(error))",
                    "        if created:",
                    "            break",
                    "if not created:",
                    "    raise Exception('CreateReport failed for ' + report_name + ': ' + '; '.join(errors))",
                    "still = []",
                    "try:",
                    "    still = [str(x) for x in (report_module.GetAllReportNames() or [])]",
                    "except Exception:",
                    "    still = []",
                    "if report_name not in still:",
                    "    raise Exception('report ' + report_name + ' was created but is not under Results')",
                    "result['name'] = report_name",
                    "result['created'] = True",
                    "result['reused'] = False",
                    "result['in_results'] = True",
                    "result['families_applied'] = families_applied",
                    "result['family_variables'] = family_vars",
                    "result['nominal_variables'] = nominal_vars",
                ]
            )
        )
        return {
            "name": str(raw.get("name") or name),
            "report_id": str(raw.get("name") or name),
            "report_type": report_type,
            "created": bool(raw.get("created")),
            "reused": False,
            "in_results": True,
            "setup": setup,
            "sweep": sweep,
            "frequency": frequency,
            "family_variables": family,
            "nominal_variables": nominal,
            "families_applied": bool(raw.get("families_applied")),
        }

    def export_results_report(
        self,
        name: str,
        dest: Path,
        *,
        report_type: str | None = None,
    ) -> Path:
        """ExportToFile a report that already exists under Results. No network-data bypass.

        The 3rd argument is the GUI "Separate Columns for Curves" checkbox.
        False matches right-click Export Data with that box unchecked: one
        column per swept variable, then Freq, then the quantity.
        """
        existing = {str(item.get("name") or "") for item in self.list_reports()}
        if name not in existing:
            raise AdapterError(
                f"report {name!r} is not under Results; create it first",
                code="report_not_in_results",
                details={"name": name, "results": sorted(existing)},
            )
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    f"report_name = {name!r}",
                    f"output_csv = {str(dest)!r}",
                    "parent = os.path.dirname(output_csv)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "report_module = oDesign.GetModule('ReportSetup')",
                    "exported = False",
                    "last = ''",
                    "for args_tuple in ((report_name, output_csv, False), (report_name, output_csv)):",
                    "    try:",
                    "        report_module.ExportToFile(*args_tuple)",
                    "        if os.path.isfile(output_csv):",
                    "            exported = True",
                    "            break",
                    "    except Exception as error:",
                    "        last = str(error)",
                    "if not exported:",
                    "    raise Exception(last or ('ExportToFile failed for ' + report_name))",
                    "trace_names = []",
                    "try:",
                    "    raw_traces = report_module.GetTraceNames(report_name)",
                    "    if raw_traces is None:",
                    "        raw_traces = []",
                    "    elif isinstance(raw_traces, str):",
                    "        raw_traces = [raw_traces]",
                    "    else:",
                    "        raw_traces = list(raw_traces)",
                    "    trace_names = [str(t) for t in raw_traces]",
                    "except Exception:",
                    "    trace_names = []",
                    "result['path'] = output_csv",
                    "result['trace_names'] = trace_names",
                ]
            )
        )
        path = Path(str(raw.get("path") or dest))
        if not path.is_file():
            raise AdapterError(
                f"report CSV was not written for {name!r}",
                code="report_export_failed",
            )
        names = raw.get("trace_names") or []
        if not isinstance(names, list):
            names = [names]
        return normalize_exported_report_csv(
            path,
            report_type,
            trace_names=[str(item) for item in names],
        )

    def create_field_overlay(
        self,
        *,
        name: str,
        face: str,
        frequency: str,
        setup: str,
        sweep: str | None = None,
        quantity: str = "Mag_E",
    ) -> dict[str, Any]:
        """Create a Field Overlays plot the user can see. Reuse the name if it exists."""
        folder = FIELD_QUANTITIES.get(quantity, "E Field")
        preferred = f"{setup} : {sweep}" if sweep else f"{setup} : LastAdaptive"
        raw = self._script(
            "\n".join(
                [
                    f"plot_name = {name!r}",
                    f"face = {face!r}",
                    f"freq = {frequency!r}",
                    f"quantity = {quantity!r}",
                    f"plot_folder = {folder!r}",
                    f"preferred = {preferred!r}",
                    "fields = oDesign.GetModule('FieldsReporter')",
                    "existing = []",
                    "try:",
                    "    existing = [str(x) for x in (fields.GetFieldPlotNames() or [])]",
                    "except Exception:",
                    "    existing = []",
                    "if plot_name in existing:",
                    "    result['name'] = plot_name",
                    "    result['created'] = False",
                    "    result['reused'] = True",
                    "else:",
                    "    face_ids = []",
                    "    obj_name = face",
                    "    try:",
                    "        face_ids = [int(face)]",
                    "        obj_name = ''",
                    "    except Exception:",
                    "        face_ids = []",
                    "        try:",
                    "            face_ids = [int(x) for x in (oEditor.GetFaceIDs(face) or [])]",
                    "        except Exception:",
                    "            face_ids = []",
                    "    intrinsic = \"Freq='\" + freq + \"' Phase='0deg'\"",
                    "    geoms = []",
                    "    if face_ids:",
                    "        geoms.append([1, 'Surface', 'FacesList', 1, int(face_ids[0])])",
                    "        geoms.append([1, 'Surface', 'FacesList', len(face_ids)] + [int(x) for x in face_ids])",
                    "    if obj_name:",
                    "        geoms.append([1, 'Surface', 'Objects', 1, obj_name])",
                    "        geoms.append([1, 'Surface', 'Objects', [obj_name]])",
                    "    if not geoms:",
                    "        raise Exception('cannot resolve face/object ' + face)",
                    "    solutions = [preferred, preferred.split(' : ')[0] + ' : LastAdaptive']",
                    "    created = False",
                    "    errors = []",
                    "    used_solution = preferred",
                    "    for sol in solutions:",
                    "        for geom in geoms:",
                    "            payload = [",
                    "                'NAME:' + plot_name,",
                    "                'SolutionName:=', sol,",
                    "                'UserSpecifyName:=', 1,",
                    "                'UserSpecifyFolder:=', 0,",
                    "                'QuantityName:=', quantity,",
                    "                'PlotFolder:=', plot_folder,",
                    "                'StreamlinePlot:=', False,",
                    "                'AdjacentSidePlot:=', False,",
                    "                'FullModelPlot:=', False,",
                    "                'IntrinsicVar:=', intrinsic,",
                    "                'PlotGeomInfo:=', geom,",
                    "                'FilterOn:=', False,",
                    "                'UseFilterColor:=', False,",
                    "            ]",
                    "            try:",
                    "                fields.CreateFieldPlot(payload, 'Field')",
                    "                created = True",
                    "                used_solution = sol",
                    "                break",
                    "            except Exception as error:",
                    "                errors.append(str(error))",
                    "                try:",
                    "                    fields.DeleteFieldPlot([plot_name])",
                    "                except Exception:",
                    "                    pass",
                    "        if created:",
                    "            break",
                    "    if not created:",
                    "        raise Exception('Field overlay ' + plot_name + ' failed. Need a solved field at this frequency. ' + '; '.join(errors[:6]))",
                    "    still = []",
                    "    try:",
                    "        still = [str(x) for x in (fields.GetFieldPlotNames() or [])]",
                    "    except Exception:",
                    "        still = []",
                    "    if plot_name not in still:",
                    "        raise Exception('field overlay ' + plot_name + ' was created but is not under Field Overlays')",
                    "    result['name'] = plot_name",
                    "    result['created'] = True",
                    "    result['reused'] = False",
                    "    result['solution'] = used_solution",
                ]
            ),
            timeout_seconds=120.0,
        )
        return {
            "name": str(raw.get("name") or name),
            "report_id": str(raw.get("name") or name),
            "report_type": "field_face",
            "created": bool(raw.get("created")),
            "reused": bool(raw.get("reused")),
            "in_results": False,
            "tree": "Field Overlays",
            "face": face,
            "frequency": frequency,
            "quantity": quantity,
            "setup": setup,
            "sweep": sweep,
        }

    def export_field_overlay(self, name: str, dest: Path) -> Path:
        """Export an existing Field Overlays plot. No modeler-screenshot fallback."""
        existing = {
            str(item.get("name") or "")
            for item in self.list_reports()
            if item.get("tree") == "Field Overlays" or item.get("report_type") == "field_face"
        }
        if name not in existing:
            raise AdapterError(
                f"field overlay {name!r} is not under Field Overlays; create it first",
                code="report_not_in_results",
                details={"name": name, "overlays": sorted(existing)},
            )
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    f"plot_name = {name!r}",
                    f"file_name = {str(dest)!r}",
                    "folder = os.path.dirname(file_name)",
                    "if folder and not os.path.isdir(folder):",
                    "    os.makedirs(folder)",
                    "fields = oDesign.GetModule('FieldsReporter')",
                    "exported = False",
                    "last = ''",
                    "try:",
                    "    fields.ExportFieldPlot(plot_name, folder, 'jpg')",
                    "    candidate = os.path.join(folder, plot_name + '.jpg')",
                    "    if os.path.isfile(candidate):",
                    "        if candidate != file_name:",
                    "            if os.path.isfile(file_name):",
                    "                try:",
                    "                    os.remove(file_name)",
                    "                except Exception:",
                    "                    pass",
                    "            os.rename(candidate, file_name)",
                    "        exported = os.path.isfile(file_name)",
                    "except Exception as error:",
                    "    last = str(error)",
                    "if not exported:",
                    "    raise Exception(last or ('ExportFieldPlot failed for ' + plot_name + '; the overlay must be visible under Field Overlays'))",
                    "result['file'] = file_name",
                ]
            ),
            timeout_seconds=120.0,
        )
        path = Path(str(raw.get("file") or dest))
        if not path.is_file():
            raise AdapterError(
                "field overlay image was not written",
                code="field_face_export_failed",
            )
        return path

    def view_set_visible(
        self,
        names: list[str],
        *,
        show: bool,
        all_objects: bool = False,
    ) -> dict[str, Any]:
        raw = self._script(
            view_visibility_script(names=names, show=show, all_objects=all_objects)
        )
        return {
            "names": [str(x) for x in (raw.get("names") or [])],
            "missing": [str(x) for x in (raw.get("missing") or [])],
            "objects": [str(x) for x in (raw.get("objects") or [])],
        }

    def view_capture(
        self,
        dest: Path,
        *,
        orientation: str = "isometric",
        fit: list[str] | None = None,
        isolate: list[str] | None = None,
        hidden: list[str] | None = None,
        width: int = 1280,
        height: int = 800,
    ) -> tuple[Path, list[str], list[str], list[str]]:
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = self._script(
            view_capture_script(
                dest,
                orientation=orientation,
                fit=fit,
                isolate=isolate,
                hidden=hidden,
                width=width,
                height=height,
            )
        )
        path = Path(str(raw.get("file") or dest))
        selection = [str(x) for x in (raw.get("selection") or [])]
        fitted = [str(x) for x in (raw.get("fit") or [])]
        missing = [str(x) for x in (raw.get("missing") or [])]
        if not path.is_file():
            raise AdapterError("view capture did not write a file", code="view_capture_failed")
        return path, selection, fitted, missing

    def variable_map(self, names: list[str] | None = None) -> dict[str, Any]:
        raw = self._script(
            "\n".join(
                [
                    "def _names(owner):",
                    "    try:",
                    "        return [str(x) for x in (owner.GetVariables() or [])]",
                    "    except Exception:",
                    "        return []",
                    "def _expr(owner, name):",
                    "    try:",
                    "        return str(owner.GetVariableValue(name))",
                    "    except Exception:",
                    "        return ''",
                    "known = _names(oProject) + _names(oDesign)",
                    "defs = []",
                    "for name in _names(oProject):",
                    "    defs.append({'name': name, 'scope': 'project', 'expression': _expr(oProject, name)})",
                    "for name in _names(oDesign):",
                    "    defs.append({'name': name, 'scope': 'design', 'expression': _expr(oDesign, name)})",
                    "objects = []",
                    "for group in ('Solids', 'Sheets', 'Lines'):",
                    "    try:",
                    "        objects.extend([str(x) for x in (oEditor.GetObjectsInGroup(group) or [])])",
                    "    except Exception:",
                    "        pass",
                    "usages = []",
                    "for obj in objects:",
                    "    props = {}",
                    "    try:",
                    "        for key in (oEditor.GetProperties('Geometry3DAttributeTab', obj) or []):",
                    "            try:",
                    "                props[str(key)] = str(oEditor.GetPropertyValue('Geometry3DAttributeTab', obj, key))",
                    "            except Exception:",
                    "                pass",
                    "    except Exception:",
                    "        pass",
                    "    try:",
                    "        for key in (oEditor.GetProperties('Geometry3DCmdTab', obj) or []):",
                    "            try:",
                    "                props[str(key)] = str(oEditor.GetPropertyValue('Geometry3DCmdTab', obj, key))",
                    "            except Exception:",
                    "                pass",
                    "    except Exception:",
                    "        pass",
                    "    usages.append({'object': obj, 'properties': props})",
                    "result['definitions'] = defs",
                    "result['object_properties'] = usages",
                    "result['known'] = known",
                ]
            ),
            timeout_seconds=120.0,
        )
        known = {str(x) for x in (raw.get("known") or [])}
        wanted = set(names) if names else known
        definitions = []
        for item in raw.get("definitions") or []:
            name = str(item.get("name") or "")
            expr = str(item.get("expression") or "")
            depends = sorted(
                token for token in set(_VAR_TOKEN.findall(expr)) if token in known and token != name
            )
            definitions.append({**item, "depends_on": depends})
        by_var: dict[str, list[dict[str, str]]] = {name: [] for name in wanted}
        for entry in raw.get("object_properties") or []:
            obj = str(entry.get("object") or "")
            props = entry.get("properties") or {}
            if not isinstance(props, dict):
                continue
            for key, value in props.items():
                text = str(value)
                for token in set(_VAR_TOKEN.findall(text)):
                    if token in wanted:
                        by_var.setdefault(token, []).append(
                            {"object": obj, "property": str(key), "expression": text}
                        )
        for item in definitions:
            name = str(item.get("name") or "")
            for dep in item.get("depends_on") or []:
                if dep in wanted:
                    by_var.setdefault(str(dep), []).append(
                        {
                            "object": "",
                            "property": f"variable:{name}",
                            "expression": str(item.get("expression") or ""),
                        }
                    )
        return {
            "definitions": definitions,
            "usages": {k: v for k, v in by_var.items() if k in wanted},
        }

    def save(self) -> dict[str, Any]:
        raw = self._script(
            "\n".join(
                [
                    "oProject.Save()",
                    "result['saved'] = True",
                    "result['mode'] = 'save'",
                    "try:",
                    "    result['project_name'] = str(oProject.GetName())",
                    "    result['project_dir'] = str(oProject.GetPath() or '')",
                    "except Exception:",
                    "    result['project_name'] = ''",
                    "    result['project_dir'] = ''",
                ]
            )
        )
        return raw

    def save_as(self, dest: Path) -> dict[str, Any]:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = self._script(
            "\n".join(
                [
                    f"dest = {str(dest)!r}",
                    "oProject.SaveAs(dest, True)",
                    "result['saved'] = True",
                    "result['mode'] = 'save_as'",
                    "result['path'] = dest",
                    "try:",
                    "    result['project_name'] = str(oProject.GetName())",
                    "except Exception:",
                    "    result['project_name'] = ''",
                ]
            )
        )
        new_name = str(raw.get("project_name") or dest.stem)
        self.project_name = new_name
        self.project_path = str(dest)
        return raw


def attach_live(
    *,
    version: str | None = "2023.2",
    process_id: int | None = None,
    project_name: str | None = None,
    design_name: str | None = None,
    project_path: str | None = None,
) -> LiveDesign:
    """Attach to an already-running COM-visible Desktop. Never starts a new one."""
    ensure_com()
    sessions = list_rot_sessions(version=version)
    if not sessions:
        raise AdapterError(
            "No COM-visible AEDT Desktop is running. Start Electronics Desktop "
            "and keep the project open, then retry. This server will not launch a second Desktop.",
            code="aedt_not_running",
        )
    chosen = None
    if process_id:
        for sess in sessions:
            if int(sess["process_id"]) == int(process_id):
                chosen = sess
                break
        if chosen is None:
            raise AdapterError(
                f"No COM-visible Desktop for PID {process_id}",
                code="aedt_pid_unreachable",
                details={"process_id": process_id, "visible": [s["process_id"] for s in sessions]},
            )
    else:
        chosen = sessions[0]
        if len(sessions) > 1 and not project_name and not project_path:
            raise AdapterError(
                "Multiple AEDT sessions are visible; pass process_id or project_name",
                code="aedt_session_ambiguous",
                details={"sessions": sessions},
            )

    pid = int(chosen["process_id"])
    projects = list(chosen.get("projects") or [])
    target_name = project_name
    if not target_name and project_path:
        target_name = Path(project_path).stem

    match = None
    if target_name:
        for item in projects:
            if str(item.get("project_name") or "").lower() == target_name.lower():
                match = item
                break
        if match is None and project_path and Path(project_path).is_file():
            desktop = get_desktop(version=version, process_id=pid, create_if_missing=False)
            opened = open_project_on_desktop(desktop, Path(project_path), design_name or "")
            match = opened
            target_name = str(opened.get("project_name") or target_name)
        if match is None:
            raise AdapterError(
                f"Project {target_name!r} is not open in AEDT PID {pid}",
                code="project_not_open",
                details={
                    "project_name": target_name,
                    "open_projects": [p.get("project_name") for p in projects],
                },
            )
    else:
        active = next((p for p in projects if p.get("is_active_project")), None)
        match = active or (projects[0] if projects else None)
        if match is None:
            raise AdapterError(
                "AEDT is running but no project is open",
                code="no_open_project",
                details={"process_id": pid},
            )
        target_name = str(match.get("project_name") or "")

    designs = [str(x) for x in (match.get("designs") or [])]
    chosen_design = design_name
    if chosen_design:
        if designs and chosen_design not in designs:
            # Some GetTopDesignList values include type prefixes; allow suffix match
            lowered = chosen_design.lower()
            hit = next((d for d in designs if d.lower() == lowered or d.lower().endswith(lowered)), None)
            if hit is None:
                raise AdapterError(
                    f"Design {chosen_design!r} is not in project {target_name}",
                    code="design_not_found",
                    details={"design_name": chosen_design, "designs": designs},
                )
            chosen_design = hit
    else:
        chosen_design = str(match.get("design") or match.get("active_design") or (designs[0] if designs else ""))
    if not chosen_design:
        raise AdapterError(
            "No design is open; open an HFSS design in the GUI (this tool will not insert one)",
            code="no_open_design",
            details={"project_name": target_name},
        )

    path = match.get("project_file") or match.get("project_path")
    return LiveDesign(
        process_id=pid,
        project_name=str(target_name),
        design_name=str(chosen_design),
        version=version,
        project_path=str(path) if path else project_path,
    )
