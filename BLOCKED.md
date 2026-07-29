# BLOCKED — 待裁决清单（benchmark 设施目标）

随交付提交。分类：A = 基线核对出入（证据+处置）；B = 顺手活（按任务书不做）；C = 已自行裁决（按任务书意图，备查）。

> 上一目标（真实 AEDT V0 演示）的 BLOCKED 全文在 git 历史（末次 8369a2a）。

## A · 基线核对出入

- **ruff 2 errors 来自可再生缓存**：按任务书顺序先跑 pytest 后，`ruff check .` 报
  I001/E701 两条，定位在 `.tmp_pytest/gen_py/3.12/__init__.py`——pywin32 COM 缓存
  （文件头自述 "this directory may be deleted to reset the COM cache"），由
  test_real_aedt 的 COM 调用生成。删除该目录后 ruff 回到 0，与任务书基线一致。
  非代码问题，未改任何产品/配置文件。

## B · 顺手活（按任务书一律不做，列此待裁决）

（暂无）

## C · 已自行裁决（按任务书意图，备查）

（暂无）
