"""Modal Results trace selection: Category / Quantity / Function → Y expressions."""

from __future__ import annotations

import re
from typing import Any

# Only these New-Trace categories are agent-visible (Modal Solution Data).
CURVE_CATEGORIES: tuple[str, ...] = ("S Parameter", "Z Parameter")

# Full HFSS New-Trace Function set for network parameters (fallback when COM
# does not enumerate Functions). Not a curated subset.
MODAL_TRACE_FUNCTIONS: tuple[str, ...] = (
    "<none>",
    "ang_deg",
    "ang_deg_val",
    "ang_rad",
    "arg",
    "cang_deg",
    "cang_deg_val",
    "cang_rad",
    "dB",
    "dB10normalize",
    "dB20normalize",
    "dBc",
    "dBm",
    "dBu",
    "im",
    "mag",
    "normalize",
    "phase_rad",
    "re",
    "real",
)

_NONE_FUNCTIONS = frozenset({"", "none", "<none>", "null"})
# Network quantities like S(1,1) / Z(1,1) are not Function(Quantity) wrappers.
_QUANTITY_ROOTS = frozenset({"s", "y", "z", "st", "yt", "zt", "gamma", "vswr"})
_FUNC_CALL = re.compile(r"^(?P<func>[A-Za-z_][\w]*)\((?P<qty>.+)\)$")


def is_none_function(function: str) -> bool:
    return str(function or "").strip().lower() in _NONE_FUNCTIONS


def parse_name_list(value: Any) -> list[str]:
    """Split quantity/function args into an ordered unique list.

    Accepts str | list[str]. Separators are ';' or top-level ',' (parentheses
    protect commas inside S(1,1)).
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        text = str(value).strip()
        if not text:
            return []
        items = _split_top_level(text)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            buf.append(ch)
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if depth == 0 and ch in {";", ","}:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def compose_y_expressions(
    quantities: list[str],
    functions: list[str],
) -> list[str]:
    """Cartesian product: for each function, for each quantity → Y expression."""
    qty = [q for q in quantities if str(q).strip()]
    fns = [f for f in functions if str(f).strip()]
    if not qty:
        raise ValueError("quantity is required")
    if not fns:
        raise ValueError("function is required")
    exprs: list[str] = []
    seen: set[str] = set()
    for function in fns:
        for quantity in qty:
            if is_none_function(function):
                expr = quantity
            else:
                expr = f"{function}({quantity})"
            if expr in seen:
                continue
            seen.add(expr)
            exprs.append(expr)
    return exprs


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    text = str(category).strip()
    if not text:
        return None
    lowered = text.lower()
    for allowed in CURVE_CATEGORIES:
        if lowered == allowed.lower():
            return allowed
    return text


def split_expression(expression: str) -> tuple[str | None, str]:
    """Split dB(S(1,1)) → ('dB', 'S(1,1)'); bare S(1,1) → (None, 'S(1,1)')."""
    text = str(expression or "").strip()
    if " - " in text:
        text = text.split(" - ", 1)[0].strip()
    if " : " in text:
        text = text.split(" : ", 1)[0].strip()
    text = re.sub(r"\s*\[[^\]]*\]\s*$", "", text).strip()
    match = _FUNC_CALL.match(text)
    if not match:
        return None, text
    func = match.group("func")
    if func.lower() in _QUANTITY_ROOTS:
        return None, text
    return func, match.group("qty").strip()


def expressions_to_trace_parts(
    expressions: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Return (quantities, functions, cleaned expressions) preserving order."""
    quantities: list[str] = []
    functions: list[str] = []
    cleaned: list[str] = []
    seen_q: set[str] = set()
    seen_f: set[str] = set()
    seen_e: set[str] = set()
    for raw in expressions:
        func, qty = split_expression(raw)
        expr = qty if func is None else f"{func}({qty})"
        if expr and expr not in seen_e:
            seen_e.add(expr)
            cleaned.append(expr)
        if qty and qty not in seen_q:
            seen_q.add(qty)
            quantities.append(qty)
        fn = "<none>" if func is None else func
        if fn not in seen_f:
            seen_f.add(fn)
            functions.append(fn)
    return quantities, functions, cleaned


def is_classic_s11_db(expressions: list[str]) -> bool:
    if len(expressions) != 1:
        return False
    lowered = expressions[0].lower().replace(" ", "")
    return lowered in {"db(s(1,1))", "db(s11)"}


def is_classic_z_re_im(expressions: list[str]) -> bool:
    if len(expressions) != 2:
        return False
    norms = [e.lower().replace(" ", "") for e in expressions]
    return set(norms) == {"re(z(1,1))", "im(z(1,1))"} or set(norms) == {
        "re(zt(1,1))",
        "im(zt(1,1))",
    }
