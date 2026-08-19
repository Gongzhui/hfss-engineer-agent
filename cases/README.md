# Antenna cases

One folder per antenna. The same tree is the **example** (nominal project) and the **benchmark** (sandbox + hidden answer). `examples/` stays MCP plumbing (`golden_patch`); do not put real antennas there.

## Layout

```
cases/<id>/
  README.md           # source, what to open, expected band
  case.json           # identity, allowlist vars, scoring
  allowlist.json      # slim MCP allowlist (sandbox path)
  build.py            # maintainer rebuild; not an MCP tool
  nominal/            # example: nominal dimensions, no results
  sandbox/            # Host Agent opens this (detuned, no results)
  answer/             # scoring only — Skill must not read this
```

## Rules

- Commit `.aedt` without `.aedtresults/`.
- Agent may read `sandbox/` + `allowlist.json` + the public fields of `case.json`.
- Host Agent exam sessions open `eval/exams/<id>/`, not this `cases/` folder.
- `answer/` and `nominal/` are the answer book. Do not load them in a scoring session.
- Save As during a session goes to `scratch/` or `HFSS_MCP_DATA_DIR`, never back onto `nominal/`.
- MCP remains tune-only. `build.py` is the maintainer path for geometry.

## Index

| id | Status | Open |
|---|---|---|
| `uwb_circular_notch` | Ported nominal solved; sandbox detuned (9 params, `lw` included) | Host Agent exam: `eval/exams/uwb_circular_notch/` (6.6 GHz stopband, width ≤ 0.5 GHz, envelope rel BW ≥ 130%; 3 h solve time). Keep `nominal/` + `answer/` closed |
| `siw_feed_l1` | Still under `benchmark/cases/siw_feed_l1/` (vendor example) | sandbox there |
