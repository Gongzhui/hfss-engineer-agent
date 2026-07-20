# Reference source snapshots

Downloaded on 2026-07-20 because Git is not currently installed on this machine. Each directory is an unpacked GitHub source archive pinned here by its exact commit SHA.

| Local directory | Upstream | Branch | Commit |
|---|---|---|---|
| `references/blender-mcp` | <https://github.com/ahujasid/blender-mcp> | `main` | `9ad355a56dfa7598788085f1b0091c010eaebb07` |
| `references/eda-agent` | <https://github.com/salitronic/eda-agent> | `main` | `b641e4e3438bcfbbde5919a7410755cf57c09fab` |

These are read-only architectural references. Do not develop inside the snapshot directories. The new HFSS MCP implementation should live in a separate source directory under this project root.

## Initial architecture takeaways

- Blender MCP: minimal `MCP stdio -> Python server -> localhost JSON/TCP -> Blender add-on/main thread` bridge.
- EDA Agent: production-oriented `MCP stdio -> typed tool modules -> persistent bridge -> live EDA host`, with tool metadata, bulk calls, checkpoints, fault recovery, durable sessions, async jobs, and layered tests.
- HFSS target: keep AEDT/PyAEDT calls behind an internal adapter; expose a narrow typed MCP surface, starting with read-only inspection and allowlisted parameter tuning. Never expose arbitrary script execution in the default tool surface.
