"""Opt-in real HFSS test on a disposable copy of the completed ME-dipole exam.

Copies disk project/results, never changes the user's live design. No solves.
Retains small JSON/CSV evidence; copied AEDT results can be removed after review.
Run from the repository root with its Python environment and idle AEDT 2023 R2.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hfss_mcp.com_session import get_desktop

ROOT = Path(__file__).resolve().parents[1]
BEST = {"l1": 1.05, "l2": 0.45, "w": 1.6, "wp": 0.4, "lp": 0.8, "d1": 0.35, "g3": 0.15, "e1": 0.05}


async def verify(dest: Path, project: Path) -> dict[str, Any]:
    env = dict(
        os.environ,
        HFSS_MCP_ADAPTER="pyaedt",
        HFSS_MCP_DEMO="0",
        HFSS_MCP_DATA_DIR=str(dest / "state"),
    )
    evidence: dict[str, Any] = {"project": str(project), "calls": []}
    async with (
        stdio_client(
            StdioServerParameters(command=sys.executable, args=["-m", "hfss_mcp.server"], env=env)
        ) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        tools = await client.list_tools()
        evidence["report_create_schema"] = next(
            t.inputSchema for t in tools.tools if t.name == "report_create"
        )

        async def call(name: str, args: dict[str, Any], *, error: str | None = None) -> dict:
            async with asyncio.timeout(45):
                result = await client.call_tool(name, args)
            data = result.structuredContent or json.loads(result.content[0].text)
            evidence["calls"].append({"tool": name, "arguments": args, "result": data})
            (dest / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            if error:
                assert not data.get("ok") and data["error"]["code"] == error, data
            else:
                assert data.get("ok"), data
            return data

        allowlist = json.loads((ROOT / "eval/exams/me_dipole_77/allowlist.json").read_text())
        allowlist.update(project_name=project.stem, project_path=str(project))
        await call("allowlist_load", {"allowlist": allowlist})
        selected = {n: [f"{v}mm"] for n, v in BEST.items()}
        selected.update(l1=["1.05mm", "1.3mm"], lp=["0.8mm", "1mm"])
        for name, category, quantity, function in [
            ("MultiS", "S Parameter", "S(1,1)", "dB"),
            ("MultiZ", "Z Parameter", "Z(1,1)", ["re", "im"]),
        ]:
            await call(
                "report_create",
                dict(
                    name=name,
                    category=category,
                    quantity=quantity,
                    function=function,
                    families=selected,
                    setup="Setup1",
                    sweep="Sweep",
                ),
            )
            report = (await call("report_get", {"name": name}))["report"]
            assert report["families"]["l1"] == ["1.05mm", "1.3mm"]
            out = await call(
                "report_export", {"report_id": name, "path": str(dest / f"{name}.csv")}
            )
            assert out["traces"] == 4, out
            assert out["solution_status"]["data_availability"] == "available"
            assert out["solution_validity"] == "unknown"
            assert "stale_solution" not in out
            rows = list(csv.DictReader((dest / f"{name}.csv").open(encoding="utf-8")))
            assert len(rows) == 400 and len({r["variation"] for r in rows}) == 4
        await call("variables_set", {"parameters": [{"name": "l1", "value": 0.9137, "unit": "mm"}]})
        await call(
            "report_create",
            dict(
                name="NominalCheck",
                category="S Parameter",
                quantity="S(1,1)",
                function="dB",
                families=[],
                setup="Setup1",
                sweep="Sweep",
            ),
        )
        await call(
            "report_export", {"report_id": "NominalCheck"}, error="report_solution_query_failed"
        )
        await call(
            "report_export", {"report_id": "MultiZ", "path": str(dest / "fixed-while-unsolved.csv")}
        )
        await call(
            "variables_set",
            {"parameters": [dict(name=n, value=v, unit="mm") for n, v in BEST.items()]},
        )
        out = await call(
            "report_export", {"report_id": "NominalCheck", "path": str(dest / "restored.csv")}
        )
        assert out["solution_status"]["data_availability"] == "available"
        assert "stale_solution" not in out
        desktop = get_desktop(version="2023.2")
        design = desktop.SetActiveProject(project.stem).SetActiveDesign("77GHZantenna")
        design.GetModule("AnalysisSetup").EditSetup(
            "Setup1", ["NAME:Setup1", "Frequency:=", "76.123GHz"]
        )
        out = await call(
            "report_export", {"report_id": "NominalCheck", "path": str(dest / "setup-changed.csv")}
        )
        # Critical: successful retrieval after Setup changes is NOT a validity certificate.
        assert out["solution_validity"] == "unknown"
        editor = design.SetActiveEditor("3D Modeler")
        editor.ChangeProperty(
            [
                "NAME:AllTabs",
                [
                    "NAME:Geometry3DAttributeTab",
                    ["NAME:PropServers", "cop1"],
                    ["NAME:ChangedProps", ["NAME:Material", "Value:=", '"aluminum"']],
                ],
            ]
        )
        await call(
            "report_export", {"report_id": "NominalCheck"}, error="report_solution_query_failed"
        )
        await call("report_export", {"report_id": "MultiZ"}, error="report_solution_query_failed")
    evidence["passed"] = True
    (dest / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


def main() -> None:
    dest = ROOT / ".tmp-report-validity" / datetime.now().strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True)
    source = ROOT / "cases/me_dipole_77/sandbox/me_dipole_77.aedt"
    project = dest / "ReportFamilyProbe.aedt"
    shutil.copy2(source, project)
    shutil.copytree(
        source.with_suffix(".aedtresults"),
        project.with_suffix(".aedtresults"),
        ignore=shutil.ignore_patterns("*.semaphore"),
    )
    desktop = get_desktop(version="2023.2")
    original = desktop.GetActiveProject().GetName()
    if project.stem in list(desktop.GetProjectList()):
        raise RuntimeError("Close the previous disposable ReportFamilyProbe before repeating")
    try:
        desktop.OpenProject(str(project))
        asyncio.run(verify(dest, project))
        print(json.dumps({"passed": True, "evidence": str(dest / "evidence.json")}))
    finally:
        desktop.SetActiveProject(original)


if __name__ == "__main__":
    main()
