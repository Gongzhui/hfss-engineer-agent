"""Application context: live COM session for interactive tuning."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.allowlist import Allowlist, assert_writable, load_allowlist_dict, load_allowlist_file
from hfss_mcp.config import RuntimeConfig, load_runtime_config
from hfss_mcp.domain import JobState, ParameterValue, utc_now_iso
from hfss_mcp.environment import inspect_environment
from hfss_mcp.errors import AdapterError, HfssMcpError, JobError, PolicyError
from hfss_mcp.ids import new_id
from hfss_mcp.live import REPORT_TYPES, LiveDesign, attach_live, list_rot_sessions
from hfss_mcp.session_discovery import discover_running_sessions

_FAKE_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    "080606070605080707070909080a0c140d0c0b0b0c1912130f"
    "141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c303134"
    "34341f27393d38323c2e333432ffda000c03010002110311003f00"
    "aa000fffd9"
)


class AppContext:
    """Process-local services shared by MCP tools. Never closes the user's AEDT."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        config: RuntimeConfig | None = None,
        adapter_name: str | None = None,
        use_fake: bool | None = None,
    ) -> None:
        if use_fake is True:
            adapter_name = "fake"
        elif use_fake is False:
            adapter_name = "pyaedt"
        self.config = config or load_runtime_config(
            adapter=adapter_name,  # type: ignore[arg-type]
            data_dir=data_dir,
        )
        self.data_dir = self.config.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = self.data_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._allowlist: Allowlist | None = None
        self._live: LiveDesign | None = None
        self._fake: FakeAdapter | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._job_lock = threading.Lock()
        self._reports: dict[str, dict[str, Any]] = {}
        self._analyze_thread: threading.Thread | None = None

    @property
    def is_fake(self) -> bool:
        return self.config.adapter == "fake"

    def close(self) -> None:
        self._live = None
        if self._fake is not None:
            try:
                self._fake.disconnect(close_desktop=False)
            except Exception:
                pass
            self._fake = None

    def health(self) -> dict[str, Any]:
        env = inspect_environment()
        preferred = env.preferred
        real_ready = (
            self.config.adapter == "pyaedt"
            and preferred is not None
            and preferred.exe_exists
        )
        from hfss_mcp import __version__ as pkg_version

        rot = []
        if not self.is_fake:
            try:
                rot = list_rot_sessions(version=self.config.aedt_version)
            except Exception:
                rot = []
        return {
            "ok": True,
            "version": str(pkg_version),
            "mode": "engineer_session_v1" if not self.is_fake else "demo_fake",
            "adapter": self.config.adapter,
            "demo_mode": self.config.demo_mode,
            "real_hfss_ready": real_ready,
            "aedt_version_configured": self.config.aedt_version,
            "connection_mode": "in_process_fake" if self.is_fake else "com_attach_live",
            "gui_attached": self._live is not None or (
                self._fake is not None and getattr(self._fake, "_attached", False)
            ),
            "gui_process_id": None if self._live is None else self._live.process_id,
            "allowlist_loaded": self._allowlist is not None,
            "data_dir": str(self.data_dir),
            "environment": env.to_public_dict(),
            "sessions": {"sessions": rot, "count": len(rot)},
            "warnings": (
                []
                if real_ready or self.is_fake
                else ["AEDT executable not found"]
            ),
        }

    def session_list(self) -> dict[str, Any]:
        if self.is_fake:
            return {"ok": True, "connection_mode": "in_process_fake", "sessions": [], "count": 0}
        rot = list_rot_sessions(version=self.config.aedt_version)
        discovery = discover_running_sessions(version=self.config.aedt_version)
        return {
            "ok": True,
            "connection_mode": "com_attach_live",
            "sessions": rot,
            "count": len(rot),
            "lock_discovery": discovery.to_public_dict(),
        }

    def allowlist_load(
        self,
        path: str | None = None,
        allowlist: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path:
            loaded = load_allowlist_file(path)
        elif allowlist:
            loaded = load_allowlist_dict(allowlist)
        else:
            raise PolicyError("pass path or allowlist", code="allowlist_required")
        self._allowlist = loaded
        return {
            "ok": True,
            "allowlist_id": loaded.allowlist_id(),
            "project_name": loaded.project_name,
            "design_name": loaded.design_name,
            "parameters": [p.model_dump(by_alias=True) for p in loaded.parameters],
            "default_setup": loaded.default_setup,
        }

    def _require_allowlist(self) -> Allowlist:
        if self._allowlist is None:
            raise PolicyError(
                "load an allowlist first (allowlist_load)",
                code="allowlist_not_loaded",
            )
        return self._allowlist

    def _ensure_session(self) -> None:
        allowlist = self._require_allowlist()
        if self.is_fake:
            if self._fake is None:
                self._fake = FakeAdapter(
                    project_path=Path(allowlist.project_path)
                    if allowlist.project_path
                    else Path(r"C:\fake\projects") / f"{allowlist.project_name}.aedt",
                    project_name=allowlist.project_name,
                    design_name=allowlist.design_name,
                    variables={
                        p.name: ParameterValue(
                            name=p.name, value=(p.min_value + p.max_value) / 2.0, unit=p.unit
                        )
                        for p in allowlist.parameters
                    },
                    setups=[allowlist.default_setup or "Setup1"],
                )
            path = (
                Path(allowlist.project_path)
                if allowlist.project_path
                else self._fake._project_path
            )
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"FAKE_PROJECT\n")
            self._fake.attach_project(path, allowlist.design_name)
            return
        if self._live is not None:
            return
        self._live = attach_live(
            version=self.config.aedt_version,
            project_name=allowlist.project_name,
            design_name=allowlist.design_name,
            project_path=allowlist.project_path,
        )

    def snapshot(self) -> dict[str, Any]:
        self._ensure_session()
        if self.is_fake:
            assert self._fake is not None
            snap = self._fake.snapshot()
            payload = snap.model_dump()
        else:
            assert self._live is not None
            payload = self._live.snapshot()
        allowlist = self._require_allowlist()
        if payload.get("design_name") and payload["design_name"] != allowlist.design_name:
            raise PolicyError(
                "attached design does not match allowlist",
                code="design_identity_mismatch",
                details={
                    "expected": allowlist.design_name,
                    "actual": payload.get("design_name"),
                },
            )
        return {"ok": True, "snapshot": payload}

    def variables_set(self, parameters: list[dict[str, Any]]) -> dict[str, Any]:
        allowlist = self._require_allowlist()
        self._ensure_session()
        values = [ParameterValue.model_validate(item) for item in parameters]
        if not values:
            raise PolicyError("parameters must be non-empty", code="empty_parameters")
        for item in values:
            assert_writable(allowlist, item.name, item.value, item.unit)
        if self.is_fake:
            assert self._fake is not None
            result = self._fake.set_variables(values)
        else:
            assert self._live is not None
            result = self._live.set_variables(values)
        return {"ok": True, **result}

    def analyze_start(self, setup: str | None = None) -> dict[str, Any]:
        allowlist = self._require_allowlist()
        self._ensure_session()
        setup_name = setup or allowlist.default_setup
        if not setup_name:
            snap = self.snapshot()["snapshot"]
            setups = snap.get("setups") or []
            if not setups:
                raise AdapterError("no setup name given and none found", code="setup_required")
            setup_name = str(setups[0])
        with self._job_lock:
            running = [
                j
                for j in self._jobs.values()
                if j["state"] == JobState.RUNNING.value
            ]
            if running:
                raise JobError(
                    "an analyze job is already running",
                    code="analyze_busy",
                    details={"job_id": running[0]["job_id"]},
                )
            job_id = new_id("job_")
            rec: dict[str, Any] = {
                "job_id": job_id,
                "kind": "analyze",
                "state": JobState.RUNNING.value,
                "setup": setup_name,
                "created_at": utc_now_iso(),
                "started_at": utc_now_iso(),
                "finished_at": None,
                "error": None,
            }
            self._jobs[job_id] = rec

        if self.is_fake:
            assert self._fake is not None
            self._fake.start_solve(setup_name)
            rec["state"] = JobState.COMPLETED.value
            rec["finished_at"] = utc_now_iso()
            return {"ok": True, "job_id": job_id, "job": rec}

        def _run() -> None:
            try:
                assert self._live is not None
                self._live.analyze(setup_name)
                with self._job_lock:
                    rec["state"] = JobState.COMPLETED.value
                    rec["finished_at"] = utc_now_iso()
            except Exception as exc:
                with self._job_lock:
                    rec["state"] = JobState.FAILED.value
                    rec["finished_at"] = utc_now_iso()
                    rec["error"] = {
                        "code": getattr(exc, "code", "analyze_failed"),
                        "message": str(exc),
                    }

        self._analyze_thread = threading.Thread(target=_run, name="hfss-analyze", daemon=True)
        self._analyze_thread.start()
        return {"ok": True, "job_id": job_id, "job": rec}

    def analyze_status(self, job_id: str) -> dict[str, Any]:
        rec = self._jobs.get(job_id)
        if rec is None:
            raise JobError(f"job not found: {job_id}", code="job_not_found")
        return {"ok": True, "job": rec}

    def analyze_cancel(self, job_id: str) -> dict[str, Any]:
        rec = self._jobs.get(job_id)
        if rec is None:
            raise JobError(f"job not found: {job_id}", code="job_not_found")
        if rec["state"] != JobState.RUNNING.value:
            return {"ok": True, "cancelled": False, "job": rec}
        rec["state"] = JobState.CANCEL_REQUESTED.value
        return {
            "ok": True,
            "cancelled": False,
            "job": rec,
            "message": "Analyze on the live GUI cannot be force-killed; cancel is best-effort",
        }

    def report_types(self) -> dict[str, Any]:
        return {"ok": True, "types": REPORT_TYPES}

    def report_list(self) -> dict[str, Any]:
        return {"ok": True, "reports": list(self._reports.values())}

    def report_create(
        self,
        report_type: str,
        *,
        name: str | None = None,
        setup: str | None = None,
        sweep: str | None = None,
        face: str | None = None,
        frequency: str | None = None,
    ) -> dict[str, Any]:
        known = {item["id"] for item in REPORT_TYPES}
        if report_type not in known:
            raise PolicyError(
                f"unknown report type {report_type!r}",
                code="report_type_unknown",
                details={"allowed": sorted(known)},
            )
        allowlist = self._require_allowlist()
        report_id = new_id("rpt_")
        rec = {
            "report_id": report_id,
            "name": name or f"{report_type}_{report_id[-6:]}",
            "report_type": report_type,
            "setup": setup or allowlist.default_setup,
            "sweep": sweep or allowlist.default_sweep,
            "face": face,
            "frequency": frequency,
        }
        if report_type == "field_face" and (not face or not frequency):
            raise PolicyError(
                "field_face needs face and frequency",
                code="field_export_args",
            )
        self._reports[report_id] = rec
        return {"ok": True, "report": rec}

    def report_export(self, report_id: str) -> dict[str, Any]:
        rec = self._reports.get(report_id)
        if rec is None:
            raise PolicyError(f"report not found: {report_id}", code="report_not_found")
        self._ensure_session()
        kind = rec["report_type"]
        stamp = new_id("art_")
        setup = str(rec.get("setup") or "Setup1")
        sweep = rec.get("sweep")
        if kind == "field_face":
            if not rec.get("face") or not rec.get("frequency"):
                raise PolicyError(
                    "field_face export needs face and frequency",
                    code="field_export_args",
                )
            dest = self.artifacts_dir / f"{stamp}_field_face.jpg"
            if self.is_fake:
                dest.write_bytes(_FAKE_JPEG)
            else:
                assert self._live is not None
                dest = self._live.export_field_face_image(
                    dest,
                    face=str(rec["face"]),
                    frequency=str(rec["frequency"]),
                    setup=setup,
                    sweep=sweep,
                )
            rec["artifact"] = str(dest)
            rec["format"] = "image"
            return {"ok": True, "report": rec, "path": str(dest), "format": "image"}
        dest = self.artifacts_dir / f"{stamp}_{kind}.csv"
        if self.is_fake:
            if kind == "terminal_z":
                dest.write_text("freq_ghz,re,im\n1.0,40.0,12.0\n2.4,50.0,2.0\n", encoding="utf-8")
            elif kind == "farfield_2d":
                dest.write_text(
                    "theta_deg,db_gain_total\n-180,-12.0\n0,5.0\n180,-12.0\n",
                    encoding="utf-8",
                )
            else:
                dest.write_text(
                    "freq_ghz,s11_db\n1.0,-5.0\n2.4,-12.0\n3.0,-8.0\n",
                    encoding="utf-8",
                )
        elif kind == "modal_s":
            assert self._live is not None
            dest = self._live.export_modal_s_csv(setup=setup, sweep=sweep, dest=dest)
        elif kind == "terminal_z":
            assert self._live is not None
            dest = self._live.export_terminal_z_csv(setup=setup, sweep=sweep, dest=dest)
        elif kind == "farfield_2d":
            assert self._live is not None
            dest = self._live.export_farfield_2d_csv(
                setup=setup,
                sweep=sweep,
                dest=dest,
                frequency=rec.get("frequency"),
            )
        else:
            raise AdapterError("unknown report kind", code="report_type_unknown")
        rec["artifact"] = str(dest)
        rec["format"] = "csv"
        return {"ok": True, "report": rec, "path": str(dest), "format": "csv"}

    def view_capture(
        self,
        *,
        orientation: str = "isometric",
        isolate: list[str] | None = None,
    ) -> dict[str, Any]:
        self._ensure_session()
        dest = self.artifacts_dir / f"view_{new_id('')[:10]}.jpg"
        if self.is_fake:
            dest.write_bytes(_FAKE_JPEG)
            path = dest
        else:
            assert self._live is not None
            path = self._live.view_capture(dest, orientation=orientation, isolate=isolate)
        return {"ok": True, "path": str(path), "orientation": orientation, "isolate": isolate or []}

    def variable_map(self, names: list[str] | None = None) -> dict[str, Any]:
        allowlist = self._require_allowlist()
        self._ensure_session()
        wanted = names or sorted(allowlist.names())
        if self.is_fake:
            usages = {
                name: [
                    {
                        "object": "Patch",
                        "property": "XSize" if name.endswith("w") or "w" in name else "YSize",
                        "expression": name,
                    }
                ]
                for name in wanted
            }
            return {"ok": True, "definitions": [], "usages": usages}
        assert self._live is not None
        payload = self._live.variable_map(wanted)
        return {"ok": True, **payload}

    def project_save(self, mode: str = "save_as", path: str | None = None) -> dict[str, Any]:
        self._ensure_session()
        if mode not in {"save", "save_as"}:
            raise PolicyError("mode must be save or save_as", code="save_mode_invalid")
        if mode == "save_as" and not path:
            raise PolicyError("save_as requires path", code="save_as_path_required")
        if self.is_fake:
            assert self._fake is not None
            if mode == "save_as":
                dest = Path(path or "")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"FAKE_SAVE_AS\n")
                return {"ok": True, "mode": mode, "path": str(dest), "saved": True}
            return {"ok": True, "mode": mode, "saved": True}
        assert self._live is not None
        raw = self._live.save() if mode == "save" else self._live.save_as(Path(path or ""))
        return {"ok": True, **raw}


def error_envelope(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, HfssMcpError):
        return exc.to_dict()
    return {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": str(exc),
            "details": {"type": type(exc).__name__},
        },
    }


def build_allowlist_for_tests(
    project_path: Path,
    *,
    parameters: list[dict[str, Any]] | None = None,
    setup: str = "Setup1",
    design_name: str = "HFSSDesign1",
) -> Allowlist:
        return load_allowlist_dict(
        {
            "project_path": str(project_path.resolve(strict=False)),
            "project_name": project_path.stem,
            "design_name": design_name,
            "default_setup": setup,
            "parameters": parameters
            or [
                {"name": "patch_w", "unit": "mm", "min": 1.0, "max": 50.0},
                {"name": "patch_l", "unit": "mm", "min": 1.0, "max": 50.0},
            ],
        }
    )
