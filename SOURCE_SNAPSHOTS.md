# Reference repositories and snapshots

The active reference repositories live beside this project under `../hfss-mcp-references/`. They are full Git clones with upstream history and remotes. The original source archives downloaded before Git was installed are retained under `../hfss-mcp-references/snapshots-2026-07-20/`.

| Local directory | Upstream | Branch | Commit |
|---|---|---|---|
| `../hfss-mcp-references/blender-mcp` | <https://github.com/ahujasid/blender-mcp> | `main` | `9ad355a56dfa7598788085f1b0091c010eaebb07` |
| `../hfss-mcp-references/eda-agent` | <https://github.com/salitronic/eda-agent> | `main` | `b641e4e3438bcfbbde5919a7410755cf57c09fab` |

These are read-only architectural references. Do not develop inside the clone or snapshot directories. The HFSS MCP implementation lives only in this repository.

## Public HFSS/AEDT MCP implementations

Public implementations discovered on 2026-07-20 are cloned under `../hfss-mcp-references/hfss-community/`. The review and acceptance criteria are in `docs/COMMUNITY_HFSS_MCP_REVIEW.md`.

| Local directory | Upstream | Branch | Commit | License observed |
|---|---|---|---|---|
| `../hfss-mcp-references/hfss-community/ansys-pyaedt-mcp` | <https://github.com/ansys/pyaedt-mcp> | `main` | `eb2fd030ac50de2d77282a43bdf9262a7d773485` | Apache-2.0 |
| `../hfss-mcp-references/hfss-community/laplaceyoung-ansys-aedt-mcp` | <https://github.com/LaplaceYoung/ansys-aedt-mcp> | `main` | `65e70647fd98b60089e6ea452b37f7f3f2d9db27` | PolyForm Noncommercial 1.0.0 |
| `../hfss-mcp-references/hfss-community/k-13robot-hfss-mcp` | <https://github.com/K-13ROBOT/HFSS_MCP> | `main` | `340f3dca70623ae88d2384f95687e8acc1369242` | MIT |
| `../hfss-mcp-references/hfss-community/kk5212-multi-agent-hfss-mcp` | <https://github.com/Kk5212/Multi_Agent_Design_with_HFSS_MCP_Server> | `main` | `6bfb17e2d00eaa77790b5ec0f594af451502f9c6` | MIT |
| `../hfss-mcp-references/hfss-community/leonardwy-hfss-mcpserver` | <https://github.com/leonardwy/HFSS_McpServer> | `main` | `950c06dc8dae360ebe701bf00ff51542ac08c2b2` | No license file detected |
| `../hfss-mcp-references/hfss-community/nedaemami123-hfss-mcp` | <https://github.com/NedaEmami123/hfss-mcp> | `main` | `9caf1d61ffbf3359ef3f4a18b1e58c76b097655f` | README claim only; no license file detected |
| `../hfss-mcp-references/hfss-community/jessega0-hfss-mcp` | <https://github.com/jessega0/HFSS-mcp> | `main` | `ffeeb6a88e2654a050d25f007d03eaf977324eec` | No license file detected |
| `../hfss-mcp-references/hfss-community/gfgf2023-hfss-mcp-server` | <https://github.com/gfgf2023/hfss-mcp-server> | `master` | `d694e46951607bfb439b4ef982c9d652ae5d11c2` | MIT |

## Initial architecture takeaways

- Blender MCP: minimal `MCP stdio -> Python server -> localhost JSON/TCP -> Blender add-on/main thread` bridge.
- EDA Agent: production-oriented `MCP stdio -> typed tool modules -> persistent bridge -> live EDA host`, with tool metadata, bulk calls, checkpoints, fault recovery, durable sessions, async jobs, and layered tests.
- HFSS target: keep AEDT/PyAEDT calls behind an internal adapter; expose a narrow typed MCP surface, starting with read-only inspection and allowlisted parameter tuning. Never expose arbitrary script execution in the default tool surface.
