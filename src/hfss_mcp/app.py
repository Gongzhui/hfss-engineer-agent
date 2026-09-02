"""Application context: live COM session for interactive tuning."""

from __future__ import annotations

import csv
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.allowlist import Allowlist, assert_writable, load_allowlist_dict, load_allowlist_file
from hfss_mcp.config import RuntimeConfig, load_runtime_config
from hfss_mcp.constraints import assert_constraints, assert_constraints_on_rows
from hfss_mcp.domain import JobState, ParameterValue, utc_now_iso
from hfss_mcp.environment import inspect_environment
from hfss_mcp.errors import AdapterError, HfssMcpError, JobError, PolicyError
from hfss_mcp.ids import new_id
from hfss_mcp.ledger import SolveLedger
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
from hfss_mcp.metrics import (
    csv_export_summary,
    normalize_exported_report_csv,
    render_s11_png,
    summarize_modal_s_csv,
    summarize_terminal_z_csv,
)
from hfss_mcp.session_discovery import discover_running_sessions
from hfss_mcp.sweeps import cartesian_from_axes, expand_table_rows, lin_values, linc_values

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
        self._job_lock = threading.RLock()
        self._reports: dict[str, dict[str, Any]] = {}
        self._analyze_thread: threading.Thread | None = None
        self._parametric_vars: dict[str, list[str]] = {}
        self._parametric_meta: dict[str, dict[str, Any]] = {}
        self._variables_dirty: bool = False
        self._view_hidden: set[str] = set()
        # State that must survive an MCP host idle-restart of this process.
        self._state_file = self.data_dir / "session-state.json"
        self._persisted_allowlist_path: str | None = None
        self._persisted_hidden: dict[str, list[str]] = {}
        self._ledger = SolveLedger(self.data_dir / "solve-ledger.jsonl")
        self._load_state()
        restored = self._ledger.load_jobs()
        if restored:
            self._jobs.update(restored)

    def _load_state(self) -> None:
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        path = raw.get("allowlist_path")
        if isinstance(path, str) and path.strip():
            self._persisted_allowlist_path = path
        hidden = raw.get("view_hidden")
        if isinstance(hidden, dict):
            self._persisted_hidden = {
                str(k): [str(x) for x in v if str(x).strip()]
                for k, v in hidden.items()
                if isinstance(v, list)
            }
        meta = raw.get("parametric_meta")
        if isinstance(meta, dict):
            self._parametric_meta = {
                str(k): dict(v) for k, v in meta.items() if isinstance(v, dict)
            }

    def _save_state(self) -> None:
        payload = {
            "allowlist_path": self._persisted_allowlist_path,
            "view_hidden": {k: sorted(v) for k, v in self._persisted_hidden.items()},
            "parametric_meta": self._parametric_meta,
        }
        try:
            self._state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _session_key(self) -> str | None:
        if self.is_fake:
            if self._fake is None:
                return None
            return f"{self._fake._project_name}::{self._fake._design_name}"
        if self._live is None:
            return None
        return f"{self._live.project_name}::{self._live.design_name}"

    def _restore_view_hidden(self) -> None:
        key = self._session_key()
        if key and not self._view_hidden and key in self._persisted_hidden:
            self._view_hidden = set(self._persisted_hidden[key])

    def _persist_view_hidden(self) -> None:
        key = self._session_key()
        if key is None:
            return
        if self._view_hidden:
            self._persisted_hidden[key] = sorted(self._view_hidden)
        else:
            self._persisted_hidden.pop(key, None)
        self._save_state()

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

    def _gui_projects(self) -> list[dict[str, Any]]:
        if self.is_fake:
            if self._fake is None or not getattr(self._fake, "_attached", False):
                return []
            return [
                {
                    "process_id": None,
                    "project_name": self._fake._project_name,
                    "designs": [self._fake._design_name],
                    "project_file": str(self._fake._project_path),
                    "is_active_project": True,
                }
            ]
        try:
            sessions = list_rot_sessions(version=self.config.aedt_version)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for sess in sessions:
            for item in sess.get("projects") or []:
                rec = dict(item)
                rec["process_id"] = sess.get("process_id")
                out.append(rec)
        return out

    def _find_open_project(
        self,
        project_name: str | None,
        project_path: str | None = None,
    ) -> dict[str, Any] | None:
        projects = self._gui_projects()
        if project_name:
            want = project_name.strip().lower()
            for item in projects:
                if str(item.get("project_name") or "").lower() == want:
                    return item
            if project_path:
                stem = Path(project_path).stem.lower()
                for item in projects:
                    if str(item.get("project_name") or "").lower() == stem:
                        return item
            return None
        active = next((item for item in projects if item.get("is_active_project")), None)
        if active is not None:
            return active
        if len(projects) == 1:
            return projects[0]
        return None

    def _drop_stale_live(self) -> None:
        if self.is_fake or self._live is None:
            return
        if self._find_open_project(self._live.project_name, self._live.project_path) is None:
            self._drop_session()

    def _detach_stale_allowlist(self) -> str | None:
        if self.is_fake or self._allowlist is None:
            return None
        if self._find_open_project(
            self._allowlist.project_name, self._allowlist.project_path
        ) is not None:
            return None
        dropped = self._allowlist.project_name
        self._allowlist = None
        return dropped

    def _try_restore_allowlist(self) -> None:
        if self._allowlist is not None or not self._persisted_allowlist_path:
            return
        try:
            loaded = load_allowlist_file(self._persisted_allowlist_path)
        except Exception:
            return
        if self.is_fake:
            self._allowlist = loaded
            return
        if self._find_open_project(loaded.project_name, loaded.project_path) is None:
            return
        if self._live is not None:
            self._allowlist = loaded
            if not self._allowlist_matches_session(loaded):
                self._allowlist = None
            return
        active = self._find_open_project(None)
        active_name = str((active or {}).get("project_name") or "")
        if active_name and active_name.lower() != loaded.project_name.lower():
            return
        self._allowlist = loaded

    def _bound_public(self) -> dict[str, Any] | None:
        if self.is_fake and self._fake is not None:
            return {
                "project_name": self._fake._project_name,
                "design_name": self._fake._design_name,
                "project_path": str(self._fake._project_path),
            }
        if self._live is None:
            return None
        return {
            "project_name": self._live.project_name,
            "design_name": self._live.design_name,
            "project_path": self._live.project_path,
            "process_id": self._live.process_id,
        }

    def _open_project_names(self) -> list[str]:
        names: list[str] = []
        for item in self._gui_projects():
            name = str(item.get("project_name") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    def _attach_gui(
        self,
        *,
        project_name: str | None = None,
        design_name: str | None = None,
    ) -> None:
        target = self._find_open_project(project_name)
        if target is None:
            names = self._open_project_names()
            if project_name:
                raise AdapterError(
                    f"Project {project_name!r} is not open. Open projects: {names or '(none)'}",
                    code="project_not_open",
                    details={"project_name": project_name, "open_projects": names},
                )
            if len(names) > 1:
                raise AdapterError(
                    "Multiple projects are open; pass project_name to session_attach",
                    code="aedt_session_ambiguous",
                    details={"open_projects": names},
                )
            sessions: list[Any] = []
            try:
                sessions = list_rot_sessions(version=self.config.aedt_version)
            except Exception:
                sessions = []
            if not sessions:
                raise AdapterError(
                    "No COM-visible AEDT Desktop is running. Start Electronics Desktop "
                    "and keep the project open, then retry. This server will not launch "
                    "a second Desktop.",
                    code="aedt_not_running",
                )
            raise AdapterError(
                "AEDT is running but no project is open",
                code="no_open_project",
            )
        designs = [str(x) for x in (target.get("designs") or []) if str(x).strip()]
        chosen_design = design_name or (designs[0] if designs else None)
        self._live = attach_live(
            version=self.config.aedt_version,
            process_id=target.get("process_id"),
            project_name=str(target.get("project_name") or ""),
            design_name=chosen_design,
        )
        self._restore_view_hidden()

    def health(self) -> dict[str, Any]:
        env = inspect_environment()
        preferred = env.preferred
        real_ready = (
            self.config.adapter == "pyaedt"
            and preferred is not None
            and preferred.exe_exists
        )
        from hfss_mcp import __version__ as pkg_version

        if not self.is_fake:
            self._drop_stale_live()
        self._try_restore_allowlist()
        if not self.is_fake:
            self._detach_stale_allowlist()
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
            "bound": self._bound_public(),
            "open_projects": self._open_project_names(),
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
            return {
                "ok": True,
                "connection_mode": "in_process_fake",
                "sessions": [],
                "count": 0,
                "bound": self._bound_public(),
                "open_projects": self._open_project_names(),
                "allowlist_loaded": self._allowlist is not None,
            }
        self._drop_stale_live()
        self._try_restore_allowlist()
        dropped = self._detach_stale_allowlist()
        rot = list_rot_sessions(version=self.config.aedt_version)
        discovery = discover_running_sessions(version=self.config.aedt_version)
        active = self._find_open_project(None)
        payload: dict[str, Any] = {
            "ok": True,
            "connection_mode": "com_attach_live",
            "sessions": rot,
            "count": len(rot),
            "lock_discovery": discovery.to_public_dict(),
            "bound": self._bound_public(),
            "active": (
                None
                if active is None
                else {
                    "project_name": active.get("project_name"),
                    "designs": active.get("designs") or [],
                    "project_file": active.get("project_file") or active.get("project_path"),
                    "process_id": active.get("process_id"),
                }
            ),
            "open_projects": self._open_project_names(),
            "allowlist_loaded": self._allowlist is not None,
        }
        if dropped:
            payload["allowlist_dropped"] = dropped
            payload["note"] = (
                f"allowlist was for {dropped!r}, which is no longer open. "
                "session_attach the project in the GUI, then allowlist_load."
            )
        return payload

    def session_attach(
        self,
        project_name: str | None = None,
        design_name: str | None = None,
    ) -> dict[str, Any]:
        """Bind MCP to an already-open GUI project. Never reopens a closed file."""
        if self.is_fake:
            self._ensure_session(write=True)
            return {
                "ok": True,
                "bound": self._bound_public(),
                "allowlist_loaded": self._allowlist is not None,
                "open_projects": self._open_project_names(),
                "note": "demo_fake has no GUI project switch",
            }
        self._drop_session()
        self._attach_gui(project_name=project_name, design_name=design_name)
        dropped = None
        if self._allowlist is not None and not self._allowlist_matches_session(self._allowlist):
            dropped = self._allowlist.project_name
            self._allowlist = None
        payload: dict[str, Any] = {
            "ok": True,
            "bound": self._bound_public(),
            "allowlist_loaded": self._allowlist is not None,
            "open_projects": self._open_project_names(),
        }
        if dropped:
            payload["allowlist_dropped"] = dropped
            payload["note"] = (
                f"dropped allowlist for {dropped!r}; allowlist_load for "
                f"{(self._bound_public() or {}).get('project_name')}"
            )
        return payload

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
        if not self.is_fake:
            self._drop_stale_live()
            if self._find_open_project(loaded.project_name, loaded.project_path) is None:
                names = self._open_project_names()
                raise PolicyError(
                    f"allowlist is for {loaded.project_name!r}, which is not open. "
                    f"Open projects: {names or '(none)'}. "
                    "Open that project in AEDT, or session_attach the GUI project "
                    "and load its allowlist.",
                    code="allowlist_project_not_open",
                    details={
                        "allowlist_project": loaded.project_name,
                        "open_projects": names,
                    },
                )
        self._allowlist = loaded
        if path:
            self._persisted_allowlist_path = str(Path(path).resolve())
            self._save_state()
        if not self._allowlist_matches_session(loaded):
            if self._live is not None or self._fake is not None:
                self._drop_session()
        if not self.is_fake and self._find_open_project(loaded.project_name, loaded.project_path):
            self._attach_gui(
                project_name=loaded.project_name,
                design_name=loaded.design_name,
            )
        return {
            "ok": True,
            "allowlist_id": loaded.allowlist_id(),
            "project_name": loaded.project_name,
            "design_name": loaded.design_name,
            "parameters": [p.model_dump(by_alias=True) for p in loaded.parameters],
            "constraints": list(loaded.constraints),
            "default_setup": loaded.default_setup,
            "bound": self._bound_public(),
            "open_projects": self._open_project_names(),
        }

    def _require_allowlist(self) -> Allowlist:
        if not self.is_fake:
            self._drop_stale_live()
            self._detach_stale_allowlist()
        self._try_restore_allowlist()
        if self._allowlist is None:
            raise PolicyError(
                "load an allowlist first (allowlist_load)",
                code="allowlist_not_loaded",
            )
        return self._allowlist

    def _ensure_session(self, *, write: bool = True) -> None:
        if not self.is_fake:
            self._drop_stale_live()
            self._detach_stale_allowlist()
        if write:
            allowlist = self._require_allowlist()
            if not self.is_fake:
                hit = self._find_open_project(allowlist.project_name, allowlist.project_path)
                if hit is None:
                    names = self._open_project_names()
                    raise PolicyError(
                        f"allowlist project {allowlist.project_name!r} is not open. "
                        f"Open projects: {names or '(none)'}. "
                        "session_attach the GUI project, then allowlist_load.",
                        code="allowlist_project_not_open",
                        details={
                            "allowlist_project": allowlist.project_name,
                            "open_projects": names,
                        },
                    )
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
                                name=p.name,
                                value=(p.min_value + p.max_value) / 2.0,
                                unit=p.unit,
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
                self._restore_view_hidden()
                return
            if self._live is None:
                self._attach_gui(
                    project_name=allowlist.project_name,
                    design_name=allowlist.design_name,
                )
            return

        if self.is_fake:
            self._require_allowlist()
            self._ensure_session(write=True)
            return
        self._follow_active_gui()
        if self._allowlist is not None and self._live is not None:
            if not self._allowlist_matches_session(self._allowlist):
                self._allowlist = None

    def _follow_active_gui(self) -> None:
        if self.is_fake:
            return
        self._drop_stale_live()
        active = self._find_open_project(None)
        name = str((active or {}).get("project_name") or "")
        if self._live is not None and (not name or self._live.project_name != name):
            self._drop_session()
        if self._live is None:
            self._attach_gui()

    def snapshot(self) -> dict[str, Any]:
        self._ensure_session(write=False)
        if self.is_fake:
            assert self._fake is not None
            snap = self._fake.snapshot()
            payload = snap.model_dump()
        else:
            assert self._live is not None
            payload = self._live.snapshot()
        if self._allowlist is not None and not self._allowlist_matches_session(self._allowlist):
            dropped = self._allowlist.project_name
            self._allowlist = None
        else:
            dropped = None
        out: dict[str, Any] = {
            "ok": True,
            "snapshot": payload,
            "bound": self._bound_public(),
            "allowlist_loaded": self._allowlist is not None,
        }
        if dropped:
            out["allowlist_dropped"] = dropped
            out["note"] = (
                f"GUI project does not match allowlist {dropped!r}; "
                "allowlist_load for the open project before mutations."
            )
        return out

    def _solve_running(self) -> dict[str, Any] | None:
        with self._job_lock:
            for job in self._jobs.values():
                if job["state"] == JobState.RUNNING.value:
                    return job
        return None

    def _guard_no_solve(self, tool: str) -> None:
        """Fail fast instead of queueing behind a running sweep in AEDT.

        AEDT defers mutating RunScript calls until the current solve ends.
        A deferred call occupies AEDT's COM queue, so every later call -
        including analyze_status progress polls - stalls behind it for the
        whole sweep. Report the conflict immediately instead.
        """
        job = self._solve_running()
        if job is None:
            return
        raise JobError(
            f"{tool} is blocked while a solve is running: AEDT defers this "
            "call until the sweep ends and every later call would queue "
            "behind it. Poll analyze_status, peek with report_export, or "
            "wait for done. Set variables BEFORE parametric_start.",
            code="solve_in_progress",
            details={"job_id": job.get("job_id"), "state": job.get("state")},
        )

    def _persist_jobs(self) -> None:
        with self._job_lock:
            snapshot = {key: dict(value) for key, value in self._jobs.items()}
        self._ledger.save_jobs(snapshot)

    def _variable_floats(self) -> dict[str, float]:
        payload = self.snapshot()["snapshot"]
        variables = payload.get("variables") or {}
        out: dict[str, float] = {}
        items = variables.items() if isinstance(variables, dict) else []
        for name, item in items:
            if isinstance(item, dict) and item.get("value") is not None:
                try:
                    out[str(name)] = float(item["value"])
                except (TypeError, ValueError):
                    continue
            elif hasattr(item, "value"):
                try:
                    out[str(name)] = float(item.value)
                except (TypeError, ValueError):
                    continue
        return out

    def _geometry_failed(self, messages: list[str] | None) -> bool:
        return any("body could not be created" in str(line).lower() for line in messages or [])

    def _record_job_points(self, rec: dict[str, Any], *, geometry_failed: bool = False) -> None:
        rows = list(rec.get("rows") or [])
        context = rec.get("context") if isinstance(rec.get("context"), dict) else {}
        if not rows:
            if context:
                rows = [dict(context)]
            else:
                return
        source = str(rec.get("setup") or rec.get("kind") or "analyze")
        for row in rows:
            self._ledger.append_point(
                {
                    "project": rec.get("project"),
                    "design": rec.get("design"),
                    "source": source,
                    "kind": rec.get("kind"),
                    "job_id": rec.get("job_id"),
                    "setup": rec.get("setup"),
                    "variables": dict(row),
                    "geometry_failed": bool(geometry_failed or rec.get("geometry_failed")),
                    "started_at": rec.get("started_at"),
                    "finished_at": rec.get("finished_at"),
                }
            )

    def _new_job_record(
        self,
        *,
        kind: str,
        setup: str,
        points: int | None = None,
        context: dict[str, float] | None = None,
        rows: list[dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        allowlist = self._allowlist
        rec: dict[str, Any] = {
            "job_id": new_id("job_"),
            "kind": kind,
            "state": JobState.RUNNING.value,
            "setup": setup,
            "created_at": utc_now_iso(),
            "started_at": utc_now_iso(),
            "finished_at": None,
            "error": None,
            "project": None if allowlist is None else allowlist.project_name,
            "design": None if allowlist is None else allowlist.design_name,
            "source": setup,
        }
        if points is not None:
            rec["points"] = points
        if context is not None:
            rec["context"] = dict(context)
        if rows is not None:
            rec["rows"] = [dict(row) for row in rows]
        return rec

    def _finish_job(
        self,
        rec: dict[str, Any],
        *,
        state: str,
        error: dict[str, Any] | None = None,
        geometry_failed: bool = False,
        messages: list[str] | None = None,
    ) -> None:
        rec["state"] = state
        rec["finished_at"] = utc_now_iso()
        rec["error"] = error
        if messages:
            rec["messages"] = list(messages)[-8:]
        if geometry_failed:
            rec["geometry_failed"] = True
        if state in {JobState.COMPLETED.value, JobState.FAILED.value}:
            self._record_job_points(rec, geometry_failed=geometry_failed)
        self._persist_jobs()

    def _reconcile_running_job(self, rec: dict[str, Any]) -> None:
        if rec.get("state") != JobState.RUNNING.value:
            return
        if self.is_fake:
            return
        try:
            self._ensure_session(write=False)
        except Exception:
            return
        if self._live is None:
            return
        try:
            messages = self._live.read_messages(limit=48)
        except Exception:
            messages = []
        rec["messages"] = messages[-8:]
        fail = failure_message_for_setup(messages, str(rec.get("setup") or ""))
        if not fail and rec.get("kind") == "parametric":
            fail = crash_message(messages)
        if fail:
            self._finish_job(
                rec,
                state=JobState.FAILED.value,
                error={"code": "hfss_message", "message": fail},
                geometry_failed=self._geometry_failed(messages),
                messages=messages,
            )
            return
        if rec.get("kind") == "parametric":
            try:
                listed = self._optimetrics_setups()
            except Exception:
                return
            match = next((item for item in listed if item.get("name") == rec.get("setup")), None)
            if match and match.get("has_result"):
                self._variables_dirty = False
                self._finish_job(
                    rec,
                    state=JobState.COMPLETED.value,
                    geometry_failed=self._geometry_failed(messages),
                    messages=messages,
                )

    def variables_set(self, parameters: list[dict[str, Any]]) -> dict[str, Any]:
        self._guard_no_solve("variables_set")
        allowlist = self._require_allowlist()
        self._ensure_session()
        values = [ParameterValue.model_validate(item) for item in parameters]
        if not values:
            raise PolicyError("parameters must be non-empty", code="empty_parameters")
        for item in values:
            assert_writable(allowlist, item.name, item.value, item.unit)
        merged = self._variable_floats()
        for item in values:
            merged[item.name] = item.value
        assert_constraints(allowlist.constraints, merged, where="variables_set")
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
            rec = self._new_job_record(
                kind="analyze",
                setup=setup_name,
                points=1,
                context=self._variable_floats(),
                rows=[self._variable_floats()],
            )
            self._jobs[rec["job_id"]] = rec
        self._persist_jobs()

        if self.is_fake:
            assert self._fake is not None
            self._fake.start_solve(setup_name)
            self._variables_dirty = False
            self._finish_job(rec, state=JobState.COMPLETED.value)
            return self._job_payload(rec)

        def _run() -> None:
            try:
                assert self._live is not None
                self._live.analyze(setup_name)
                try:
                    messages = self._live.read_messages(limit=48)
                except Exception:
                    messages = []
                with self._job_lock:
                    self._variables_dirty = False
                    self._finish_job(
                        rec,
                        state=JobState.COMPLETED.value,
                        geometry_failed=self._geometry_failed(messages),
                        messages=messages,
                    )
            except Exception as exc:
                with self._job_lock:
                    self._finish_job(
                        rec,
                        state=JobState.FAILED.value,
                        error={
                            "code": getattr(exc, "code", "analyze_failed"),
                            "message": str(exc),
                        },
                    )

        self._analyze_thread = threading.Thread(target=_run, name="hfss-analyze", daemon=True)
        self._analyze_thread.start()
        return self._job_payload(rec)

    def analyze_status(self, job_id: str) -> dict[str, Any]:
        rec = self._jobs.get(job_id)
        if rec is None:
            restored = self._ledger.load_jobs()
            if job_id in restored:
                rec = restored[job_id]
                self._jobs[job_id] = rec
        if rec is None:
            raise JobError(
                f"job not found: {job_id}",
                code="job_not_found",
                details={
                    "hint": "jobs persist under the data dir as jobs.json. If this "
                    "id is missing, the solve may still be running in AEDT — poll "
                    "report_export / optimetrics_list, or call solved_points_list."
                },
            )
        self._reconcile_running_job(rec)
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
                rec["geometry_failed"] = self._geometry_failed(messages)
                self._record_job_points(rec, geometry_failed=rec["geometry_failed"])
                self._persist_jobs()
                payload["done"] = True
                payload["poll"] = None
        payload["job"] = rec
        return payload

    def analyze_cancel(self, job_id: str) -> dict[str, Any]:
        rec = self._jobs.get(job_id)
        if rec is None:
            raise JobError(
                f"job not found: {job_id}",
                code="job_not_found",
                details={
                    "hint": "jobs persist under the data dir as jobs.json. If this "
                    "id is missing, the solve may still be running in AEDT — poll "
                    "report_export / optimetrics_list, or call solved_points_list."
                },
            )
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
        self._ensure_session(write=False)
        setups = self._optimetrics_setups()
        for item in setups:
            if item.get("variables"):
                continue
            cached = self._parametric_vars.get(str(item.get("name") or ""))
            if cached:
                item["variables"] = list(cached)
        return {"ok": True, "setups": setups}

    def _build_parametric_plan(self, sweeps: list[dict[str, Any]]) -> dict[str, Any]:
        allowlist = self._require_allowlist()
        if not sweeps:
            raise PolicyError(
                "parametric needs at least one sweep",
                code="parametric_sweep_required",
            )
        table_entries = [
            raw
            for raw in sweeps
            if str(raw.get("variation") or "") == "table" or raw.get("rows")
        ]
        if table_entries and len(table_entries) != len(sweeps):
            raise PolicyError(
                "table variation must be the only sweep entry",
                code="parametric_sweep_invalid",
            )
        current = self._variable_floats()
        if table_entries:
            return self._plan_table_sweep(table_entries[0], allowlist, current)
        return self._plan_cartesian_sweeps(sweeps, allowlist, current)

    def _plan_table_sweep(
        self,
        raw: dict[str, Any],
        allowlist: Allowlist,
        current: dict[str, float],
    ) -> dict[str, Any]:
        units = {p.name: p.unit for p in allowlist.parameters}
        order, numeric_rows, unit_map = expand_table_rows(
            list(raw.get("rows") or []),
            allowed=allowlist.names(),
            units=units,
        )
        for row in numeric_rows:
            for name, value in row.items():
                assert_writable(allowlist, name, value, unit_map[name])
        swept = set(order)
        context = {
            name: current[name]
            for name in allowlist.names()
            if name not in swept and name in current
        }
        merged = [{**context, **row} for row in numeric_rows]
        assert_constraints_on_rows(
            allowlist.constraints, merged, where="parametric_create"
        )
        if len(numeric_rows) > PARAMETRIC_MAX_POINTS:
            raise PolicyError(
                f"parametric would run {len(numeric_rows)} points; max is {PARAMETRIC_MAX_POINTS}",
                code="parametric_too_many_points",
                details={"points": len(numeric_rows), "max": PARAMETRIC_MAX_POINTS},
            )
        formatted = [
            {
                "variable": name,
                "data": " ".join(f"{row[name]}{unit_map[name]}" for row in numeric_rows),
            }
            for name in order
        ]
        return {
            "formatted": formatted,
            "points": len(numeric_rows),
            "sync_indices": list(range(len(order))),
            "table_rows": numeric_rows,
            "rows": merged,
            "context": context,
            "variables": order,
        }

    def _plan_cartesian_sweeps(
        self,
        sweeps: list[dict[str, Any]],
        allowlist: Allowlist,
        current: dict[str, float],
    ) -> dict[str, Any]:
        formatted: list[dict[str, str]] = []
        axes: dict[str, list[float]] = {}
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
                lo, hi = (start, stop) if start <= stop else (stop, start)
                values = lin_values(lo, hi, step)
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
                values = linc_values(start, stop, count)
                assert_writable(allowlist, name, start, unit)
                assert_writable(allowlist, name, stop, unit)
                lo, hi = (start, stop) if start <= stop else (stop, start)
                data = f"LINC {lo}{unit} {hi}{unit} {count}"
            else:
                raise PolicyError(
                    f"unsupported variation {variation!r}; "
                    "use linear_step, linear_count, values, or table",
                    code="parametric_variation_unsupported",
                    details={"allowed": ["linear_step", "linear_count", "values", "table"]},
                )
            n_points = len(values)
            total_points *= n_points
            axes[name] = values
            formatted.append({"variable": name, "data": data})
        if total_points > PARAMETRIC_MAX_POINTS:
            raise PolicyError(
                f"parametric would run {total_points} points; max is {PARAMETRIC_MAX_POINTS}",
                code="parametric_too_many_points",
                details={"points": total_points, "max": PARAMETRIC_MAX_POINTS},
            )
        cartesian = cartesian_from_axes(axes)
        swept = set(axes)
        context = {
            name: current[name]
            for name in allowlist.names()
            if name not in swept and name in current
        }
        merged = [{**context, **row} for row in cartesian]
        assert_constraints_on_rows(
            allowlist.constraints, merged, where="parametric_create"
        )
        return {
            "formatted": formatted,
            "points": total_points,
            "sync_indices": [],
            "table_rows": cartesian,
            "rows": merged,
            "context": context,
            "variables": list(axes.keys()),
        }

    def parametric_create(
        self,
        *,
        name: str | None = None,
        setup: str | None = None,
        sweeps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._guard_no_solve("parametric_create")
        allowlist = self._require_allowlist()
        self._ensure_session()
        plan = self._build_parametric_plan(list(sweeps or []))
        formatted = plan["formatted"]
        points = int(plan["points"])
        setup_name = setup or allowlist.default_setup or "Setup1"
        report_name = name or f"Parametric_{formatted[0]['variable']}"
        sync_indices = list(plan.get("sync_indices") or [])
        if self.is_fake:
            assert self._fake is not None
            rec = self._fake.create_parametric(
                name=report_name,
                sim_setup=setup_name,
                sweeps=formatted,
                sync_indices=sync_indices,
                table_rows=list(plan.get("table_rows") or []),
            )
        else:
            assert self._live is not None
            rec = self._live.create_parametric(
                name=report_name,
                sim_setup=setup_name,
                sweeps=formatted,
                sync_indices=sync_indices,
            )
        rec["sim_setup"] = setup_name
        rec["sweeps"] = formatted
        rec["points"] = points
        rec["variables"] = list(plan["variables"])
        rec["sync_indices"] = sync_indices
        rec["context"] = dict(plan["context"])
        self._parametric_vars[report_name] = list(rec["variables"])
        self._parametric_meta[report_name] = {
            "variables": list(rec["variables"]),
            "context": dict(plan["context"]),
            "rows": [dict(row) for row in plan["rows"]],
            "points": points,
            "sync_indices": sync_indices,
        }
        self._save_state()
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
        meta = self._parametric_meta.get(name) or {}
        with self._job_lock:
            running = [j for j in self._jobs.values() if j["state"] == JobState.RUNNING.value]
            if running:
                raise JobError(
                    "an analyze job is already running",
                    code="analyze_busy",
                    details={"job_id": running[0]["job_id"]},
                )
            rec = self._new_job_record(
                kind="parametric",
                setup=name,
                points=meta.get("points"),
                context=meta.get("context") or self._variable_floats(),
                rows=list(meta.get("rows") or []),
            )
            self._jobs[rec["job_id"]] = rec
        self._persist_jobs()
        if self.is_fake:
            self._variables_dirty = False
            self._finish_job(rec, state=JobState.COMPLETED.value)
            return self._job_payload(rec)

        def _run() -> None:
            try:
                assert self._live is not None
                self._live.analyze_parametric(name)
                try:
                    messages = self._live.read_messages(limit=48)
                except Exception:
                    messages = []
                with self._job_lock:
                    self._variables_dirty = False
                    self._finish_job(
                        rec,
                        state=JobState.COMPLETED.value,
                        geometry_failed=self._geometry_failed(messages),
                        messages=messages,
                    )
            except Exception as exc:
                with self._job_lock:
                    self._finish_job(
                        rec,
                        state=JobState.FAILED.value,
                        error={
                            "code": getattr(exc, "code", "analyze_failed"),
                            "message": str(exc),
                        },
                    )

        self._analyze_thread = threading.Thread(target=_run, name="hfss-parametric", daemon=True)
        self._analyze_thread.start()
        return self._job_payload(rec)

    def _annotate_parametric_table(
        self,
        dest: Path,
        *,
        context: dict[str, float],
        swept: list[str],
    ) -> dict[str, float]:
        extra = {name: context[name] for name in context if name not in swept}
        if not extra or not dest.is_file():
            return extra
        try:
            rows = list(
                csv.reader(dest.read_text(encoding="utf-8", errors="replace").splitlines())
            )
        except Exception:
            return extra
        if not rows:
            return extra
        header = [str(cell).strip() for cell in rows[0]]
        extra_names = [name for name in extra if name not in header]
        if not extra_names:
            return extra
        written = [header + extra_names]
        for raw in rows[1:]:
            if not raw or all(not str(cell).strip() for cell in raw):
                continue
            padded = [str(cell) for cell in raw]
            if len(padded) < len(header):
                padded.extend([""] * (len(header) - len(padded)))
            padded = padded[: len(header)]
            padded.extend(str(extra[name]) for name in extra_names)
            written.append(padded)
        with dest.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(written)
        return extra

    def parametric_export_table(self, name: str) -> dict[str, Any]:
        self._ensure_session(write=False)
        dest = self.artifacts_dir / f"{new_id('art_')}_parametric.csv"
        if self.is_fake:
            assert self._fake is not None
            dest = self._fake.export_parametric_table(name, dest)
        else:
            assert self._live is not None
            dest = self._live.export_parametric_table(name, dest)
        meta = self._parametric_meta.get(name) or {}
        swept = list(meta.get("variables") or self._parametric_vars.get(name) or [])
        context = dict(meta.get("context") or {})
        extra = self._annotate_parametric_table(dest, context=context, swept=swept)
        return {
            "ok": True,
            "name": name,
            "path": str(dest),
            "format": "csv",
            "context": extra,
            "swept": swept,
        }

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
        self._ensure_session(write=False)
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
        self._guard_no_solve("report_create")
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

    def report_export(
        self,
        report_id: str,
        *,
        path: str | None = None,
        summarize: dict[str, Any] | bool | None = None,
        png: bool = False,
    ) -> dict[str, Any]:
        self._ensure_session(write=False)
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
            dest = self._resolve_export_path(path, suffix=".jpg", default="field_face")
            if self.is_fake:
                assert self._fake is not None
                dest = self._fake.export_results_report(
                    listed_name, dest, report_type="field_face"
                )
            else:
                assert self._live is not None
                dest = self._live.export_field_overlay(listed_name, dest)
            dest = self._copy_if_requested(dest, path, suffix=".jpg")
            out = rec or dict(listed_item)
            out["artifact"] = str(dest)
            out["format"] = "image"
            self._reports[listed_name] = out
            return {"ok": True, "report": out, "path": str(dest), "format": "image"}
        dest = self._resolve_export_path(path, suffix=".csv", default=str(kind or "report"))
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
        dest = self._copy_if_requested(dest, path, suffix=".csv")
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
        csv_shape: dict[str, Any] = {}
        if dest.suffix.lower() == ".csv":
            csv_shape = csv_export_summary(dest)
            payload["traces"] = csv_shape.get("traces")
            payload["labeled"] = csv_shape.get("labeled")
            payload["csv_format"] = csv_shape.get("format")
            payload["header"] = csv_shape.get("header")
        if summarize:
            payload["summary"] = self._summarize_report(
                dest, kind=kind, csv_shape=csv_shape, summarize=summarize
            )
        if png:
            png_dest = dest.with_suffix(".png")
            mark = None
            if isinstance(summarize, dict) and summarize.get("target_ghz") is not None:
                mark = float(summarize["target_ghz"])
            try:
                render_s11_png(dest, png_dest, mark_ghz=mark)
                payload["png"] = str(png_dest)
            except Exception as exc:
                payload["png_error"] = {
                    "code": getattr(exc, "code", "png_failed"),
                    "message": str(exc),
                }
        if self._variables_dirty:
            payload["stale_solution"] = True
            payload["note"] = (
                "variables_set has not been solved. This CSV is the last solved "
                "variation, not the current design values. Analyze, or export a "
                "family trace that already contains this point."
            )
        return payload

    def _resolve_export_path(self, path: str | None, *, suffix: str, default: str) -> Path:
        if path:
            dest = Path(path)
            if dest.suffix.lower() == "":
                dest = dest.with_suffix(suffix)
            dest.parent.mkdir(parents=True, exist_ok=True)
            return dest
        return self.artifacts_dir / f"{new_id('art_')}_{default}{suffix}"

    def _copy_if_requested(self, dest: Path, path: str | None, *, suffix: str) -> Path:
        if not path:
            return dest
        wanted = Path(path)
        if wanted.suffix.lower() == "":
            wanted = wanted.with_suffix(suffix)
        wanted.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() != wanted.resolve() and dest.is_file():
            shutil.copy2(dest, wanted)
            return wanted
        return dest

    def _summarize_report(
        self,
        dest: Path,
        *,
        kind: str | None,
        csv_shape: dict[str, Any],
        summarize: dict[str, Any] | bool,
    ) -> dict[str, Any]:
        if summarize is True:
            raise PolicyError(
                "summarize needs an object with target_ghz",
                code="summarize_args",
            )
        if not isinstance(summarize, dict):
            raise PolicyError("summarize must be an object", code="summarize_args")
        if summarize.get("target_ghz") is None:
            raise PolicyError("summarize needs target_ghz", code="summarize_args")
        target = float(summarize["target_ghz"])
        threshold = float(summarize.get("threshold_db", -10.0))
        fmt = csv_shape.get("format")
        if kind == "terminal_z" or fmt == "terminal_z":
            return summarize_terminal_z_csv(dest, target_ghz=target)
        return summarize_modal_s_csv(
            dest, target_ghz=target, threshold_db=threshold
        )

    def solved_points_list(
        self,
        *,
        source: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        project = None
        design = None
        if self._allowlist is not None:
            project = self._allowlist.project_name
            design = self._allowlist.design_name
        points = self._ledger.list_points(
            project=project, design=design, source=source, limit=limit
        )
        return {"ok": True, "points": points, "count": len(points)}

    def view_hide(self, names: list[str]) -> dict[str, Any]:
        cleaned = [str(x).strip() for x in names if str(x).strip()]
        if not cleaned:
            raise PolicyError("names must be non-empty", code="empty_parameters")
        self._ensure_session(write=False)
        if self.is_fake:
            self._view_hidden.update(cleaned)
            self._persist_view_hidden()
            return {
                "ok": True,
                "hidden": sorted(self._view_hidden),
                "names": cleaned,
                "missing": [],
            }
        assert self._live is not None
        raw = self._live.view_set_visible(cleaned, show=False)
        self._view_hidden.update(raw["names"])
        self._persist_view_hidden()
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
        self._ensure_session(write=False)
        if self.is_fake:
            if all_objects:
                shown = sorted(self._view_hidden)
                self._view_hidden.clear()
            else:
                shown = cleaned
                self._view_hidden.difference_update(cleaned)
            self._persist_view_hidden()
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
        self._persist_view_hidden()
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
        self._ensure_session(write=False)
        o = (orientation or "isometric").strip().lower()
        if o not in VIEW_ORIENTATIONS:
            raise PolicyError(
                f"orientation must be one of: {', '.join(VIEW_ORIENTATIONS)}",
                code="orientation_invalid",
                details={"valid": list(VIEW_ORIENTATIONS), "got": orientation},
            )
        dest = self.artifacts_dir / f"view_{new_id('')[:10]}.jpg"
        keep = [str(x).strip() for x in (fit or isolate or []) if str(x).strip()]
        hidden_in_fit = sorted({name for name in keep if name in self._view_hidden})
        warning = None
        if hidden_in_fit:
            warning = (
                "fit includes objects in the view_hide set: "
                + ", ".join(hidden_in_fit)
            )
        if self.is_fake:
            dest.write_bytes(_FAKE_JPEG)
            payload = {
                "ok": True,
                "path": str(dest),
                "orientation": o,
                "fit": keep,
                "isolate": isolate or [],
                "hidden": sorted(self._view_hidden),
                "selection": keep,
                "missing": [],
            }
            if warning:
                payload["warning"] = warning
                payload["hidden_in_fit"] = hidden_in_fit
            return payload
        assert self._live is not None
        path, selection, fitted, missing = self._live.view_capture(
            dest,
            orientation=o,
            fit=keep or None,
            isolate=None,
            hidden=sorted(self._view_hidden),
        )
        payload = {
            "ok": True,
            "path": str(path),
            "orientation": o,
            "fit": fitted,
            "isolate": isolate or [],
            "hidden": sorted(self._view_hidden),
            "selection": selection,
            "missing": missing,
        }
        if warning:
            payload["warning"] = warning
            payload["hidden_in_fit"] = hidden_in_fit
        return payload

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
        self._ensure_session(write=False)
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
    constraints: list[str] | None = None,
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
            "constraints": list(constraints or []),
        }
    )
