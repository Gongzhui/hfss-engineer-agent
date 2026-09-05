"""Opt-in real AEDT regression on a disposable copy of golden_patch.

Run only when the user's Desktop is idle. Never runs against the exam project.
Uses real MCP stdio for start/poll/report; leaves evidence under scratch/.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from benchmark.aedt_text import strip_aedt_text
from hfss_mcp.com_session import get_desktop, open_project_on_desktop

ROOT = Path(__file__).resolve().parents[1]


async def verify(dest: Path, project: Path) -> dict[str, Any]:
    env = dict(
        os.environ,
        HFSS_MCP_ADAPTER="pyaedt",
        HFSS_MCP_DEMO="0",
        HFSS_MCP_DATA_DIR=str(dest / "data"),
    )
    async with (
        stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "hfss_mcp.server"],
                env=env,
            )
        ) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()

        async def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            async with asyncio.timeout(30):
                result = await client.call_tool(name, args)
            payload = result.structuredContent or json.loads(result.content[0].text)
            assert payload.get("ok"), payload
            return dict(payload)

        await call(
            "allowlist_load",
            {
                "allowlist": {
                    "project_path": str(project),
                    "project_name": project.stem,
                    "design_name": "HFSSDesign1",
                    "default_setup": "Setup1",
                    "parameters": [{"name": "gap", "unit": "mm", "min": 0.5, "max": 3.0}],
                }
            },
        )
        evidence: dict[str, Any] = {"project": str(project), "phases": []}

        async def solve(name: str, args: dict[str, Any]) -> None:
            started = await call(name, args)
            job_id = started["job_id"]
            samples = []
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                t0 = time.perf_counter()
                async with asyncio.timeout(2):
                    result = await client.call_tool("analyze_status", {"job_id": job_id})
                payload = result.structuredContent or json.loads(result.content[0].text)
                elapsed = time.perf_counter() - t0
                assert payload.get("ok") and payload["state_verified"], payload
                samples.append(
                    {
                        "latency_s": elapsed,
                        "done": payload["done"],
                        "state": payload["job"]["state"],
                        "messages_updated_at": payload["messages_updated_at"],
                        "progress": payload.get("progress"),
                    }
                )
                if payload["done"]:
                    assert payload["job"]["state"] == "completed", payload
                    break
                await asyncio.sleep(1)
            else:
                raise AssertionError("Real solve did not finish within ten minutes")
            assert any(not sample["done"] for sample in samples), samples
            phase = {
                "tool": name,
                "job": payload["job"],
                "samples": samples,
                "max_poll_s": max(sample["latency_s"] for sample in samples),
            }
            evidence["phases"].append(phase)
            (dest / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "phase": name,
                        "polls": len(samples),
                        "max_poll_s": phase["max_poll_s"],
                        "state": "completed",
                    }
                ),
                flush=True,
            )

        await solve("analyze_start", {"setup": "Setup1"})
        await call(
            "parametric_create",
            {
                "name": "ProgressRegression",
                "setup": "Setup1",
                "sweeps": [{"variable": "gap", "values": [1.05, 1.15]}],
            },
        )
        await solve("parametric_start", {"name": "ProgressRegression"})
        await call(
            "report_create",
            {
                "category": "S Parameter",
                "quantity": "S(1,1)",
                "function": "dB",
                "name": "ProgressProof",
                "setup": "Setup1",
                "sweep": "Sweep1",
                "parametric": "ProgressRegression",
            },
        )
        exported = await call(
            "report_export", {"report_id": "ProgressProof", "path": str(dest / "family.csv")}
        )
        assert exported["traces"] >= 2, exported
        evidence["family_traces"] = exported["traces"]
        evidence["passed"] = True
        return evidence


def main() -> None:
    source = ROOT / "examples/golden_patch.aedt"
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ROOT / "scratch" / f"progress-live-{stamp}"
    dest.mkdir(parents=True)
    project = dest / f"progress_smoke_{stamp.replace('-', '_')}.aedt"
    project.write_bytes(source.read_bytes())
    strip_aedt_text(project, block_names=("Optimetrics", "ReportSetup", "ProjectPreview"))
    desktop = get_desktop(version="2023.2", create_if_missing=False)
    previous = str(desktop.GetActiveProject().GetName())
    print(json.dumps({"evidence_dir": str(dest), "previous_project": previous}), flush=True)
    open_project_on_desktop(desktop, project, "HFSSDesign1")
    evidence = asyncio.run(verify(dest, project))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    evidence["source_unchanged"] = True
    (dest / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    # Only close our disposable project after successful completion.
    desktop.CloseProject(project.stem)
    desktop.SetActiveProject(previous)
    print("REAL_AEDT_PROGRESS_PASS", flush=True)


if __name__ == "__main__":
    main()
