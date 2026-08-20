"""Rebuild the thesis §3.1 circular monopole (geometry only).

Launches a *new* non-graphical AEDT. Refuses to continue if that process is the
already-open GUI Desktop. Does not create a port, setup, or sweep, and does not solve.

Usage:
    uv run python cases/uwb_circular_notch/build.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
PROJECT_NAME = "uwb_circular_notch"
DESIGN_NAME = "CircularMonopole"
AEDT_VERSION = "2023.2"

NOMINAL_MM: dict[str, str] = {
    "l": "33mm",
    "w": "25mm",
    "sub_h": "1.14mm",
    "lw": "3.5mm",
    "l1": "16.3mm",
    "patch_r": "8mm",
    "slot_length": "20mm",
    "l2": "2mm",
    "sw": "1mm",
    "g1": "16mm",
    "g2": "3.9mm",
    "g3": "5.2mm",
    "air_pad": "25mm",
}

EXPRESSIONS: dict[str, str] = {
    "l3": "slot_length/2",
    "l4": "slot_length/4",
}

FEED_OVERLAP = "0.3mm"


def _ansysedt_pids() -> set[int]:
    raw = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq ansysedt.exe", "/FO", "CSV", "/NH"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pids: set[int] = set()
    for line in raw.splitlines():
        if "ansysedt.exe" not in line.lower():
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _wipe_project(folder: Path, stem: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for path in folder.glob(f"{stem}*"):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def _ensure_rt5880(hfss: object) -> str:
    names = [
        "Rogers RT/duroid 5880 (tm)",
        "Rogers RT/duroid 5880",
        "RT5880",
    ]
    materials = hfss.materials
    for name in names:
        with suppress(Exception):
            if materials.exists(name) or name.casefold() in getattr(materials, "material_keys", {}):
                return name
    mat = materials.add_material("RT5880")
    mat.permittivity = 2.2
    mat.dielectric_loss_tangent = 0.0009
    with suppress(Exception):
        mat.update()
    return "RT5880"


def _assign_vars(hfss: object) -> None:
    hfss.modeler.model_units = "mm"
    for name, value in NOMINAL_MM.items():
        hfss[name] = value
    for name, expr in EXPRESSIONS.items():
        hfss[name] = expr


def _build_geometry(hfss: object, substrate_mat: str) -> None:
    modeler = hfss.modeler
    modeler.create_box(
        origin=["-w/2", "0mm", "0mm"],
        sizes=["w", "l", "sub_h"],
        name="Substrate",
        material=substrate_mat,
    )
    # orientation is the plane, not the axis. "Z" is misread as YZ → a vertical
    # wire that HFSS dumps in Unclassified. Must be "XY".
    modeler.create_circle(
        orientation="XY",
        origin=["0mm", "l1+patch_r", "sub_h"],
        radius="patch_r",
        name="Patch",
        material="copper",
    )
    modeler.create_rectangle(
        orientation="XY",
        origin=["-lw/2", "0mm", "sub_h"],
        sizes=["lw", f"l1+{FEED_OVERLAP}"],
        name="Feed",
        material="copper",
    )
    modeler.unite(["Patch", "Feed"], keep_originals=False)

    modeler.create_rectangle(
        orientation="XY",
        origin=["-l3/2", "l1+patch_r+l2-sw", "sub_h"],
        sizes=["l3", "sw"],
        name="USlotBar",
        material="copper",
    )
    modeler.create_rectangle(
        orientation="XY",
        origin=["-l3/2", "l1+patch_r+l2-l4", "sub_h"],
        sizes=["sw", "l4"],
        name="USlotLeft",
        material="copper",
    )
    modeler.create_rectangle(
        orientation="XY",
        origin=["l3/2-sw", "l1+patch_r+l2-l4", "sub_h"],
        sizes=["sw", "l4"],
        name="USlotRight",
        material="copper",
    )
    modeler.unite(["USlotBar", "USlotLeft", "USlotRight"], keep_originals=False)
    modeler.subtract("Patch", "USlotBar", keep_originals=False)

    modeler.create_rectangle(
        orientation="XY",
        origin=["-w/2", "0mm", "0mm"],
        sizes=["w", "g1"],
        name="Ground",
        material="copper",
    )
    modeler.create_rectangle(
        orientation="XY",
        origin=["-g2/2", "g1-g3", "0mm"],
        sizes=["g2", "g3"],
        name="GroundNotch",
        material="copper",
    )
    modeler.subtract("Ground", "GroundNotch", keep_originals=False)

    hfss.assign_perfecte_to_sheets("Patch", name="PatchPEC")
    hfss.assign_perfecte_to_sheets("Ground", name="GroundPEC")

    modeler.create_box(
        origin=["-w/2-air_pad", "-air_pad", "-air_pad"],
        sizes=["w+2*air_pad", "l+2*air_pad", "sub_h+2*air_pad"],
        name="AirBox",
        material="vacuum",
    )
    hfss.assign_radiation_boundary_to_objects("AirBox", name="Rad1")
    with suppress(Exception):
        modeler["AirBox"].display_wireframe = True
        modeler["AirBox"].transparency = 0.95
        modeler["Substrate"].transparency = 0.6
        modeler["Patch"].color = (220, 80, 40)
        modeler["Ground"].color = (240, 200, 60)


def _object_groups(hfss: object) -> dict[str, list[str]]:
    oed = hfss.modeler.oeditor
    groups: dict[str, list[str]] = {}
    for group in ("Solids", "Sheets", "Lines", "Unclassified"):
        names: list[str] = []
        with suppress(Exception):
            raw = oed.GetObjectsInGroup(group) or []
            names = [str(x) for x in raw if x]
        groups[group] = names
    return groups


def _assert_classified(hfss: object) -> dict[str, list[str]]:
    groups = _object_groups(hfss)
    print(f"groups: {groups}")
    unclassified = groups.get("Unclassified") or []
    if unclassified:
        raise SystemExit(f"unclassified objects (geometry invalid): {unclassified}")
    sheets = set(groups.get("Sheets") or [])
    solids = set(groups.get("Solids") or [])
    if "Patch" not in sheets:
        raise SystemExit(f"Patch is not a sheet: {groups}")
    if "Ground" not in sheets:
        raise SystemExit(f"Ground is not a sheet: {groups}")
    if "Substrate" not in solids:
        raise SystemExit(f"Substrate is not a solid: {groups}")
    return groups


def _hide_objects(hfss: object, names: list[str], hidden: bool) -> None:
    if not names:
        return
    args = ["NAME:Selections", "Selections:=", ",".join(names)]
    with suppress(Exception):
        if hidden:
            hfss.modeler.oeditor.Hide(args)
        else:
            hfss.modeler.oeditor.Show(args)


def _export_preview(hfss: object, dest: Path, *, hide: list[str] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    hide = hide or []
    _hide_objects(hfss, hide, True)
    oed = hfss.modeler.oeditor
    with suppress(Exception):
        oed.FitAll()
    params = [
        "NAME:SaveImageParams",
        "ShowAxis:=",
        True,
        "ShowGrid:=",
        False,
        "ShowRuler:=",
        True,
        "ShowRegion:=",
        "Default",
        "Orientation:=",
        "isometric",
    ]
    exported = False
    for args in (
        (str(dest), 1280, 800, params),
        (str(dest), 1280, 800),
        (str(dest),),
    ):
        with suppress(Exception):
            oed.ExportModelImageToFile(*args)
            if dest.is_file() and dest.stat().st_size > 1000:
                exported = True
                break
    _hide_objects(hfss, hide, False)
    if not exported:
        raise SystemExit(f"preview image was not written: {dest}")
    print(f"preview: {dest} ({dest.stat().st_size} bytes)")


def _dump_vars(hfss: object, path: Path) -> None:
    names = list(NOMINAL_MM) + list(EXPRESSIONS)
    out: dict[str, dict[str, str]] = {}
    for name in names:
        var = hfss[name]
        expr = (
            getattr(var, "expression", None)
            or NOMINAL_MM.get(name)
            or EXPRESSIONS.get(name)
        )
        evaluated = getattr(var, "evaluated_value", None)
        out[name] = {
            "expression": str(expr),
            "evaluated": str(evaluated if evaluated is not None else expr),
        }
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_perturbation() -> dict[str, str]:
    case = json.loads((CASE_DIR / "case.json").read_text(encoding="utf-8"))
    raw = case.get("perturbation") or {}
    return {str(k): str(v) for k, v in raw.items() if k not in {"seed", "min_pct", "max_pct"}}


def main() -> int:
    tmp = REPO_ROOT / ".tmp_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(tmp)
    os.environ["TEMP"] = str(tmp)
    os.environ["TMPDIR"] = str(tmp)
    os.environ["PYAEDT_NON_GRAPHICAL"] = "1"

    nominal_dir = CASE_DIR / "nominal"
    sandbox_dir = CASE_DIR / "sandbox"
    answer_dir = CASE_DIR / "answer"
    nominal_file = nominal_dir / f"{PROJECT_NAME}.aedt"
    sandbox_file = sandbox_dir / f"{PROJECT_NAME}.aedt"

    _wipe_project(nominal_dir, PROJECT_NAME)
    _wipe_project(sandbox_dir, PROJECT_NAME)
    # keep README.md in those folders
    for folder in (nominal_dir, sandbox_dir):
        readme = folder / "README.md"
        if not readme.exists():
            readme.write_text("", encoding="utf-8")

    preexisting = _ansysedt_pids()
    print(f"ansysedt already running: {sorted(preexisting) or 'none'}")

    from ansys.aedt.core import Hfss

    hfss = None
    build_pid: int | None = None
    try:
        hfss = Hfss(
            project=str(nominal_file),
            design=DESIGN_NAME,
            solution_type="Modal",
            version=AEDT_VERSION,
            non_graphical=True,
            new_desktop=True,
            close_on_exit=False,
        )
        build_pid = int(hfss.odesktop.GetProcessID())
        print(f"build desktop pid={build_pid}")
        if build_pid in preexisting:
            hfss.release_desktop(close_projects=False, close_desktop=False)
            hfss = None
            raise SystemExit(
                f"refusing to build: attached to already-open AEDT pid {build_pid}"
            )

        _assign_vars(hfss)
        substrate_mat = _ensure_rt5880(hfss)
        print(f"substrate material: {substrate_mat}")
        _build_geometry(hfss, substrate_mat)
        groups = _assert_classified(hfss)
        names = {n for g in groups.values() for n in g}
        if any(str(name).lower().startswith("port") for name in names):
            raise SystemExit(f"port-like object created, aborting: {sorted(names)}")

        setups = []
        with suppress(Exception):
            setups = list(hfss.setup_names)
        if setups:
            raise SystemExit(f"setup created unexpectedly: {setups}")

        preview_dir = CASE_DIR / "preview"
        _export_preview(hfss, preview_dir / "iso_all.png")
        _export_preview(hfss, preview_dir / "iso_antenna.png", hide=["AirBox"])

        hfss.save_project()
        if not nominal_file.is_file():
            raise SystemExit(f"nominal project missing: {nominal_file}")
        answer_dir.mkdir(parents=True, exist_ok=True)
        _dump_vars(hfss, answer_dir / "nominal_vars.json")
        print(f"saved nominal: {nominal_file}")

        for name, value in _load_perturbation().items():
            hfss[name] = value
            print(f"sandbox {name} = {value}")
        hfss.save_project(str(sandbox_file), overwrite=True)
        if not sandbox_file.is_file():
            raise SystemExit(f"sandbox project missing: {sandbox_file}")
        print(f"saved sandbox: {sandbox_file}")
    finally:
        if hfss is not None:
            with suppress(Exception):
                hfss.release_desktop(close_projects=True, close_desktop=True)
        if build_pid and build_pid not in preexisting:
            leftover_now = _ansysedt_pids()
            if build_pid in leftover_now:
                subprocess.run(["taskkill", "/PID", str(build_pid), "/F"], check=False)
                print(f"killed leftover build pid {build_pid}")

    leftover = _ansysedt_pids()
    killed = preexisting - leftover
    if killed:
        raise SystemExit(f"build closed GUI AEDT pids {sorted(killed)}; leftover={sorted(leftover)}")
    print(f"GUI AEDT still running: {sorted(preexisting & leftover)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
