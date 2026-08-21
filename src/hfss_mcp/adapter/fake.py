"""In-memory FakeAdapter for offline MCP tests."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.domain import DesignSnapshot, ParameterValue, utc_now_iso
from hfss_mcp.errors import AdapterError
from hfss_mcp.ids import sha256_hex


class FakeAdapter:
    """Deterministic stand-in for the live COM design."""

    def __init__(
        self,
        *,
        project_path: Path | None = None,
        project_name: str = "DemoProject",
        design_name: str = "HFSSDesign1",
        variables: dict[str, ParameterValue] | None = None,
        setups: list[str] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._attached = False
        self._project_path = (
            Path(project_path)
            if project_path is not None
            else Path(r"C:\fake\projects\DemoProject.aedt")
        )
        self._project_name = project_name
        self._design_name = design_name
        self._variables: dict[str, ParameterValue] = copy.deepcopy(variables or {})
        self._setups = list(setups or ["Setup1"])
        self._mutation_count = 0
        self._revision = self._compute_revision()
        self._results_reports: list[dict[str, Any]] = []
        self._field_overlays: list[dict[str, Any]] = []
        self._optimetrics: list[dict[str, Any]] = []

    def _compute_revision(self) -> str:
        payload = {
            "n": self._mutation_count,
            "vars": {k: {"v": v.value, "u": v.unit} for k, v in sorted(self._variables.items())},
        }
        return sha256_hex(str(payload))[:16]

    def attach_project(self, project_path: Path, design_name: str) -> DesignSnapshot:
        with self._lock:
            path = Path(project_path)
            self._project_path = path
            self._project_name = path.stem
            self._design_name = design_name
            self._attached = True
            if not self._variables:
                self._variables = {
                    "patch_w": ParameterValue(name="patch_w", value=10.0, unit="mm"),
                    "patch_l": ParameterValue(name="patch_l", value=12.0, unit="mm"),
                }
            self._revision = self._compute_revision()
            return self.snapshot()

    def snapshot(self) -> DesignSnapshot:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            return DesignSnapshot(
                project_path=str(self._project_path),
                project_name=self._project_name,
                design_name=self._design_name,
                revision=self._revision,
                variables=copy.deepcopy(self._variables),
                setups=list(self._setups),
                objects=["Patch", "Substrate", "Ground", "AirBox"],
                captured_at=utc_now_iso(),
            )

    def set_variables(self, items: list[ParameterValue]) -> dict[str, Any]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            readback: dict[str, ParameterValue] = {}
            for item in items:
                if item.name not in self._variables:
                    raise AdapterError(
                        f"variable {item.name!r} does not exist",
                        code="variable_not_found",
                        details={"name": item.name},
                    )
                self._variables[item.name] = ParameterValue(
                    name=item.name, value=item.value, unit=item.unit
                )
                readback[item.name] = copy.deepcopy(self._variables[item.name])
            self._mutation_count += 1
            self._revision = self._compute_revision()
            return {
                "ok": True,
                "readback": {k: v.model_dump() for k, v in readback.items()},
                "saved": False,
                "revision": self._revision,
            }

    def start_solve(self, setup: str, sweep: str | None = None) -> None:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            if setup not in self._setups:
                raise AdapterError(
                    f"setup {setup!r} not found",
                    code="setup_not_found",
                    details={"setup": setup},
                )
            _ = sweep

    def list_reports(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(item) for item in self._results_reports + self._field_overlays]

    def create_results_report(
        self,
        *,
        report_type: str,
        name: str,
        setup: str,
        sweep: str | None,
        frequency: str | None = None,
        face: str | None = None,
        family_variables: list[str] | None = None,
        nominal_variables: list[str] | None = None,
        quantity: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            if report_type == "field_face":
                rec = {
                    "name": name,
                    "report_id": name,
                    "report_type": report_type,
                    "setup": setup,
                    "sweep": sweep,
                    "frequency": frequency,
                    "face": face,
                    "quantity": quantity,
                    "in_results": False,
                    "tree": "Field Overlays",
                    "created": True,
                    "reused": False,
                }
                existing = next((x for x in self._field_overlays if x["name"] == name), None)
                if existing:
                    out = copy.deepcopy(existing)
                    out["created"] = False
                    out["reused"] = True
                    return out
                self._field_overlays.append(rec)
                return copy.deepcopy(rec)
            family = [str(v) for v in (family_variables or []) if str(v).strip()]
            nominal = [
                str(v)
                for v in (nominal_variables or [])
                if str(v).strip() and str(v).strip() not in family
            ]
            existing = next((x for x in self._results_reports if x["name"] == name), None)
            if existing:
                if family or nominal:
                    raise AdapterError(
                        f"report {name!r} already exists; pick a new name to apply "
                        "families or Nominal pins",
                        code="report_exists",
                        details={"name": name},
                    )
                return {
                    **copy.deepcopy(existing),
                    "created": False,
                    "reused": True,
                    "in_results": True,
                }
            report_rec: dict[str, Any] = {
                "name": name,
                "report_id": name,
                "report_type": report_type,
                "setup": setup,
                "sweep": sweep,
                "frequency": frequency,
                "in_results": True,
                "tree": "Results",
                "created": True,
                "reused": False,
                "family_variables": family,
                "nominal_variables": nominal,
                "families_applied": bool(family),
                "traces": (
                    [
                        f"dB(S(1,1)) [] - {family[0]}='lo'",
                        f"dB(S(1,1)) [] - {family[0]}='hi'",
                    ]
                    if family
                    else []
                ),
            }
            self._results_reports.append(report_rec)
            return copy.deepcopy(report_rec)

    def export_results_report(
        self,
        name: str,
        dest: Path,
        *,
        report_type: str | None = None,
    ) -> Path:
        with self._lock:
            rec = next((x for x in self._results_reports if x["name"] == name), None)
            overlay = next((x for x in self._field_overlays if x["name"] == name), None)
            if rec is None and overlay is None:
                raise AdapterError(
                    f"report {name!r} is not under Results; create it first",
                    code="report_not_in_results",
                    details={"name": name},
                )
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            kind = report_type or (rec or overlay or {}).get("report_type")
            if kind == "field_face":
                dest.write_bytes(b"\xff\xd8\xff\xd9")
                return dest
            families = list((rec or {}).get("family_variables") or [])
            if kind == "terminal_z":
                dest.write_text("freq_ghz,re,im\n1.0,40.0,12.0\n2.4,50.0,2.0\n", encoding="utf-8")
            elif kind == "farfield_2d":
                dest.write_text(
                    "theta_deg,db_gain_total\n-180,-12.0\n0,5.0\n180,-12.0\n",
                    encoding="utf-8",
                )
            elif families:
                # GUI Export Data, Separate Columns unchecked: one column per var.
                combo_lo = {var: 10.0 if index == 0 else 11.0 for index, var in enumerate(families)}
                combo_hi = {var: 11.0 if index == 0 else 13.0 for index, var in enumerate(families)}
                header = [f"{var} [mm]" for var in families] + [
                    "Freq [GHz]",
                    "dB(S(1,1)) []",
                ]
                freqs = (1.0, 2.4, 3.0)
                dbs = ((-5.0, -12.0, -8.0), (-4.0, -9.0, -7.0))
                lines = [",".join(f'"{item}"' for item in header)]
                for combo, trace in ((combo_lo, dbs[0]), (combo_hi, dbs[1])):
                    for freq, db in zip(freqs, trace, strict=True):
                        cells = [str(combo[var]) for var in families]
                        cells.extend([str(freq), str(db)])
                        lines.append(",".join(cells))
                dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:
                dest.write_text(
                    "freq_ghz,s11_db\n1.0,-5.0\n2.4,-12.0\n3.0,-8.0\n",
                    encoding="utf-8",
                )
            return dest

    def list_optimetrics(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(item) for item in self._optimetrics]

    def create_parametric(
        self,
        *,
        name: str,
        sim_setup: str,
        sweeps: list[dict[str, str]],
    ) -> dict[str, Any]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            existing = next((x for x in self._optimetrics if x["name"] == name), None)
            rec = {
                "name": name,
                "tree": "Optimetrics",
                "setup_kind": "parametric",
                "enabled": True,
                "has_result": False,
                "variables": [item["variable"] for item in sweeps],
                "sim_setup": sim_setup,
                "sweeps": copy.deepcopy(sweeps),
                "created": existing is None,
                "reused": existing is not None,
                "edited": existing is not None,
            }
            if existing:
                existing.update(rec)
                existing["created"] = False
                existing["reused"] = True
                existing["edited"] = True
                return copy.deepcopy(existing)
            self._optimetrics.append(rec)
            return copy.deepcopy(rec)

    def export_parametric_table(self, name: str, dest: Path) -> Path:
        with self._lock:
            rec = next((x for x in self._optimetrics if x["name"] == name), None)
            if rec is None:
                raise AdapterError(
                    f"parametric {name!r} is not under Optimetrics; create it first",
                    code="report_not_in_results",
                    details={"name": name},
                )
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            variables = rec.get("variables") or ["var"]
            header = "*," + ",".join(str(v) for v in variables)
            dest.write_text(header + "\n1,1.0\n", encoding="utf-8")
            rec["has_result"] = True
            return dest

    def disconnect(self, *, close_desktop: bool = False) -> None:
        with self._lock:
            self._attached = False
            _ = close_desktop
