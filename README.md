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

## Repository roles

- This repository (`Gongzhui/hfss-mcp`) is the only active implementation and the future public interface for agents.
- [`Gongzhui/hfss-cli`](https://github.com/Gongzhui/hfss-cli) is the preserved first-party legacy implementation. Its AEDT session, action, result, and test code is migration input, not a third-party reference.
- [`Gongzhui/hfss-cli-optimize-skill`](https://github.com/Gongzhui/hfss-cli-optimize-skill) preserves the legacy tuning workflow. It will be adapted after the MCP contract stabilizes.
- Blender MCP and EDA Agent are read-only third-party architectural references stored in the sibling `../hfss-mcp-references/` directory.

The detailed migration boundary and baseline are recorded in `docs/MIGRATION_FROM_HFSS_CLI.md`. A code-level comparison of existing public HFSS/AEDT MCP implementations is recorded in `docs/COMMUNITY_HFSS_MCP_REVIEW.md`.
