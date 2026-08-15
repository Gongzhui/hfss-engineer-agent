# uwb_circular_notch

Printed circular monopole with a U-shaped slot (single band-notch UWB). First antenna in 陈彦松, *超宽带天线及其带阻特性设计*, 东南大学本科毕业设计, 2025, §3.1.

Thesis PDF (not in this repo): `Downloads/超宽带天线及其带阻特性设计 打印.pdf`. Dimensions from 图 3-2 / 表 3.1.

## What is in the project

Built: substrate, circular patch + microstrip feed, inverted-U slot, truncated ground with matching notch, design variables, air box + radiation, **wave port `1` (added by hand)**, Setup1 @ 12 GHz, interpolating Sweep1 1–15 GHz, discrete RadSweep at 3.65/11.27 GHz, infinite sphere `FF3D`.

Rebuild geometry (will **wipe the port**):

```powershell
uv run python cases/uwb_circular_notch/build.py
```

Re-solve without rebuilding:

```powershell
uv run python cases/uwb_circular_notch/setup_solve.py
```

## Open

- Example (do not detune): `nominal/uwb_circular_notch.aedt`, design `CircularMonopole`
- Host Agent session: `sandbox/uwb_circular_notch.aedt`. Exam: `eval/exams/uwb_circular_notch/`.

Rebuild (separate non-graphical AEDT; will not close a GUI session):

```powershell
cd C:\Users\Gongzhui\Documents\Projects\hfss-mcp
uv run python cases/uwb_circular_notch/build.py
```

## Geometry (mm)

| var | nominal | meaning |
|---|---|---|
| `l` × `w` × `sub_h` | 33 × 25 × 1.14 | substrate, Rogers RT5880 (εr=2.2, tanδ=0.0009) |
| `patch_r` | 8 | patch radius (thesis $r$; HFSS forbids a variable named `r` on a circle) |
| `l1`, `lw` | 16.3, 3.5 | feed length (substrate edge → circle tangent), feed width |
| `slot_length` | 20 | U-slot centerline length; `l3=slot_length/2`, `l4=slot_length/4` |
| `l2`, `sw` | 2, 1 | U-slot offset from patch center to top of U; slot width |
| `g1`, `g2`, `g3` | 16, 3.9, 5.2 | ground height; notch width × depth at ground top-center |
| `air_pad` | 25 | λ/4 at 3 GHz; air box padding (including −Y) |

Circle center at `(0, l1+patch_r, sub_h)` so the disk is tangent to the feed end. Circle and feed are **XY-plane sheets** (not `WhichAxis=Y`). Inverted U opens toward the feed.

Conductors are zero-thickness sheets with Perfect E (`PatchPEC`, `GroundPEC`). Feed edge is at `y=0` for a lumped or wave port.

## Expected (thesis §3.1.3) vs first HFSS solve (2026-08-13)

权威曲线是工程里的 Modal 报告 `S11`。第一次误把 Touchstone 50 Ω 终端 S 当成同一条曲线；那份已改名为 `s11_touchstone_50ohm.csv`。

| | Thesis Fig 3-6 | Modal `dB(S(1,1))` |
|---|---|---|
| −10 dB 通带 | 3.07–12.67 GHz，中间有阻带 | 约 2.3–6.4 与 6.8–12.3 GHz；3.07–12.67 内约 94% 点 ≤ −10 dB |
| 阻带 | ~6 GHz 抬起 | 6.6 GHz −5.63 dB |
| 谐振深度 | ~3.7 GHz −25 dB，~11.2 GHz −39 dB | 2.4 GHz −18.5 dB；11.2 GHz −13.1 dB |

## Sandbox perturbation (2026-08-13)

九个量都改了，相对标称均 ≤50%。`lw` 加宽到 5.25 mm（微带更胖、Z0 偏低）；收到 1.75 mm 反而把通带撑得更宽，已不用。

| var | nominal | sandbox | Δ |
|---|---|---|---|
| `patch_r` | 8 | 5.6 | −30% |
| `slot_length` | 20 | 12 | −40% |
| `l1` | 16.3 | 10.0 | −39% |
| `l2` | 2 | 1.2 | −40% |
| `sw` | 1 | 1.5 | +50% |
| `g1` | 16 | 8.5 | −47% |
| `g2` | 3.9 | 2.0 | −49% |
| `g3` | 5.2 | 2.6 | −50% |
| `lw` | 3.5 | 5.25 | +50% |

Modal `S11`：标称 −10 dB 合计约 10.7 GHz（3.07–12.67 GHz 内 94% 点 ≤ −10 dB）。沙箱加宽 `lw` 后约 8.5 GHz（同区间 75%）：2–6 GHz 那一段基本打掉，只剩 3.7–4.9 GHz 一条窄缝；高频 6.8–13.1 GHz 仍宽。曲线：`results/s11.csv` 与 `results/s11_sandbox.csv`。
