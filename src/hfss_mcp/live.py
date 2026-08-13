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
from hfss_mcp.metrics import parse_touchstone_s11_db, parse_touchstone_z11

_EXPR_GLUED = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z_%µμ]+)$"
)
_VAR_TOKEN = re.compile(r"\$?[A-Za-z_][\w$]*")

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
        self._reports: dict[str, dict[str, Any]] = {}

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
        """Blocking Analyze on the live design. Call from a worker thread."""
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

    def _export_network_touchstone(
        self, *, setup: str, sweep: str | None, dest: Path, data_type: str
    ) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        suffix = ".s1p" if data_type.upper() == "S" else ".z1p"
        ts = dest.with_suffix(suffix)
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    f"dest = {str(ts)!r}",
                    f"setup = {setup!r}",
                    f"sweep = {json.dumps(sweep)}",
                    f"data_type = {data_type!r}",
                    "parent = os.path.dirname(dest)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "sol = oDesign.GetModule('Solutions')",
                    "name = (setup + ':' + sweep) if sweep else setup",
                    "alt = (setup + ' : ' + sweep) if sweep else setup",
                    "adaptive = setup + ' : LastAdaptive'",
                    "last = ''",
                    "ok = False",
                    "for solution in (name, alt, adaptive, setup):",
                    "    try:",
                    "        sol.ExportNetworkData('', [solution], 3, dest, ['All'], True, 50, data_type, -1, 0, 15, True, False, False)",
                    "        ok = True",
                    "        break",
                    "    except Exception as error:",
                    "        last = str(error)",
                    "if not ok:",
                    "    raise Exception(last or 'ExportNetworkData failed')",
                    "result['path'] = dest",
                    "result['exists'] = os.path.isfile(dest)",
                ]
            )
        )
        path = Path(str(raw.get("path") or ts))
        if not path.is_file():
            raise AdapterError("Touchstone export missing", code="touchstone_missing")
        return path

    def export_modal_s_csv(self, *, setup: str, sweep: str | None, dest: Path) -> Path:
        dest = Path(dest)
        ts = self._export_network_touchstone(
            setup=setup, sweep=sweep, dest=dest, data_type="S"
        )
        freqs, vals = parse_touchstone_s11_db(ts)
        dest.write_text(
            "freq_ghz,s11_db\n"
            + "\n".join(f"{f:.6g},{v:.6g}" for f, v in zip(freqs, vals, strict=False))
            + "\n",
            encoding="utf-8",
        )
        return dest

    def export_terminal_z_csv(self, *, setup: str, sweep: str | None, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            ts = self._export_network_touchstone(
                setup=setup, sweep=sweep, dest=dest, data_type="Z"
            )
            freqs, reals, imags = parse_touchstone_z11(ts)
            dest.write_text(
                "freq_ghz,re,im\n"
                + "\n".join(
                    f"{f:.6g},{r:.6g},{i:.6g}"
                    for f, r, i in zip(freqs, reals, imags, strict=False)
                )
                + "\n",
                encoding="utf-8",
            )
            return dest
        except AdapterError:
            pass
        solution = f"{setup} : {sweep}" if sweep else f"{setup} : LastAdaptive"
        expressions = json.dumps(
            ["re(Z(1,1))", "im(Z(1,1))", "mag(Z(1,1))", "re(Zt(1,1))", "im(Zt(1,1))"]
        )
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    "report_name = 'hfss_mcp_terminal_z'",
                    f"setup_solution = {solution!r}",
                    f"output_csv = {str(dest)!r}",
                    f"expressions = {expressions}",
                    "parent = os.path.dirname(output_csv)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "report_module = oDesign.GetModule('ReportSetup')",
                    "try:",
                    "    report_module.DeleteReports([report_name])",
                    "except Exception:",
                    "    pass",
                    "categories = ['Terminal Solution Data', 'Modal Solution Data']",
                    "created = False",
                    "errors = []",
                    "for category in categories:",
                    "    for expression in expressions:",
                    "        try:",
                    "            report_module.CreateReport(report_name, category, 'Rectangular Plot', setup_solution, ['Domain:=', 'Sweep'], ['Freq:=', ['All']], ['X Component:=', 'Freq', 'Y Component:=', [expression]])",
                    "            created = True",
                    "            break",
                    "        except Exception as error:",
                    "            errors.append(category + ' ' + expression + ': ' + str(error))",
                    "            try:",
                    "                report_module.DeleteReports([report_name])",
                    "            except Exception:",
                    "                pass",
                    "    if created:",
                    "        break",
                    "if not created:",
                    "    raise Exception('Terminal Z report failed: ' + '; '.join(errors))",
                    "exported = False",
                    "for args_tuple in ((report_name, output_csv, False), (report_name, output_csv)):",
                    "    try:",
                    "        report_module.ExportToFile(*args_tuple)",
                    "        if os.path.isfile(output_csv):",
                    "            exported = True",
                    "            break",
                    "    except Exception:",
                    "        pass",
                    "try:",
                    "    report_module.DeleteReports([report_name])",
                    "except Exception:",
                    "    pass",
                    "if not exported:",
                    "    raise Exception('Terminal Z CSV was not written')",
                    "result['path'] = output_csv",
                ]
            )
        )
        path = Path(str(raw.get("path") or dest))
        if not path.is_file():
            raise AdapterError("terminal Z CSV missing", code="terminal_z_export_failed")
        return path

    def export_farfield_2d_csv(
        self,
        *,
        setup: str,
        sweep: str | None,
        dest: Path,
        frequency: str | None = None,
    ) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        solution = f"{setup} : LastAdaptive"
        if sweep:
            solution = f"{setup} : {sweep}"
        freq = frequency or "All"
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    "report_name = 'hfss_mcp_farfield_2d'",
                    f"preferred = {solution!r}",
                    f"output_csv = {str(dest)!r}",
                    f"freq = {freq!r}",
                    "parent = os.path.dirname(output_csv)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "report_module = oDesign.GetModule('ReportSetup')",
                    "spheres = []",
                    "try:",
                    "    rad = oDesign.GetModule('RadField')",
                    "    for args in (('Infinite Sphere',), ()):",
                    "        try:",
                    "            spheres = [str(x) for x in (rad.GetSetupNames(*args) or [])]",
                    "            if spheres:",
                    "                break",
                    "        except Exception:",
                    "            pass",
                    "except Exception:",
                    "    spheres = []",
                    "if not spheres:",
                    "    raise Exception('No infinite sphere / far-field setup on this design')",
                    "solutions = []",
                    "try:",
                    "    solutions = [str(x) for x in (report_module.GetAvailableSolutions('Far Fields') or [])]",
                    "except Exception:",
                    "    solutions = []",
                    "setup_solution = preferred",
                    "if solutions and preferred not in solutions:",
                    "    adaptive = [s for s in solutions if 'LastAdaptive' in s]",
                    "    setup_solution = adaptive[0] if adaptive else solutions[0]",
                    "try:",
                    "    report_module.DeleteReports([report_name])",
                    "except Exception:",
                    "    pass",
                    "variation = ['Theta:=', ['All'], 'Phi:=', ['0deg'], 'Freq:=', [freq]]",
                    "expressions = ['dB(GainTotal)', 'GainTotal', 'dB(RealizedGainTotal)']",
                    "created = False",
                    "errors = []",
                    "for sphere in spheres:",
                    "    context = ['Context:=', sphere]",
                    "    for expression in expressions:",
                    "        components = ['X Component:=', 'Theta', 'Y Component:=', [expression]]",
                    "        try:",
                    "            report_module.CreateReport(report_name, 'Far Fields', 'Rectangular Plot', setup_solution, context, variation, components)",
                    "            created = True",
                    "            break",
                    "        except Exception as error:",
                    "            errors.append(str(error))",
                    "            try:",
                    "                report_module.DeleteReports([report_name])",
                    "            except Exception:",
                    "                pass",
                    "    if created:",
                    "        break",
                    "if not created:",
                    "    raise Exception('Far-field 2D report failed. Available solutions: ' + (', '.join(solutions) if solutions else '<none>') + '. ' + '; '.join(errors))",
                    "exported = False",
                    "for args_tuple in ((report_name, output_csv, False), (report_name, output_csv)):",
                    "    try:",
                    "        report_module.ExportToFile(*args_tuple)",
                    "        if os.path.isfile(output_csv):",
                    "            exported = True",
                    "            break",
                    "    except Exception:",
                    "        pass",
                    "try:",
                    "    report_module.DeleteReports([report_name])",
                    "except Exception:",
                    "    pass",
                    "if not exported:",
                    "    raise Exception('Far-field CSV was not written')",
                    "result['path'] = output_csv",
                    "result['setup_solution'] = setup_solution",
                    "result['spheres'] = spheres",
                ]
            )
        )
        path = Path(str(raw.get("path") or dest))
        if not path.is_file():
            raise AdapterError("far-field CSV missing", code="farfield_export_failed")
        return path

    def export_field_face_image(
        self,
        dest: Path,
        *,
        face: str,
        frequency: str,
        setup: str,
        sweep: str | None = None,
        quantity: str = "Mag_E",
        width: int = 1280,
        height: int = 800,
    ) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        solution = f"{setup} : LastAdaptive"
        if sweep:
            solution = f"{setup} : {sweep}"
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    f"file_name = {str(dest)!r}",
                    f"face = {face!r}",
                    f"freq = {frequency!r}",
                    f"quantity = {quantity!r}",
                    f"preferred = {solution!r}",
                    f"width = {int(width)}",
                    f"height = {int(height)}",
                    "parent = os.path.dirname(file_name)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "plot_name = 'hfss_mcp_field_face'",
                    "folder = os.path.dirname(file_name)",
                    "fields = oDesign.GetModule('FieldsReporter')",
                    "try:",
                    "    fields.DeleteFieldPlot([plot_name])",
                    "except Exception:",
                    "    pass",
                    "face_ids = []",
                    "obj_name = face",
                    "try:",
                    "    face_ids = [int(face)]",
                    "    obj_name = ''",
                    "except Exception:",
                    "    face_ids = []",
                    "    try:",
                    "        face_ids = [int(x) for x in (oEditor.GetFaceIDs(face) or [])]",
                    "    except Exception:",
                    "        face_ids = []",
                    "intrinsic = \"Freq='\" + freq + \"' Phase='0deg'\"",
                    "geoms = []",
                    "if face_ids:",
                    "    geoms.append([1, 'Surface', 'FacesList', 1, int(face_ids[0])])",
                    "    geoms.append([1, 'Surface', 'FacesList', len(face_ids)] + [int(x) for x in face_ids])",
                    "if obj_name:",
                    "    geoms.append([1, 'Surface', 'Objects', 1, obj_name])",
                    "    geoms.append([1, 'Surface', 'Objects', [obj_name]])",
                    "solutions = [preferred, preferred.split(' : ')[0] + ' : LastAdaptive']",
                    "quantities = [quantity, 'Mag_E', 'Mag_Jsurf', 'Mag_H']",
                    "created = False",
                    "errors = []",
                    "used_solution = preferred",
                    "for sol in solutions:",
                    "    for qty in quantities:",
                    "        for geom in geoms:",
                    "            payload = [",
                    "                'NAME:' + plot_name,",
                    "                'SolutionName:=', sol,",
                    "                'UserSpecifyName:=', 1,",
                    "                'UserSpecifyFolder:=', 0,",
                    "                'QuantityName:=', qty,",
                    "                'PlotFolder:=', 'E Field',",
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
                    "    if created:",
                    "        break",
                    "if not created:",
                    "    raise Exception('Field plot on face failed. Need a solved field solution at this frequency. ' + '; '.join(errors[:6]))",
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
                    "    try:",
                    "        oEditor.FitAll()",
                    "    except Exception:",
                    "        pass",
                    "    params = ['NAME:SaveImageParams', 'ShowAxis:=', False, 'ShowGrid:=', False, 'ShowRuler:=', False, 'ShowRegion:=', 'Default', 'Orientation:=', 'isometric']",
                    "    for args in ((file_name, int(width), int(height), params), (file_name, int(width), int(height)), (file_name,)):",
                    "        try:",
                    "            oEditor.ExportModelImageToFile(*args)",
                    "            if os.path.isfile(file_name):",
                    "                exported = True",
                    "                break",
                    "        except Exception as error:",
                    "            last = str(error)",
                    "try:",
                    "    fields.DeleteFieldPlot([plot_name])",
                    "except Exception:",
                    "    pass",
                    "if not exported:",
                    "    raise Exception(last or 'Field-face image was not written')",
                    "result['file'] = file_name",
                    "result['solution'] = used_solution",
                ]
            ),
            timeout_seconds=120.0,
        )
        path = Path(str(raw.get("file") or dest))
        if not path.is_file():
            raise AdapterError(
                "field_face image was not written",
                code="field_face_export_failed",
            )
        return path

    def view_capture(
        self,
        dest: Path,
        *,
        orientation: str = "isometric",
        isolate: list[str] | None = None,
        width: int = 1280,
        height: int = 800,
    ) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        names = json.dumps([str(x) for x in (isolate or [])], ensure_ascii=True)
        raw = self._script(
            "\n".join(
                [
                    "import os",
                    f"file_name = {str(dest)!r}",
                    f"orientation = {orientation!r}",
                    f"width = {int(width)}",
                    f"height = {int(height)}",
                    f"isolate = {names}",
                    "parent = os.path.dirname(file_name)",
                    "if parent and not os.path.isdir(parent):",
                    "    os.makedirs(parent)",
                    "if isolate:",
                    "    try:",
                    "        oEditor.ShowUnclassified(False)",
                    "    except Exception:",
                    "        pass",
                    "    try:",
                    "        all_names = []",
                    "        for group in ('Solids', 'Sheets', 'Lines'):",
                    "            try:",
                    "                all_names.extend([str(x) for x in (oEditor.GetObjectsInGroup(group) or [])])",
                    "            except Exception:",
                    "                pass",
                    "        hide = [n for n in all_names if n not in isolate]",
                    "        if hide:",
                    "            oEditor.ChangeProperty([",
                    "                'NAME:AllTabs',",
                    "                ['NAME:Geometry3DAttributeTab', ['NAME:PropServers'] + hide, ['NAME:ChangedProps', ['NAME:Show', 'Value:=', False]]],",
                    "            ])",
                    "    except Exception:",
                    "        pass",
                    "try:",
                    "    oEditor.FitAll()",
                    "except Exception:",
                    "    pass",
                    "params = ['NAME:SaveImageParams', 'ShowAxis:=', False, 'ShowGrid:=', False, 'ShowRuler:=', False, 'ShowRegion:=', 'Default', 'Orientation:=', orientation]",
                    "exported = False",
                    "last = ''",
                    "for args in ((file_name, int(width), int(height), params), (file_name, int(width), int(height)), (file_name,)):",
                    "    try:",
                    "        oEditor.ExportModelImageToFile(*args)",
                    "        if os.path.isfile(file_name):",
                    "            exported = True",
                    "            break",
                    "    except Exception as error:",
                    "        last = str(error)",
                    "if isolate:",
                    "    try:",
                    "        oEditor.ChangeProperty([",
                    "            'NAME:AllTabs',",
                    "            ['NAME:Geometry3DAttributeTab', ['NAME:PropServers'] + isolate, ['NAME:ChangedProps', ['NAME:Show', 'Value:=', True]]],",
                    "        ])",
                    "    except Exception:",
                    "        pass",
                    "if not exported:",
                    "    raise Exception(last or 'ExportModelImageToFile failed')",
                    "result['file'] = file_name",
                ]
            )
        )
        path = Path(str(raw.get("file") or dest))
        if not path.is_file():
            raise AdapterError("view capture did not write a file", code="view_capture_failed")
        return path

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
