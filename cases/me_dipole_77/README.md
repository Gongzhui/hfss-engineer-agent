# me_dipole_77

77 GHz plated-through-hole printed magneto-electric dipole. Topology from Ng et al., “60 GHz Plated Through Hole Printed Magneto-Electric Dipole Antenna,” *IEEE TAP*, 60(7), 2012 (P02). This HFSS project is a **77 GHz retarget** (20 mil RT/Duroid 5880), not a 1:1 copy of the 60 GHz table.

Nominal is a Save As of the user-corrected `Downloads/77GHZantenna.aedt`, design `77GHZantenna`. `ws=wp+g3` and `ls=lp+offset` so the feed slot tracks the T-stem.

## Open

- Example (do not detune): `nominal/me_dipole_77.aedt`, design `77GHZantenna`
- Host Agent / sandbox: `sandbox/me_dipole_77.aedt`

Do not open `nominal/` or `answer/` in a scoring session.

## Geometry (mm)

RT/Duroid 5880, copper, lumped port `1`, radiation box, Setup1 @ 77 GHz, Fast sweep 60–100 GHz (100 pts).

| var | nominal | meaning |
|---|---|---|
| `h` | 0.508 | substrate thickness (20 mil) |
| `w` | 1.55 | planar dipole width \(W\) |
| `l1` | 1.15 | each dipole arm length \(L_1\) |
| `l2` | 0.55 | gap between arms \(L_2\) (total \(2L_1+L_2=2.85\)) |
| `gndw` | 18 | ground side |
| `r1` | 0.125 | via radius |
| `viagap` | 0.55 | via pitch along the inner edge |
| `d1` | 0.27 | via row offset; `via_offset=l2/2+d1` |
| `wp`, `lp` | 0.55, 0.85 | T-stem width × length |
| `g3` | 0.15 | slot wider than stem; `ws=wp+g3` |
| `e1`, `e2` | 0.16, 0.19 | T-bar end widening |
| `g4` | 0.05 | small feed clearance |
| `tcop` | 0.0175 | copper thickness |

Leave `h`, `gndw`, `tcop`, `ws`, `ls`, and the tiny `offset`/`d`/`lsub` knobs out of the exam allowlist. Keep `lp+|offset| < l1` so the slot stays inside `cop1`.

## Sandbox perturbation

Seven independent knobs, set by the user on the live model then saved. `ws` and `ls` follow.

| var | nominal | sandbox | Δ |
|---|---|---|---|
| `l1` | 1.15 | 0.9 | −0.25 |
| `l2` | 0.55 | 0.7 | +0.15 |
| `w` | 1.55 | 1.8 | +0.25 |
| `wp` | 0.55 | 0.4 | −0.15 |
| `lp` | 0.85 | 1 | +0.15 |
| `d1` | 0.27 | 0.2 | −0.07 |
| `g3` | 0.15 | 0.3 | +0.15 |

`e1` stays 0.16 mm (on the allowlist, not detuned). Frozen start curve: `results/s11_sandbox.csv` (no −10 dB band; nearest 77 GHz is about −9.2 dB). Nominal: `results/s11.csv` (about 67–92 GHz, relative BW ≈ 32%).
