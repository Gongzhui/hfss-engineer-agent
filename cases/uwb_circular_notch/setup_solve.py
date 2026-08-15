"""Add thesis-style setup/sweep/far-field to the ported nominal project and solve.

Does not rebuild geometry. Opens the existing .aedt in a new non-graphical AEDT.
Refuses to attach to an already-open GUI Desktop.

Usage:
    uv run python cases/uwb_circular_notch/setup_solve.py
"""

from __future__ import annotations

import csv
import math
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
PROJECT_FILE = CASE_DIR / "nominal" / "uwb_circular_notch.aedt"
DESIGN_NAME = "CircularMonopole"
AEDT_VERSION = "2023.2"
SETUP_NAME = "Setup1"
SWEEP_NAME = "Sweep1"
RAD_SWEEP_NAME = "RadSweep"
SPHERE_NAME = "FF3D"
SOLVE_FREQ = "12GHz"
SWEEP_START_GHZ = 1.0
SWEEP_STOP_GHZ = 15.0
SWEEP_POINTS = 141
PATTERN_GHZ = (3.65, 11.27)
CORES = 4


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


def _ensure_setup(hfss: object) -> None:
    names = [str(x) for x in (hfss.setup_names or [])]
    if SETUP_NAME not in names:
        created = hfss.create_setup(
            name=SETUP_NAME,
            Frequency=SOLVE_FREQ,
            MaximumPasses=18,
            MinimumPasses=2,
            MaxDeltaS=0.02,
        )
        actual = getattr(created, "name", SETUP_NAME)
        print(f"created setup {actual} @ {SOLVE_FREQ}")
        if actual != SETUP_NAME:
            raise SystemExit(f"setup was renamed to {actual}, expected {SETUP_NAME}")
    else:
        print(f"setup already present: {names}")

    setup = None
    for item in hfss.setups:
        if getattr(item, "name", None) == SETUP_NAME:
            setup = item
            break
    if setup is None:
        raise SystemExit(f"cannot find setup {SETUP_NAME}")

    sweep_names = [getattr(s, "name", str(s)) for s in (setup.sweeps or [])]
    if SWEEP_NAME not in sweep_names:
        hfss.create_linear_count_sweep(
            setup=SETUP_NAME,
            unit="GHz",
            start_frequency=SWEEP_START_GHZ,
            stop_frequency=SWEEP_STOP_GHZ,
            num_of_freq_points=SWEEP_POINTS,
            name=SWEEP_NAME,
            save_fields=False,
            save_rad_fields=False,
            sweep_type="Interpolating",
        )
        print(f"created interpolating {SWEEP_NAME} {SWEEP_START_GHZ}-{SWEEP_STOP_GHZ} GHz")
    if RAD_SWEEP_NAME not in sweep_names:
        setup.create_single_point_sweep(
            unit="GHz",
            freq=list(PATTERN_GHZ),
            name=RAD_SWEEP_NAME,
            save_single_field=True,
            save_fields=True,
            save_rad_fields=True,
        )
        print(f"created discrete {RAD_SWEEP_NAME} at {PATTERN_GHZ} GHz")


def _ensure_sphere(hfss: object) -> None:
    existing: list[str] = []
    with suppress(Exception):
        rad = hfss.odesign.GetModule("RadField")
        for args in (("Infinite Sphere",), ()):
            with suppress(Exception):
                existing = [str(x) for x in (rad.GetSetupNames(*args) or [])]
                if existing:
                    break
    if SPHERE_NAME in existing:
        print(f"sphere exists: {existing}")
        return
    hfss.insert_infinite_sphere(
        name=SPHERE_NAME,
        theta_start=0,
        theta_stop=180,
        theta_step=5,
        phi_start=0,
        phi_stop=360,
        phi_step=5,
    )
    print(f"created infinite sphere {SPHERE_NAME}")


def _create_reports(hfss: object) -> None:
    rpt = hfss.odesign.GetModule("ReportSetup")
    s11_name = "S11"
    with suppress(Exception):
        rpt.DeleteReports([s11_name])
    rpt.CreateReport(
        s11_name,
        "Modal Solution Data",
        "Rectangular Plot",
        f"{SETUP_NAME} : {SWEEP_NAME}",
        ["Domain:=", "Sweep"],
        ["Freq:=", ["All"]],
        ["X Component:=", "Freq", "Y Component:=", ["dB(S(1,1))"]],
    )
    for freq in PATTERN_GHZ:
        tag = str(freq).replace(".", "p")
        e_name = f"Eplane_{tag}GHz"
        h_name = f"Hplane_{tag}GHz"
        for name in (e_name, h_name):
            with suppress(Exception):
                rpt.DeleteReports([name])
        # E-plane: YZ, phi=90, Gain vs Theta
        rpt.CreateReport(
            e_name,
            "Far Fields",
            "Radiation Pattern",
            f"{SETUP_NAME} : {RAD_SWEEP_NAME}",
            ["Context:=", SPHERE_NAME],
            ["Theta:=", ["All"], "Phi:=", ["90deg"], "Freq:=", [f"{freq}GHz"]],
            ["Ang Component:=", "Theta", "Mag Component:=", ["dB(GainTotal)"]],
        )
        # H-plane: XY, theta=90, Gain vs Phi
        rpt.CreateReport(
            h_name,
            "Far Fields",
            "Radiation Pattern",
            f"{SETUP_NAME} : {RAD_SWEEP_NAME}",
            ["Context:=", SPHERE_NAME],
            ["Theta:=", ["90deg"], "Phi:=", ["All"], "Freq:=", [f"{freq}GHz"]],
            ["Ang Component:=", "Phi", "Mag Component:=", ["dB(GainTotal)"]],
        )
    print("created S11 + E/H-plane reports")


def _export_report_csv(hfss: object, report_name: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    rpt = hfss.odesign.GetModule("ReportSetup")
    exported = False
    for args in ((report_name, str(dest), False), (report_name, str(dest))):
        with suppress(Exception):
            rpt.ExportToFile(*args)
            if dest.is_file() and dest.stat().st_size > 10:
                exported = True
                break
    if not exported:
        raise SystemExit(f"failed to export report {report_name} -> {dest}")
    print(f"csv: {dest}")
    return dest


def _summarize_s11(csv_path: Path) -> dict[str, float]:
    from importlib.util import module_from_spec, spec_from_file_location

    plot_path = REPO_ROOT / "skills" / "tune-hfss-antenna" / "scripts" / "plot_s11.py"
    spec = spec_from_file_location("plot_s11", plot_path)
    if spec is None or spec.loader is None:
        raise SystemExit("plot_s11.py missing")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    freqs, dbs = mod.parse_s11_file(csv_path)
    svg = CASE_DIR / "results" / "s11.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(plot_path),
            str(csv_path),
            "--mark-ghz",
            "3.65",
            "--out",
            str(svg),
        ],
        check=False,
    )

    band = [(f, db) for f, db in zip(freqs, dbs, strict=False) if 3.07 <= f <= 12.67]
    notch = [(f, db) for f, db in zip(freqs, dbs, strict=False) if 5.0 <= f <= 7.5]
    summary = {
        "n_points": float(len(freqs)),
        "f_min": min(freqs),
        "f_max": max(freqs),
        "s11_min_db": min(dbs),
        "s11_min_ghz": freqs[dbs.index(min(dbs))],
        "band_frac_below_m10": (
            sum(1 for _, db in band if db <= -10.0) / len(band) if band else 0.0
        ),
        "notch_max_db": max(db for _, db in notch) if notch else math.nan,
        "notch_max_ghz": (max(notch, key=lambda x: x[1])[0] if notch else math.nan),
    }
    csv_path = CASE_DIR / "results" / "s11.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["freq_ghz", "s11_db"])
        writer.writerows(zip(freqs, dbs, strict=False))
    print(f"s11 csv: {csv_path}")
    print(f"s11 svg: {svg}")
    print(f"s11 summary: {summary}")
    return summary


def main() -> int:
    if not PROJECT_FILE.is_file():
        raise SystemExit(f"missing project: {PROJECT_FILE}")

    tmp = REPO_ROOT / ".tmp_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(tmp)
    os.environ["TEMP"] = str(tmp)
    os.environ["TMPDIR"] = str(tmp)
    os.environ["PYAEDT_NON_GRAPHICAL"] = "1"

    preexisting = _ansysedt_pids()
    print(f"ansysedt already running: {sorted(preexisting) or 'none'}")

    from ansys.aedt.core import Hfss

    hfss = None
    build_pid: int | None = None
    try:
        hfss = Hfss(
            project=str(PROJECT_FILE),
            design=DESIGN_NAME,
            non_graphical=True,
            new_desktop=True,
            close_on_exit=False,
            version=AEDT_VERSION,
        )
        build_pid = int(hfss.odesktop.GetProcessID())
        print(f"solve desktop pid={build_pid}")
        if build_pid in preexisting:
            hfss.release_desktop(close_projects=False, close_desktop=False)
            hfss = None
            raise SystemExit(f"refusing: attached to already-open AEDT pid {build_pid}")

        excitations = []
        with suppress(Exception):
            excitations = [str(x) for x in (hfss.excitation_names or [])]
        print(f"excitations: {excitations}")
        if not any(name == "1" or name.endswith(":1") or name.startswith("1") for name in excitations):
            raise SystemExit("wave port '1' not found; will not invent a port")

        _ensure_setup(hfss)
        _ensure_sphere(hfss)
        hfss.save_project()
        print("setup saved, starting analyze")
        hfss.analyze(setup=SETUP_NAME, cores=CORES, blocking=True)
        print("analyze finished")
        _create_reports(hfss)
        results = CASE_DIR / "results"
        s11_raw = _export_report_csv(hfss, "S11", results / "s11_from_hfss_report.csv")
        from hfss_mcp.metrics import normalize_exported_report_csv

        s11_csv = results / "s11.csv"
        s11_csv.write_bytes(s11_raw.read_bytes())
        normalize_exported_report_csv(s11_csv, "modal_s")
        _summarize_s11(s11_csv)
        for freq in PATTERN_GHZ:
            tag = str(freq).replace(".", "p")
            _export_report_csv(hfss, f"Eplane_{tag}GHz", results / f"eplane_{tag}ghz.csv")
            _export_report_csv(hfss, f"Hplane_{tag}GHz", results / f"hplane_{tag}ghz.csv")
        hfss.save_project()
        print(f"saved {PROJECT_FILE}")
    finally:
        if hfss is not None:
            with suppress(Exception):
                hfss.release_desktop(close_projects=True, close_desktop=True)
        if build_pid and build_pid not in preexisting:
            leftover_now = _ansysedt_pids()
            if build_pid in leftover_now:
                subprocess.run(["taskkill", "/PID", str(build_pid), "/F"], check=False)
                print(f"killed leftover solve pid {build_pid}")

    leftover = _ansysedt_pids()
    killed = preexisting - leftover
    if killed:
        raise SystemExit(f"solve closed GUI AEDT pids {sorted(killed)}")
    print(f"GUI AEDT still running: {sorted(preexisting & leftover)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
