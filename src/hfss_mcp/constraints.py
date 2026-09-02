"""Safe evaluation of allowlist constraint expressions.

Only arithmetic and comparisons on named floats — no attribute access,
calls, or imports. Used to reject infeasible parametric rows / variable sets.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from hfss_mcp.errors import PolicyError

_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_CMPOPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _eval_node(node: ast.AST, values: dict[str, float]) -> float | bool:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, values)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise PolicyError(
            f"constraint constant not allowed: {node.value!r}",
            code="constraint_invalid",
        )
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise PolicyError(
                f"constraint references unknown variable {node.id!r}",
                code="constraint_unknown_variable",
                details={"name": node.id, "known": sorted(values)},
            )
        return float(values[node.id])
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return float(_UNARYOPS[type(node.op)](_eval_node(node.operand, values)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = float(_eval_node(node.left, values))
        right = float(_eval_node(node.right, values))
        if isinstance(node.op, ast.Div) and right == 0.0:
            raise PolicyError("division by zero in constraint", code="constraint_invalid")
        return float(_BINOPS[type(node.op)](left, right))
    if isinstance(node, ast.Compare):
        current = float(_eval_node(node.left, values))
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if type(op) not in _CMPOPS:
                raise PolicyError(
                    f"constraint comparator not allowed: {type(op).__name__}",
                    code="constraint_invalid",
                )
            rhs = float(_eval_node(comparator, values))
            if not bool(_CMPOPS[type(op)](current, rhs)):
                return False
            current = rhs
        return True
    raise PolicyError(
        f"constraint syntax not allowed: {type(node).__name__}",
        code="constraint_invalid",
    )


def parse_constraint(expr: str) -> ast.Expression:
    text = str(expr or "").strip()
    if not text:
        raise PolicyError("constraint must be non-empty", code="constraint_invalid")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise PolicyError(
            f"constraint is not valid Python expression: {expr!r}",
            code="constraint_invalid",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(tree, ast.Expression):
        raise PolicyError("constraint must be an expression", code="constraint_invalid")
    # Warm validation with dummy zeros for free names is done by callers.
    return tree


def constraint_names(expr: str) -> set[str]:
    tree = parse_constraint(expr)
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def eval_constraint(expr: str, values: dict[str, float]) -> bool:
    tree = parse_constraint(expr)
    result = _eval_node(tree, values)
    if not isinstance(result, bool):
        raise PolicyError(
            f"constraint must compare to true/false, got {result!r} from {expr!r}",
            code="constraint_invalid",
        )
    return result


def assert_constraints(
    constraints: list[str],
    values: dict[str, float],
    *,
    where: str,
) -> None:
    if not constraints:
        return
    for expr in constraints:
        if eval_constraint(expr, values):
            continue
        raise PolicyError(
            f"constraint violated ({where}): {expr}",
            code="constraint_violated",
            details={"constraint": expr, "values": dict(values), "where": where},
        )


def assert_constraints_on_rows(
    constraints: list[str],
    rows: list[dict[str, float]],
    *,
    where: str,
) -> None:
    if not constraints or not rows:
        return
    bad: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        for expr in constraints:
            try:
                ok = eval_constraint(expr, row)
            except PolicyError as exc:
                if getattr(exc, "code", "") == "constraint_unknown_variable":
                    # Row may omit unrelated knobs; skip that constraint.
                    missing = (exc.details or {}).get("name")
                    if missing and missing not in row:
                        continue
                raise
            if not ok:
                bad.append({"index": index, "constraint": expr, "values": dict(row)})
                break
    if bad:
        raise PolicyError(
            f"{len(bad)} parametric row(s) violate allowlist constraints ({where})",
            code="parametric_row_infeasible",
            details={"where": where, "rows": bad[:20], "count": len(bad)},
        )
