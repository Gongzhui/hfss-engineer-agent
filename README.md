# HFSS MCP

A constrained MCP bridge for AI-assisted HFSS simulation and antenna tuning.

The first implementation milestone is deliberately narrow: inspect a live AEDT/HFSS session, tune allowlisted parameters, run approved setups and sweeps as asynchronous jobs, and return traceable results. Arbitrary script execution and unrestricted geometry edits are not part of the default tool surface.

## Local development

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy
uv run hfss-mcp
```

The current development machine has AEDT 2023 R2 installed at `C:\Program Files\AnsysEM\v232`.

Reference source snapshots and their upstream commits are documented in `SOURCE_SNAPSHOTS.md`.

