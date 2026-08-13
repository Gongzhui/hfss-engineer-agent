"""Leak audit for a built benchmark case sandbox.

    uv run python benchmark/verify_case.py --case siw_feed_l1

Checks (any finding => exit 1):
  1. sandbox .aedt holds no Soln( records, no Report2D / ReportManager /
     Documentation / ProjectPreview blocks.
  2. no reference to any sibling design name anywhere in the sandbox text.
  3. exactly one HFSSModel block and it is the case design.
  4. whitelisted variable values equal the deterministic perturbation
     (recomputed from source + case.json) and differ from nominal.
  5. no exact ``VariableProp('<var>', ..., '<nominal><unit>')`` line survives.
  6. no reference to the answer-book directory in the sandbox text.
  7. no ``*.aedtresults`` directory inside the sandbox tree.
  8. manifest.json is accepted by the product loader and locks onto the
     sandbox project with exactly the case whitelist.

Prints LEAK-FREE and exits 0 when all checks pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aedt_text import find_forbidden_tokens  # noqa: E402
from case_io import (  # noqa: E402
    Case,
    compute_perturbation,
    load_case,
    nominal_map,
    read_design_variables,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def audit(case: Case) -> list[str]:
    findings: list[str] = []
    sandbox = case.sandbox_project
    if not sandbox.is_file():
        return [f"sandbox project missing: {sandbox} (run build_case.py first)"]

    src = Path(case.source.project_path)
    nominal = nominal_map(case)
    perturbed = compute_perturbation(case, nominal)

    # 1-2. forbidden blocks / solution records / sibling references
    for f in find_forbidden_tokens(sandbox, list(case.source.sibling_designs)):
        findings.append(f"sandbox text: {f}")

    text = sandbox.read_text(encoding="utf-8", errors="replace")

    # 3. exactly one HFSSModel and it is the case design
    n_models = text.count("$begin 'HFSSModel'")
    if n_models != 1:
        findings.append(f"sandbox holds {n_models} HFSSModel blocks, expected 1")
    else:
        try:
            read_design_variables(sandbox, case.source.design_name)
        except ValueError as exc:
            findings.append(f"case design missing in sandbox: {exc}")

    # 4. whitelisted variables carry the perturbed values, not nominal ones
    try:
        sandbox_vars = read_design_variables(sandbox, case.source.design_name)
        for var in case.variables:
            if var.name not in sandbox_vars:
                findings.append(f"whitelisted variable {var.name!r} missing in sandbox")
                continue
            value_s, unit = sandbox_vars[var.name]
            got = float(value_s)
            if abs(got - perturbed[var.name]) > 1e-9:
                findings.append(
                    f"{var.name}: sandbox value {got}{unit} != perturbed {perturbed[var.name]}"
                )
            if abs(got - nominal[var.name]) < 1e-12:
                findings.append(f"{var.name}: sandbox still holds nominal value {got}")
            if unit != var.unit:
                findings.append(f"{var.name}: unit {unit!r} != case unit {var.unit!r}")
    except ValueError as exc:
        findings.append(f"cannot parse sandbox variables: {exc}")

    # 5. the whitelisted variable's own VariableProp line must not carry the
    #    nominal value — neither as the value nor inside oa/sa/ta metadata
    src_vars = read_design_variables(src, case.source.design_name)
    for var in case.variables:
        nominal_str = f"{src_vars[var.name][0]}{var.unit}"
        for lineno, line in enumerate(text.splitlines(), start=1):
            if f"VariableProp('{var.name}'," in line and nominal_str in line:
                findings.append(
                    f"line {lineno}: nominal value {nominal_str} leaks on {var.name} "
                    "VariableProp line (value slot or oa/sa/ta metadata)"
                )

    # 6. answer-book path references
    for token in (str(case.answer_dir), "/answer/", "\\answer\\"):
        if token in text:
            findings.append(f"answer-book reference in sandbox text: {token!r}")

    # 7. results / pyaedt sidecar dirs inside sandbox tree
    if case.sandbox_dir.is_dir():
        for results in case.sandbox_dir.glob("*.aedtresults"):
            findings.append(f"results directory inside sandbox: {results.name}")
        for sidecar in case.sandbox_dir.glob("*.pyaedt"):
            findings.append(f"pyaedt sidecar directory inside sandbox: {sidecar.name}")

    # 8. manifest locks onto the sandbox with exactly the case whitelist
    if not case.manifest_path.is_file():
        findings.append(f"manifest missing: {case.manifest_path}")
    else:
        try:
            from hfss_mcp.allowlist import load_allowlist_file

            loaded = load_allowlist_file(case.manifest_path)
            if loaded.project_path and Path(loaded.project_path) != sandbox.resolve():
                findings.append(
                    f"allowlist project_path {loaded.project_path} != sandbox {sandbox.resolve()}"
                )
            if loaded.design_name != case.source.design_name:
                findings.append(f"allowlist design {loaded.design_name!r} != case design")
            got_names = sorted(loaded.names())
            want_names = sorted(v.name for v in case.variables)
            if got_names != want_names:
                findings.append(f"allowlist whitelist {got_names} != case {want_names}")
        except Exception as exc:  # noqa: BLE001 — audit must report, not crash
            findings.append(f"manifest rejected by product loader: {exc}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Leak audit for a benchmark case sandbox.")
    parser.add_argument("--case", required=True, help="case id under benchmark/cases/")
    args = parser.parse_args()
    try:
        case = load_case(args.case)
    except (FileNotFoundError, ValueError) as exc:
        log(f"PREFLIGHT FAIL: {exc}")
        return 2
    log(f"auditing sandbox: {case.sandbox_project}")
    findings = audit(case)
    if findings:
        log(f"LEAK AUDIT FAILED — {len(findings)} finding(s):")
        for f in findings:
            log(f"  - {f}")
        return 1
    log("checks: soln/reports/documentation/preview stripped; siblings gone; "
        "variables == perturbation; no nominal VariableProp; no answer refs; "
        "no results dirs; manifest locks sandbox + whitelist")
    log("LEAK-FREE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
