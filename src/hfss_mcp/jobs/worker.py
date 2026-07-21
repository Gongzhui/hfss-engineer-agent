"""Worker process entry: exclusive AEDT session for one trial job."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.jobs.trial_exec import execute_trial
from hfss_mcp.manifest import load_manifest


def run_worker(
    *,
    db_path: Path,
    job_id: str,
    adapter_name: str,
    aedt_version: str,
    non_graphical: bool,
    workspace_root: Path,
) -> int:
    store = JobStore(db_path, recover=False)
    try:
        job = store.get(job_id)
        if job is None:
            print(json.dumps({"ok": False, "error": "job_not_found"}), flush=True)
            return 2
        body = store.get_manifest_body(job.manifest_id)
        if body is None:
            store.transition(
                job_id,
                __import__("hfss_mcp.domain", fromlist=["JobState"]).JobState.FAILED,
                error={"code": "manifest_missing", "message": "manifest not in store"},
            )
            return 3
        manifest = load_manifest(body)
        payload = job.input_payload
        working = Path(payload["working_project"])
        original = Path(payload["original_project"])
        original_sha = str(payload["original_sha256"])

        store.heartbeat(job_id, worker_pid=os.getpid())

        adapter: Any
        if adapter_name == "fake":
            from hfss_mcp.adapter.fake import FakeAdapter
            from hfss_mcp.domain import ParameterValue

            adapter = FakeAdapter(
                project_path=working,
                project_name=manifest.project_name,
                design_name=manifest.design_name,
                variables={
                    p.name: ParameterValue(
                        name=p.name,
                        value=(p.min_value + p.max_value) / 2,
                        unit=p.unit,
                    )
                    for p in manifest.parameters
                },
                setups=[s.setup for s in manifest.allowed_setups],
                solve_duration_s=0.05,
            )
        else:
            from hfss_mcp.adapter.pyaedt_adapter import PyAedtAdapter

            payload = job.input_payload
            attach_mode = bool(payload.get("attach_mode"))
            attach_pid = payload.get("aedt_process_id")
            attach_port = payload.get("grpc_port")
            if attach_mode and attach_pid:
                adapter = PyAedtAdapter(
                    version=aedt_version,
                    non_graphical=False,
                    new_desktop=False,
                    close_on_exit=False,
                    aedt_process_id=int(attach_pid),
                    grpc_port=int(attach_port) if attach_port else None,
                )
            else:
                adapter = PyAedtAdapter(
                    version=aedt_version,
                    non_graphical=non_graphical,
                    new_desktop=True,
                    close_on_exit=True,
                )

        ckpt_dir = workspace_root / "checkpoints"
        if manifest.checkpoint.directory:
            ckpt_dir = Path(manifest.checkpoint.directory)
        checkpoints = CheckpointService(ckpt_dir)

        try:
            result = execute_trial(
                store=store,
                job_id=job_id,
                manifest=manifest,
                adapter=adapter,
                checkpoints=checkpoints,
                working_project=working,
                original_project=original,
                original_sha256=original_sha,
            )
            print(
                json.dumps({"ok": True, "result_state": result.get("state")}),
                flush=True,
            )
            return 0 if result.get("state") in {"completed", "cancelled"} or result.get(
                "metrics"
            ) else (0 if result.get("state") == "completed" else 1)
        finally:
            try:
                adapter.disconnect(close_desktop=True)
            except Exception:
                pass
            # Kill any leftover owned pids for pyaedt
            owned = getattr(adapter, "owned_aedt_pids", None)
            if callable(owned):
                pids = owned()
                for pid in pids:
                    try:
                        import subprocess

                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                            timeout=20,
                        )
                    except Exception:
                        pass
    except Exception as exc:  # noqa: BLE001
        try:
            from hfss_mcp.domain import JobState

            store.transition(
                job_id,
                JobState.FAILED,
                error={
                    "code": "worker_crash",
                    "message": str(exc),
                    "traceback": traceback.format_exc()[-2000:],
                },
            )
        except Exception:
            pass
        print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
        return 1
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hfss-mcp trial worker")
    parser.add_argument("--db", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--adapter", default=os.environ.get("HFSS_MCP_ADAPTER", "pyaedt"))
    parser.add_argument("--aedt-version", default=os.environ.get("HFSS_MCP_AEDT_VERSION", "2023.2"))
    parser.add_argument("--non-graphical", default="1")
    parser.add_argument("--workspace-root", required=True)
    args = parser.parse_args(argv)
    return run_worker(
        db_path=Path(args.db),
        job_id=args.job_id,
        adapter_name=args.adapter,
        aedt_version=args.aedt_version,
        non_graphical=str(args.non_graphical) not in {"0", "false", "no"},
        workspace_root=Path(args.workspace_root),
    )


if __name__ == "__main__":
    sys.exit(main())
