"""Create a minimal HFSS project for real AEDT smoke (temp workspace only)."""

from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any


def create_minimal_patch_project(
    work_dir: Path,
    *,
    project_name: str = "McpSmokePatch",
    design_name: str = "HFSSDesign1",
    version: str = "2023.2",
    non_graphical: bool = True,
) -> dict[str, Any]:
    """Build a tiny driven-modal model optimized for fast unattended solves."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    project_path = work_dir / f"{project_name}.aedt"

    for p in list(work_dir.glob(f"{project_name}*")):
        with suppress(OSError):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)

    import importlib

    mod = None
    for name in ("ansys.aedt.core", "pyaedt"):
        try:
            mod = importlib.import_module(name)
            break
        except ImportError:
            continue
    if mod is None:
        raise RuntimeError("PyAEDT not importable")

    Hfss = mod.Hfss
    hfss = Hfss(
        project=str(project_path),
        design=design_name,
        solution_type="Modal",
        version=version,
        non_graphical=non_graphical,
        new_desktop=True,
        close_on_exit=True,
    )
    try:
        # Single independent variable for fast trials
        hfss["gap"] = "1mm"

        modeler = hfss.modeler
        # Very small copper plates
        modeler.create_box(
            origin=["0mm", "0mm", "0mm"],
            sizes=["5mm", "5mm", "0.5mm"],
            name="BoxBot",
            material="copper",
        )
        modeler.create_box(
            origin=["0mm", "0mm", "gap"],
            sizes=["5mm", "5mm", "0.5mm"],
            name="BoxTop",
            material="copper",
        )
        modeler.create_rectangle(
            orientation="XZ",
            origin=["0mm", "0mm", "0.5mm"],
            sizes=["5mm", "gap"],
            name="PortSheet",
        )

        axis = getattr(hfss, "axis_directions", None)
        integ = getattr(axis, "ZPos", 5) if axis is not None else 5
        try:
            hfss.lumped_port(
                assignment="PortSheet",
                reference=None,
                create_port_sheet=False,
                integration_line=integ,
                impedance=50,
                name="1",
                renormalize=True,
            )
        except Exception:
            hfss.lumped_port(
                assignment="PortSheet",
                create_port_sheet=False,
                integration_line=[[0, 0, 0.5], [0, 0, 1.5]],
                impedance=50,
                name="1",
            )

        # No open region — radiation is expensive; air box is enough for S11 path
        modeler.create_box(
            origin=["-5mm", "-5mm", "-5mm"],
            sizes=["15mm", "15mm", "15mm"],
            name="AirBox",
            material="vacuum",
        )
        with suppress(Exception):
            hfss.assign_radiation_boundary_to_objects("AirBox")

        setup = hfss.create_setup(name="Setup1")
        with suppress(Exception):
            setup.props["Frequency"] = "2.4GHz"
            setup.props["MaximumPasses"] = 1
            setup.props["MinimumPasses"] = 1
            setup.props["MaxDeltaS"] = 0.2
            setup.update()

        # Few discrete points for speed
        hfss.create_linear_count_sweep(
            setup="Setup1",
            unit="GHz",
            start_frequency=1.0,
            stop_frequency=3.0,
            num_of_freq_points=5,
            name="Sweep1",
            sweep_type="Discrete",
            save_fields=False,
        )

        hfss.save_project()
        project_file = getattr(hfss, "project_file", None) or str(project_path)
        return {
            "project_path": str(Path(str(project_file)).resolve()),
            "project_name": str(hfss.project_name),
            "design_name": str(hfss.design_name),
            "setup": "Setup1",
            "sweep": "Sweep1",
            "parameters": ["gap"],
        }
    finally:
        with suppress(Exception):
            hfss.release_desktop(close_projects=True, close_desktop=True)
