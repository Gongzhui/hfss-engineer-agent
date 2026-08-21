"""Application context: live COM session for interactive tuning."""

from __future__ import annotations

import re
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
from hfss_mcp.live import (
    DEFAULT_REPORT_NAMES,
    FIELD_QUANTITIES,
    OPTIMETRICS_TYPES,
    PARAMETRIC_MAX_POINTS,
    REPORT_TYPES,
    VIEW_ORIENTATIONS,
    LiveDesign,
    attach_live,
    crash_message,
    failure_message_for_setup,
    last_progress_line,
    list_rot_sessions,
)
from hfss_mcp.metrics import csv_export_summary, normalize_exported_report_csv
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
        self.data_dir = Path(self.config.data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = (self.data_dir / "artifacts").resolve()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._allowlist: Allowlist | None = None
        self._live: LiveDesign | None = None
        self._fake: FakeAdapter | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._job_lock = threading.Lock()
        self._reports: dict[str, dict[str, Any]] = {}
        self._analyze_thread: threading.Thread | None = None
        self._parametric_vars: dict[str, list[str]] = {}
        self._variables_dirty: bool = False
        self._view_hidden: set[str] = set()

    @property
    def is_fake(self) -> bool:
        return self.config.adapter == "fake"

    def close(self) -> None:
        self._drop_session()

    def _drop_session(self) -> None:
        self._live = None
        self._parametric_vars = {}
        self._variables_dirty = False
        self._view_hidden = set()
        if self._fake is not None:
            try:
                self._fake.disconnect(close_desktop=False)
            except Exception:
                pass
            self._fake = None

    def _allowlist_matches_session(self, allowlist: Allowlist) -> bool:
        if self.is_fake:
            if self._fake is None:
                return False
            return (
                self._fake._project_name == allowlist.project_name
                and self._fake._design_name == allowlist.design_name
            )
        if self._live is None:
            return False
        if (
            self._live.project_name != allowlist.project_name
            or self._live.design_name != allowlist.design_name
        ):
            return False
        wanted = allowlist.project_path
        have = self._live.project_path
        if wanted and have:
            return Path(have).resolve(strict=False) == Path(wanted).resolve(strict=False)
        return True

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
        if not self._allowlist_matches_session(loaded):
            if self._live is not None or self._fake is not None:
                self._drop_session()
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
        if not self._allowlist_matches_session(allowlist):
            self._drop_session()
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
        self._variables_dirty = True
        return {
            "ok": True,
            **result,
            "needs_solve": True,
            "note": (
                "Variables are written. Results still show the last solved "
                "variation until you Analyze or export a family trace for this point."
            ),
        }

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
            self._variables_dirty = False
            return self._job_payload(rec)

        def _run() -> None:
            try:
                assert self._live is not None
                self._live.analyze(setup_name)
                with self._job_lock:
                    rec["state"] = JobState.COMPLETED.value
                    rec["finished_at"] = utc_now_iso()
                    self._variables_dirty = False
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
        return self._job_payload(rec)

    def analyze_status(self, job_id: str) -> dict[str, Any]:
        rec = self._jobs.get(job_id)
        if rec is None:
            raise JobError(f"job not found: {job_id}", code="job_not_found")
        return self._job_payload(rec)

    def _job_payload(self, rec: dict[str, Any]) -> dict[str, Any]:
        """ok means the tool call worked. done means HFSS finished or failed."""
        state = str(rec.get("state") or "")
        done = state in {JobState.COMPLETED.value, JobState.FAILED.value}
        running = state == JobState.RUNNING.value
        payload: dict[str, Any] = {
            "ok": True,
            "accepted": True,
            "done": done,
            "poll": "analyze_status" if running else None,
            "job_id": rec.get("job_id"),
            "job": rec,
        }
        if self.is_fake or self._live is None:
            payload["messages"] = list(rec.get("messages") or [])
            return payload
        try:
            messages = self._live.read_messages(limit=24)
        except Exception:
            messages = []
        payload["messages"] = messages
        rec["messages"] = messages[-8:]
        progress = last_progress_line(messages)
        if progress:
            payload["progress"] = progress
            rec["progress"] = progress
        if running:
            fail = failure_message_for_setup(messages, str(rec.get("setup") or ""))
            if not fail and rec.get("kind") == "parametric":
                fail = crash_message(messages)
            if fail:
                rec["state"] = JobState.FAILED.value
                rec["finished_at"] = utc_now_iso()
                rec["error"] = {"code": "hfss_message", "message": fail}
                payload["done"] = True
                payload["poll"] = None
        payload["job"] = rec
        return payload

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

    def optimetrics_types(self) -> dict[str, Any]:
        return {"ok": True, "types": OPTIMETRICS_TYPES}

    def _optimetrics_setups(self) -> list[dict[str, Any]]:
        if self.is_fake:
            assert self._fake is not None
            return self._fake.list_optimetrics()
        assert self._live is not None
        return self._live.list_optimetrics()

    def optimetrics_list(self) -> dict[str, Any]:
        self._ensure_session()
        setups = self._optimetrics_setups()
        for item in setups:
            if item.get("variables"):
                continue
            cached = self._parametric_vars.get(str(item.get("name") or ""))
            if cached:
                item["variables"] = list(cached)
        return {"ok": True, "setups": setups}

    def _format_parametric_sweeps(
        self, sweeps: list[dict[str, Any]]
    ) -> tuple[list[dict[str, str]], int]:
        allowlist = self._require_allowlist()
        if not sweeps:
            raise PolicyError(
                "parametric needs at least one sweep",
                code="parametric_sweep_required",
            )
        formatted: list[dict[str, str]] = []
        total_points = 1
        for raw in sweeps:
            name = str(raw.get("variable") or raw.get("name") or "").strip()
            spec = allowlist.param_map().get(name)
            if spec is None:
                raise PolicyError(
                    f"variable {name!r} is not on the allowlist",
                    code="variable_not_allowed",
                    details={"name": name, "allowed": sorted(allowlist.names())},
                )
            unit = str(raw.get("unit") or spec.unit)
            default_variation = "values" if raw.get("values") else "linear_step"
            variation = str(raw.get("variation") or default_variation)
            if variation == "values":
                values = [float(v) for v in (raw.get("values") or [])]
                if len(values) < 2:
                    raise PolicyError(
                        "values sweep needs at least two points",
                        code="parametric_sweep_invalid",
                        details={"variable": name},
                    )
                for value in values:
                    assert_writable(allowlist, name, value, unit)
                data = " ".join(f"{value}{unit}" for value in values)
                n_points = len(values)
            elif variation == "linear_step":
                if any(k not in raw for k in ("start", "stop", "step")):
                    raise PolicyError(
                        "linear_step needs start, stop, step",
                        code="parametric_sweep_invalid",
                    )
                start = float(raw["start"])
                stop = float(raw["stop"])
                step = float(raw["step"])
                if step <= 0:
                    raise PolicyError("step must be > 0", code="parametric_sweep_invalid")
                assert_writable(allowlist, name, start, unit)
                assert_writable(allowlist, name, stop, unit)
                n_points = int(round(abs(stop - start) / step)) + 1
                lo, hi = (start, stop) if start <= stop else (stop, start)
                data = f"LIN {lo}{unit} {hi}{unit} {step}{unit}"
            elif variation == "linear_count":
                if any(k not in raw for k in ("start", "stop", "count")):
                    raise PolicyError(
                        "linear_count needs start, stop, count",
                        code="parametric_sweep_invalid",
                    )
                start = float(raw["start"])
                stop = float(raw["stop"])
                count = int(raw["count"])
                if count < 2:
                    raise PolicyError(
                        "linear_count needs count >= 2",
                        code="parametric_sweep_invalid",
                    )
                assert_writable(allowlist, name, start, unit)
                assert_writable(allowlist, name, stop, unit)
                n_points = count
                lo, hi = (start, stop) if start <= stop else (stop, start)
                data = f"LINC {lo}{unit} {hi}{unit} {count}"
            else:
                raise PolicyError(
                    f"unsupported variation {variation!r}; "
                    "use linear_step, linear_count, or values",
                    code="parametric_variation_unsupported",
                    details={"allowed": ["linear_step", "linear_count", "values"]},
                )
            total_points *= n_points
            formatted.append({"variable": name, "data": data})
        if total_points > PARAMETRIC_MAX_POINTS:
            raise PolicyError(
                f"parametric would run {total_points} points; max is {PARAMETRIC_MAX_POINTS}",
                code="parametric_too_many_points",
                details={"points": total_points, "max": PARAMETRIC_MAX_POINTS},
            )
        return formatted, total_points

    def parametric_create(
        self,
        *,
        name: str | None = None,
        setup: str | None = None,
        sweeps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        allowlist = self._require_allowlist()
        self._ensure_session()
        formatted, points = self._format_parametric_sweeps(list(sweeps or []))
        setup_name = setup or allowlist.default_setup or "Setup1"
        report_name = name or f"Parametric_{formatted[0]['variable']}"
        if self.is_fake:
            assert self._fake is not None
            rec = self._fake.create_parametric(
                name=report_name, sim_setup=setup_name, sweeps=formatted
            )
        else:
            assert self._live is not None
            rec = self._live.create_parametric(
                name=report_name, sim_setup=setup_name, sweeps=formatted
            )
        rec["sim_setup"] = setup_name
        rec["sweeps"] = formatted
        rec["points"] = points
        rec["variables"] = [item["variable"] for item in formatted]
        self._parametric_vars[report_name] = list(rec["variables"])
        return {"ok": True, "setup": rec}

    def parametric_start(self, name: str) -> dict[str, Any]:
        self._ensure_session()
        listed = self._optimetrics_setups()
        match = next((item for item in listed if item.get("name") == name), None)
        if match is None:
            raise PolicyError(
                f"parametric {name!r} is not under Optimetrics; create it first",
                code="report_not_in_results",
                details={"name": name},
            )
        if match.get("setup_kind") != "parametric":
            raise PolicyError(
                f"{name!r} is {match.get('setup_kind')}, not a parametric setup",
                code="parametric_kind_unsupported",
            )
        with self._job_lock:
            running = [j for j in self._jobs.values() if j["state"] == JobState.RUNNING.value]
            if running:
                raise JobError(
                    "an analyze job is already running",
                    code="analyze_busy",
                    details={"job_id": running[0]["job_id"]},
                )
            job_id = new_id("job_")
            rec: dict[str, Any] = {
                "job_id": job_id,
                "kind": "parametric",
                "state": JobState.RUNNING.value,
                "setup": name,
                "created_at": utc_now_iso(),
                "started_at": utc_now_iso(),
                "finished_at": None,
                "error": None,
            }
            self._jobs[job_id] = rec
        if self.is_fake:
            rec["state"] = JobState.COMPLETED.value
            rec["finished_at"] = utc_now_iso()
            self._variables_dirty = False
            return self._job_payload(rec)

        def _run() -> None:
            try:
                assert self._live is not None
                self._live.analyze_parametric(name)
                with self._job_lock:
                    rec["state"] = JobState.COMPLETED.value
                    rec["finished_at"] = utc_now_iso()
                    self._variables_dirty = False
            except Exception as exc:
                with self._job_lock:
                    rec["state"] = JobState.FAILED.value
                    rec["finished_at"] = utc_now_iso()
                    rec["error"] = {
                        "code": getattr(exc, "code", "analyze_failed"),
                        "message": str(exc),
                    }

        self._analyze_thread = threading.Thread(target=_run, name="hfss-parametric", daemon=True)
        self._analyze_thread.start()
        return self._job_payload(rec)

    def parametric_export_table(self, name: str) -> dict[str, Any]:
        self._ensure_session()
        dest = self.artifacts_dir / f"{new_id('art_')}_parametric.csv"
        if self.is_fake:
            assert self._fake is not None
            dest = self._fake.export_parametric_table(name, dest)
        else:
            assert self._live is not None
            dest = self._live.export_parametric_table(name, dest)
        return {"ok": True, "name": name, "path": str(dest), "format": "csv"}

    def report_types(self) -> dict[str, Any]:
        return {"ok": True, "types": REPORT_TYPES}

    def _default_report_name(
        self,
        report_type: str,
        *,
        name: str | None,
        face: str | None,
        frequency: str | None,
        quantity: str | None = None,
    ) -> str:
        if name:
            return name
        if report_type == "field_face":
            face_part = re.sub(r"[^\w]+", "_", str(face or "face")).strip("_") or "face"
            freq_part = re.sub(r"[^\w]+", "_", str(frequency or "freq")).strip("_") or "freq"
            qty_part = re.sub(r"[^\w]+", "_", str(quantity or "Mag_E")).strip("_") or "Mag_E"
            return f"Field_{face_part}_{freq_part}_{qty_part}"
        if report_type == "farfield_2d" and frequency:
            freq_part = re.sub(r"[^\w]+", "_", str(frequency)).strip("_")
            return f"{DEFAULT_REPORT_NAMES['farfield_2d']}_{freq_part}"
        return DEFAULT_REPORT_NAMES.get(report_type, report_type)

    def report_list(self) -> dict[str, Any]:
        self._ensure_session()
        if self.is_fake:
            assert self._fake is not None
            reports = self._fake.list_reports()
        else:
            assert self._live is not None
            reports = self._live.list_reports()
        return {"ok": True, "reports": reports}

    def _known_parametric_variable_names(self) -> list[str]:
        seen: list[str] = []

        def add(name: object) -> None:
            key = str(name).strip()
            if key and key not in seen:
                seen.append(key)

        for cached in self._parametric_vars.values():
            for name in cached:
                add(name)
        for item in self._optimetrics_setups():
            if item.get("setup_kind") != "parametric":
                continue
            for name in item.get("variables") or []:
                add(name)
            cached = self._parametric_vars.get(str(item.get("name") or ""))
            if cached:
                for name in cached:
                    add(name)
        return seen

    def _parametric_setup_variables(self, name: str) -> list[str]:
        listed = self._optimetrics_setups()
        match = next((item for item in listed if item.get("name") == name), None)
        if match is None:
            raise PolicyError(
                f"parametric {name!r} is not under Optimetrics",
                code="report_not_in_results",
                details={"name": name},
            )
        names = [str(x).strip() for x in (match.get("variables") or []) if str(x).strip()]
        if not names:
            names = [
                str(x).strip()
                for x in (self._parametric_vars.get(name) or [])
                if str(x).strip()
            ]
        if not names:
            raise PolicyError(
                f"parametric {name!r} has no sweep variables on the Optimetrics node; "
                "names are cached when you parametric_create in this MCP session",
                code="parametric_variables_unknown",
                details={"name": name},
            )
        return names

    def _report_variation_plan(
        self,
        *,
        families: list[str] | None,
        parametric: str | None,
    ) -> tuple[list[str], list[str]]:
        """(All vars, Nominal-pinned vars). Default does not All every setup."""
        allowlist = self._require_allowlist()
        known = self._known_parametric_variable_names()
        family: list[str] = []
        if families is not None:
            for name in families:
                key = str(name).strip()
                if not key:
                    continue
                if key not in allowlist.names():
                    raise PolicyError(
                        f"variable {key!r} is not on the allowlist",
                        code="variable_not_allowed",
                        details={"name": key, "allowed": sorted(allowlist.names())},
                    )
                if key not in family:
                    family.append(key)
        elif parametric:
            family = self._parametric_setup_variables(parametric)
        nominal = [name for name in known if name not in family]
        return family, nominal

    def report_create(
        self,
        report_type: str,
        *,
        name: str | None = None,
        setup: str | None = None,
        sweep: str | None = None,
        face: str | None = None,
        frequency: str | None = None,
        families: list[str] | None = None,
        parametric: str | None = None,
        quantity: str | None = None,
    ) -> dict[str, Any]:
        known = {item["id"] for item in REPORT_TYPES}
        if report_type not in known:
            raise PolicyError(
                f"unknown report type {report_type!r}",
                code="report_type_unknown",
                details={"allowed": sorted(known)},
            )
        allowlist = self._require_allowlist()
        field_quantity = "Mag_E"
        if report_type == "field_face":
            if not face or not frequency:
                raise PolicyError(
                    "field_face needs face and frequency",
                    code="field_export_args",
                )
            field_quantity = quantity or "Mag_E"
            if field_quantity not in FIELD_QUANTITIES:
                raise PolicyError(
                    f"unknown field quantity {field_quantity!r}",
                    code="field_quantity_unknown",
                    details={"allowed": sorted(FIELD_QUANTITIES)},
                )
        self._ensure_session()
        report_name = self._default_report_name(
            report_type,
            name=name,
            face=face,
            frequency=frequency,
            quantity=field_quantity if report_type == "field_face" else None,
        )
        setup_name = setup or allowlist.default_setup or "Setup1"
        sweep_name = sweep or allowlist.default_sweep
        family_variables: list[str] = []
        nominal_variables: list[str] = []
        if report_type != "field_face":
            family_variables, nominal_variables = self._report_variation_plan(
                families=families, parametric=parametric
            )
        if self.is_fake:
            assert self._fake is not None
            rec = self._fake.create_results_report(
                report_type=report_type,
                name=report_name,
                setup=setup_name,
                sweep=sweep_name,
                frequency=frequency,
                face=face,
                family_variables=family_variables,
                nominal_variables=nominal_variables,
                quantity=field_quantity if report_type == "field_face" else None,
            )
        else:
            assert self._live is not None
            if report_type == "field_face":
                rec = self._live.create_field_overlay(
                    name=report_name,
                    face=str(face),
                    frequency=str(frequency),
                    setup=setup_name,
                    sweep=sweep_name,
                    quantity=field_quantity,
                )
            else:
                rec = self._live.create_results_report(
                    report_type=report_type,
                    name=report_name,
                    setup=setup_name,
                    sweep=sweep_name,
                    frequency=frequency,
                    family_variables=family_variables,
                    nominal_variables=nominal_variables,
                )
        rec["report_id"] = rec.get("name") or report_name
        rec["report_type"] = report_type
        rec["face"] = face
        rec["frequency"] = frequency
        if report_type != "field_face":
            rec["family_variables"] = list(rec.get("family_variables") or family_variables)
            rec["nominal_variables"] = list(rec.get("nominal_variables") or nominal_variables)
        if report_type == "field_face":
            rec["quantity"] = field_quantity
        self._reports[str(rec["report_id"])] = rec
        return {"ok": True, "report": rec}

    def report_export(self, report_id: str) -> dict[str, Any]:
        self._ensure_session()
        rec = self._reports.get(report_id)
        listed_item: dict[str, Any] | None = None
        if self.is_fake:
            assert self._fake is not None
            listed = self._fake.list_reports()
        else:
            assert self._live is not None
            listed = self._live.list_reports()
        for item in listed:
            if item.get("name") == report_id or item.get("report_id") == report_id:
                listed_item = item
                break
        kind = (rec or {}).get("report_type") or (listed_item or {}).get("report_type")
        is_overlay = kind == "field_face" or (listed_item or {}).get("tree") == "Field Overlays"
        if listed_item is None:
            raise PolicyError(
                f"report {report_id!r} is not under Results or Field Overlays; create it first",
                code="report_not_in_results",
                details={"report_id": report_id},
            )
        listed_name = str(listed_item.get("name") or report_id)
        if is_overlay:
            dest = self.artifacts_dir / f"{new_id('art_')}_field_face.jpg"
            if self.is_fake:
                assert self._fake is not None
                dest = self._fake.export_results_report(
                    listed_name, dest, report_type="field_face"
                )
            else:
                assert self._live is not None
                dest = self._live.export_field_overlay(listed_name, dest)
            out = rec or dict(listed_item)
            out["artifact"] = str(dest)
            out["format"] = "image"
            self._reports[listed_name] = out
            return {"ok": True, "report": out, "path": str(dest), "format": "image"}
        dest = self.artifacts_dir / f"{new_id('art_')}_{kind or 'report'}.csv"
        if self.is_fake:
            assert self._fake is not None
            dest = self._fake.export_results_report(
                listed_name, dest, report_type=kind
            )
        else:
            assert self._live is not None
            dest = self._live.export_results_report(
                listed_name, dest, report_type=kind
            )
        if dest.suffix.lower() == ".csv":
            dest = normalize_exported_report_csv(
                dest,
                kind,
                trace_names=list(listed_item.get("traces") or []),
            )
        out = rec or {
            "report_id": listed_name,
            "name": listed_name,
            "report_type": kind,
            "in_results": True,
        }
        out["artifact"] = str(dest)
        out["format"] = "csv"
        self._reports[listed_name] = out
        payload: dict[str, Any] = {
            "ok": True,
            "report": out,
            "path": str(dest),
            "format": "csv",
        }
        if dest.suffix.lower() == ".csv":
            summary = csv_export_summary(dest)
            payload["traces"] = summary.get("traces")
            payload["labeled"] = summary.get("labeled")
            payload["csv_format"] = summary.get("format")
            payload["header"] = summary.get("header")
        if self._variables_dirty:
            payload["stale_solution"] = True
            payload["note"] = (
                "variables_set has not been solved. This CSV is the last solved "
                "variation, not the current design values. Analyze, or export a "
                "family trace that already contains this point."
            )
        return payload

    def view_hide(self, names: list[str]) -> dict[str, Any]:
        cleaned = [str(x).strip() for x in names if str(x).strip()]
        if not cleaned:
            raise PolicyError("names must be non-empty", code="empty_parameters")
        self._ensure_session()
        if self.is_fake:
            self._view_hidden.update(cleaned)
            return {
                "ok": True,
                "hidden": sorted(self._view_hidden),
                "names": cleaned,
                "missing": [],
            }
        assert self._live is not None
        raw = self._live.view_set_visible(cleaned, show=False)
        self._view_hidden.update(raw["names"])
        return {
            "ok": True,
            "hidden": sorted(self._view_hidden),
            "names": raw["names"],
            "missing": raw["missing"],
            "objects": raw["objects"],
        }

    def view_show(
        self, names: list[str] | None = None, *, all_objects: bool = False
    ) -> dict[str, Any]:
        cleaned = [str(x).strip() for x in (names or []) if str(x).strip()]
        if not all_objects and not cleaned:
            raise PolicyError(
                "pass names or all_objects=true",
                code="empty_parameters",
            )
        self._ensure_session()
        if self.is_fake:
            if all_objects:
                shown = sorted(self._view_hidden)
                self._view_hidden.clear()
            else:
                shown = cleaned
                self._view_hidden.difference_update(cleaned)
            return {
                "ok": True,
                "hidden": sorted(self._view_hidden),
                "names": shown,
                "missing": [],
            }
        assert self._live is not None
        raw = self._live.view_set_visible(
            cleaned, show=True, all_objects=all_objects
        )
        if all_objects:
            self._view_hidden.clear()
        else:
            self._view_hidden.difference_update(raw["names"])
        return {
            "ok": True,
            "hidden": sorted(self._view_hidden),
            "names": raw["names"],
            "missing": raw["missing"],
            "objects": raw["objects"],
        }

    def view_capture(
        self,
        *,
        orientation: str = "isometric",
        fit: list[str] | None = None,
        isolate: list[str] | None = None,
    ) -> dict[str, Any]:
        self._ensure_session()
        o = (orientation or "isometric").strip().lower()
        if o not in VIEW_ORIENTATIONS:
            raise PolicyError(
                f"orientation must be one of: {', '.join(VIEW_ORIENTATIONS)}",
                code="orientation_invalid",
                details={"valid": list(VIEW_ORIENTATIONS), "got": orientation},
            )
        dest = self.artifacts_dir / f"view_{new_id('')[:10]}.jpg"
        keep = [str(x).strip() for x in (fit or isolate or []) if str(x).strip()]
        if self.is_fake:
            dest.write_bytes(_FAKE_JPEG)
            return {
                "ok": True,
                "path": str(dest),
                "orientation": o,
                "fit": keep,
                "isolate": isolate or [],
                "hidden": sorted(self._view_hidden),
                "selection": keep,
                "missing": [],
            }
        assert self._live is not None
        path, selection, fitted, missing = self._live.view_capture(
            dest,
            orientation=o,
            fit=keep or None,
            isolate=None,
            hidden=sorted(self._view_hidden),
        )
        return {
            "ok": True,
            "path": str(path),
            "orientation": o,
            "fit": fitted,
            "isolate": isolate or [],
            "hidden": sorted(self._view_hidden),
            "selection": selection,
            "missing": missing,
        }

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
