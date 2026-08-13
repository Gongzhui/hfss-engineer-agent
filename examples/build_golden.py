"""Build the golden demo project + allowlist (reproducible, fixed output paths).

Usage:
    uv run python examples/build_golden.py

Outputs (re-created on every run):
    examples/golden_patch.aedt      — minimal driven-modal model (variable ``gap``)
    examples/golden_manifest.json   — allowlist pointing at the .aedt
"""

from __future__ import annotations

import json
from pathlib import Path

from hfss_mcp.real_project import create_minimal_patch_project

HERE = Path(__file__).resolve().parent


def main() -> int:
    meta = create_minimal_patch_project(
        HERE,
        project_name="golden_patch",
        version="2023.2",
        non_graphical=True,
    )
    project_path = Path(meta["project_path"]).resolve()
    if not project_path.is_file():
        raise SystemExit(f"golden project missing after build: {project_path}")

    allowlist = {
        "project_path": str(project_path),
        "project_name": meta["project_name"],
        "design_name": meta["design_name"],
        "default_setup": meta["setup"],
        "default_sweep": meta["sweep"],
        "parameters": [{"name": "gap", "unit": "mm", "min": 0.5, "max": 3.0}],
    }
    manifest_path = HERE / "golden_manifest.json"
    manifest_path.write_text(
        json.dumps(allowlist, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"golden project: {project_path}")
    print(f"allowlist:      {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
