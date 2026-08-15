# 开考（人看）

应试 Agent 只应看到本文件夹。不要用 Cursor 打开 `hfss-mcp` 仓库根。

1. Electronics Desktop 打开  
   `cases/uwb_circular_notch/sandbox/uwb_circular_notch.aedt`  
   设计 `CircularMonopole`。不要打开 `nominal/`。
2. Cursor → Open Folder → **本目录**  
   `eval/exams/uwb_circular_notch`
3. 确认用户级 MCP `hfss-mcp` 已连接（新窗口一般会带上 `~/.cursor/mcp.json`）。
4. 新开 Agent 聊天，只发：**执行测试**  
   手续是 Optimetrics 联合扫参（分组和密度由本结构判断），不是一串单点 Analyze。
5. 结束后回到仓库根判卷（应试窗口里不要跑）：

```powershell
cd C:\Users\Gongzhui\Documents\Projects\hfss-mcp
uv run python eval/score_run.py --exam uwb_circular_notch --run eval/exams/uwb_circular_notch/runs/<run-id>
```
