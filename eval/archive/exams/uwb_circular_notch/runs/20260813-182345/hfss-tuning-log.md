# uwb_circular_notch 调参日志

- started: 2026-08-13T18:23:45
- session project_path: C:\Users\Gongzhui\Documents\Projects\hfss-mcp\cases\uwb_circular_notch\sandbox\uwb_circular_notch.aedt
- allowlist: ./allowlist.json

开场变量：patch_r=5.6 mm, l2=1.2 mm, slot_length=12 mm, sw=1.5 mm, lw=5.25 mm, l1=10 mm, g1=8.5 mm, g2=2.0 mm, g3=2.6 mm

## Round 000（开场，未改参）

- S11 文件: round-000-s11.csv
- −10 dB 频段（目视）: 1.00–2.05 GHz；3.65–4.95 GHz；6.75–13.15 GHz。3–12 GHz 目标档里大段不连续。
- 阻带是否可辨: 3.4 GHz 有一尖锐抬起（约 −1.4 dB），更像谐振/匹配垮掉，不是通带中间的阻带。5.0–6.8 GHz 另有一段缓抬（谷底约 −6.9 dB @ 6.0 GHz）。6.8 GHz 以上已经匹配得很好。
- 假设（下一轮要验证什么）: 圆贴片偏小，主通带被抬到 6.8–13 GHz；把 patch_r 加大，看低频 −10 dB 边是否下移、3 GHz 附近是否重新匹配。

## Round 001

- 假设: 圆贴片偏小，主通带被抬到 6.8–13 GHz。加大 patch_r 应让低频 −10 dB 边下移。
- 改动（变量 / 旧值 → 新值）: patch_r 5.6 mm → 9.0 mm
- Analyze: Setup1，job_id: job_a0e489f32eb5437488ade9c29f142783
- S11 文件: round-001-s11.csv
- −10 dB 频段相对上一轮: 变为 1.00–2.05 GHz；3.05–4.10 GHz；5.75–12.35 GHz。3.4 GHz 尖峰消失，下通带出现在 3.1 GHz 附近；上通带起点从 6.75 降到 5.75 GHz，高端从 13.15 收到 12.35 GHz。
- 阻带相对上一轮: 4.1–5.75 GHz 一段缓抬（约 −7.4 dB @ 5.1 GHz），位置仍偏低、偏宽，把下通带只剩下约 1 GHz。
- 下一轮 / 停止理由: 缩短 slot_length，看阻带中心是否上移、下通带是否变宽。

## Round 002

- 假设: 阻带中心偏低（约 5.1 GHz）且从 4.1 GHz 就开始抬，吞掉下通带。缩短 slot_length 应把阻带往上推、下通带变宽。
- 改动（变量 / 旧值 → 新值）: slot_length 12 mm → 10.5 mm
- Analyze: Setup1，job_id: job_7747a416966f4a38976b68d67f12d9ba
- S11 文件: round-002-s11.csv
- −10 dB 频段相对上一轮: 变为 1.00–1.85 GHz；3.05–3.95 GHz；6.05–12.55 GHz。下通带上沿从 4.10 收到 3.95 GHz；上通带起点从 5.75 升到 6.05 GHz。
- 阻带相对上一轮: 3.95–6.05 GHz，峰值约 −6.5 dB @ 5.2 GHz。中心几乎没动，宽度反而加大。
- 下一轮 / 停止理由: 槽宽 sw 仍为上限 1.5 mm，Q 偏低。减小 sw，看阻带是否收窄、下通带是否回到 4 GHz 以上。

## Round 003

- 假设: 槽太宽导致 4–6 GHz 抬起 Q 低。减小 sw 应收窄这段抬起。
- 改动（变量 / 旧值 → 新值）: sw 1.5 mm → 0.8 mm
- Analyze: Setup1，job_id: job_72931102b3cb4c69a18836f9e3793f40
- S11 文件: round-003-s11.csv
- −10 dB 频段相对上一轮: 仍约 1.00–1.80 GHz；3.05–3.95 GHz；6.05–12.65 GHz。与 Round 002 几乎重合。
- 阻带相对上一轮: 峰值仍约 −6.5 dB @ 5.2 GHz，宽度几乎不变。sw 不是这段抬起的主因。
- 下一轮 / 停止理由: 4–6 GHz 更像两段谐振中间的匹配空洞。加长地板 g1，看这段是否落回 −10 dB。

## Round 004

- 假设: 部分地板偏短，3.3 GHz 与 7 GHz 两段谐振中间匹配空洞。加长 g1 看 4–6 GHz 是否落回 −10 dB。
- 改动（变量 / 旧值 → 新值）: g1 8.5 mm → 13 mm
- Analyze: Setup1，job_id: job_352f1e594ade4506aa07d7d8acd1bc84
- S11 文件: round-004-s11.csv
- −10 dB 频段相对上一轮: 变为约 1.00–1.55 GHz；2.65–7.05 GHz；10.05–14.55 GHz。4–6 GHz 空洞被填上，但 7–10 GHz 整段抬出 −10 dB。2.4 GHz 附近出现异常尖峰（S11 为正）。
- 阻带相对上一轮: 出现清晰抬起，约 7.1–10.1 GHz，峰值约 −0.6 dB @ 8.9 GHz。阻带过高、过宽。
- 下一轮 / 停止理由: g1=13 mm 过大。收到约 10.5 mm，看 4–6 GHz 是否仍匹配、阻带是否回到通带中间。

## Round 005

- 假设: g1=13 mm 过大，阻带被推到 8.9 GHz。收到 10.5 mm，看 4–6 GHz 是否仍匹配、阻带是否回到通带中间。
- 改动（变量 / 旧值 → 新值）: g1 13 mm → 10.5 mm
- Analyze: Setup1，job_id: job_5ffb7ca4f34743c5b59a80b10aea649b
- S11 文件: round-005-s11.csv
- −10 dB 频段相对上一轮: 变为约 1.00–1.55 GHz；2.95–10.15 GHz。3–10 GHz 连成一段，高端从 14.5 GHz 收到 10.15 GHz。2.7 GHz 仍有匹配尖峰（约 −2 dB）。
- 阻带相对上一轮: 8.9 GHz 强阻带消失。4.5 GHz 仅缓抬到约 −10.2 dB，仍低于 −10 dB，不能算清晰阻带。
- 下一轮 / 停止理由: 通带已经连上，但中间没有清晰阻带。加长 slot_length，在通带中间开出阻带。

## Round 006

- 假设: 3–10 GHz 已连成通带，中间没有清晰阻带。加长 slot_length 应在通带中间开出阻带。
- 改动（变量 / 旧值 → 新值）: slot_length 10.5 mm → 14 mm
- Analyze: Setup1，job_id: job_765467419b9c48088e4b68e94635b1c6
- S11 文件: round-006-s11.csv
- −10 dB 频段相对上一轮: 仍约 1.00–1.60 GHz；2.95–10.35 GHz。与 Round 005 几乎重合，高端略延到 10.35 GHz。
- 阻带相对上一轮: 4.5 GHz 处约 −10.3 dB，仍低于 −10 dB。slot_length 不是这段抬起的主因。
- 下一轮 / 停止理由: 回到 g1。10.5 mm 把 4.5 GHz 压到刚过 −10 dB。收到 9.5 mm，让该处重新高于 −10 dB。

## Round 007

- 假设: g1=10.5 mm 把 4.5 GHz 抬起压到刚过 −10 dB。收到 9.5 mm，该处应重新高于 −10 dB。
- 改动（变量 / 旧值 → 新值）: g1 10.5 mm → 9.5 mm
- Analyze: Setup1，job_id: job_d2c4ca72e2ba474b95ca1a9e5f9f9bbe
- S11 文件: round-007-s11.csv
- −10 dB 频段相对上一轮: 变为约 1.00–1.85 GHz；3.05–4.15 GHz；5.35–11.35 GHz。下通带重新分开；上通带从 10.35 延到 11.35 GHz。
- 阻带相对上一轮: 4.15–5.35 GHz 清晰抬起，峰值约 −8.5 dB @ 4.8 GHz。阻带仍略偏低、偏浅。
- 下一轮 / 停止理由: 加大 C 槽开口 l2，看阻带是否上移、下通带是否变宽。

## Round 008

- 假设: l2 是 C 槽开口。加大开口应让阻带上移、下通带变宽。
- 改动（变量 / 旧值 → 新值）: l2 1.2 mm → 2.2 mm
- Analyze: Setup1，job_id: job_84fe829fd4f245c0966276beef6c1d4e
- S11 文件: round-008-s11.csv
- −10 dB 频段相对上一轮: 仍约 1.00–1.75 GHz；3.05–4.10 GHz；5.35–11.25 GHz。与 Round 007 几乎重合，下沿和上沿都略差一格。
- 阻带相对上一轮: 仍约 4.10–5.35 GHz，峰值约 −8.4 dB @ 4.8 GHz。l2 几乎没动阻带位置。
- 下一轮 / 停止理由: Analyze 预算 8 次用尽。未保存工程。末态变量：patch_r=9.0 mm, slot_length=14 mm, sw=0.8 mm, g1=9.5 mm, l2=2.2 mm；其余与开场相同。最后一轮 CSV 已复制为 s11.csv。
