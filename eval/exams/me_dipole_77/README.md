# 开考（人看）

应试 Agent 只应看到本文件夹。不要用 Cursor 打开 `hfss-mcp` 仓库根。

0. **开考前**确认 `runs/` 里只有 `.gitkeep`。若还有上一场的时间戳目录，先不要开考，把那些目录清出本文件夹。
1. Electronics Desktop 打开  
   `cases/me_dipole_77/sandbox/me_dipole_77.aedt`  
   设计 `77GHZantenna`。不要打开 `nominal/`。
2. Cursor → Open Folder → **本目录**  
   `eval/exams/me_dipole_77`
3. 确认用户级 MCP `hfss-mcp` 已连接（新窗口一般会带上 `~/.cursor/mcp.json`）。
4. 新开 Agent 聊天，只发：**执行测试**  
   卷面两项：最靠近 77 GHz 的点 \(S_{11}\le -10\,\mathrm{dB}\)，且该连续通带相对带宽 > 25%。本场预算是 **求解时间合计 4 小时**（只计 HFSS 在算的时间，Agent 自己加总），满了必须交卷。手续是 Optimetrics 联合扫参（分组和密度由本结构判断），不是一串单点 Analyze。
5. 结束后回到仓库根判卷（应试窗口里不要跑）。判完把本场 `runs/<run-id>` 清出本文件夹，再开下一场。

```powershell
cd C:\Users\Gongzhui\Documents\Projects\hfss-mcp
uv run python eval/score_run.py --exam me_dipole_77 --run eval/exams/me_dipole_77/runs/<run-id>
```
