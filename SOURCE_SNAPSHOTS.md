# Reference repositories and snapshots

The active reference repositories live beside this project under `../hfss-mcp-references/`. They are full Git clones with upstream history and remotes. The original source archives downloaded before Git was installed are retained under `../hfss-mcp-references/snapshots-2026-07-20/`.

| Local directory | Upstream | Branch | Commit |
|---|---|---|---|
| `../hfss-mcp-references/blender-mcp` | <https://github.com/ahujasid/blender-mcp> | `main` | `9ad355a56dfa7598788085f1b0091c010eaebb07` |
| `../hfss-mcp-references/eda-agent` | <https://github.com/salitronic/eda-agent> | `main` | `b641e4e3438bcfbbde5919a7410755cf57c09fab` |

These are read-only architectural references. Do not develop inside the clone or snapshot directories. The HFSS MCP implementation lives only in this repository.

## Initial architecture takeaways

- Blender MCP: minimal `MCP stdio -> Python server -> localhost JSON/TCP -> Blender add-on/main thread` bridge.
- EDA Agent: production-oriented `MCP stdio -> typed tool modules -> persistent bridge -> live EDA host`, with tool metadata, bulk calls, checkpoints, fault recovery, durable sessions, async jobs, and layered tests.
- HFSS target: keep AEDT/PyAEDT calls behind an internal adapter; expose a narrow typed MCP surface, starting with read-only inspection and allowlisted parameter tuning. Never expose arbitrary script execution in the default tool surface.
