"""Text-level .aedt inspection / stripping helpers (sandbox authoring + leak audit).

The .aedt format is line-oriented text with balanced ``$begin 'X'`` / ``$end 'X'``
blocks. Stripping happens on *copies* only; the source example stays read-only.
"""

from __future__ import annotations

import re
from pathlib import Path

# Blocks that carry answer leaks (saved solutions, plotted curves, PDF refs,
# rendered preview thumbnails) and must not survive into a sandbox.
STRIP_BLOCK_NAMES = ("ReportManager", "Report2D", "Documentation", "ProjectPreview")

SOLN_RE = re.compile(r"^\s*Soln\(")
_BEGIN_RE = re.compile(r"\$begin '([^']+)'")


def strip_aedt_text(path: Path) -> dict[str, int]:
    """Remove leak-bearing blocks/lines in place. Returns removal counts."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    out: list[str] = []
    counts: dict[str, int] = {"Soln": 0}
    i = 0
    while i < len(lines):
        line = lines[i]
        if SOLN_RE.match(line):
            counts["Soln"] += 1
            i += 1
            continue
        m = _BEGIN_RE.search(line)
        if m and m.group(1) in STRIP_BLOCK_NAMES:
            name = m.group(1)
            depth = 0
            j = i
            while j < len(lines):
                # count occurrences: both tokens may share a line (cdata markers)
                depth += lines[j].count(f"$begin '{name}'")
                depth -= lines[j].count(f"$end '{name}'")
                if depth == 0:
                    break
                j += 1
            if depth != 0 or j >= len(lines):
                raise ValueError(f"unbalanced block {name!r} starting at line {i + 1} in {path}")
            counts[name] = counts.get(name, 0) + 1
            i = j + 1
            continue
        out.append(line)
        i += 1
    path.write_text("".join(out), encoding="utf-8")
    return counts


def find_forbidden_tokens(path: Path, extra_names: list[str]) -> list[str]:
    """Return a list of leak findings (empty = clean). Pure read, no writes."""
    findings: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SOLN_RE.match(line):
            findings.append(f"line {lineno}: saved-solution record Soln(...)")
        m = _BEGIN_RE.search(line)
        if m and m.group(1) in STRIP_BLOCK_NAMES:
            findings.append(f"line {lineno}: forbidden block {m.group(1)!r}")
        for name in extra_names:
            if f"'{name}'" in line:
                findings.append(f"line {lineno}: reference to stripped design {name!r}")
    return findings
