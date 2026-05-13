---
name: delta-force-skill-minimal
description: 三角洲行动特勤处制造与收取辅助。截图驱动+安全检测+动态调度+Agent 守护。静止时零干扰，按需时精准触发。
version: 0.2.0
---

# Delta Force Skill — Agent Guardian Edition

## 架构

```
┌─────────────────────────────────────────────────────┐
│  Agent (守护者 / 审视者)                              │
│  python main.py status          → 全局状态快照       │
│  python main.py next_action     → 要不要动？何时动？ │
│  python main.py collect_completed → 收取已完成       │
│  python main.py produce_station_items → 启动制造     │
│  Get-Content logs/status.json   → 读最新状态         │
│  Get-Content logs/*.log         → 审计明细日志       │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│  独立进程 (schedule / watch loop)                     │
│  scheduled_collect_and_produce.ps1  → 单次执行入口   │
│  watch_collect_produce_dynamic.ps1 → 动态循环守护    │
│  → 每次运行后自动写入 logs/status.json               │
│  → 生产状态持久化到 logs/production_state.json       │
└─────────────────────────────────────────────────────┘
```

Agent 是脚本的**守护者**：脚本独立跑，Agent 通过 `status` / `next_action` 审视全局，必要时介入（手动收取、重启循环、分析异常）。

## Agent 审视清单

### 1. 快速查看全局状态

```bash
python main.py status
```

返回：
- `summary`: 人类可读摘要，如 "workbench 已完成待收取"
- `actionPlan.needAction`: 是否需要操作
- `productionState`: 各站台当前生产状态 + 预计完成时间
- `gameRunning` / `windowVisible`: 游戏是否在运行
- `recentLogs`: 最近 5 次执行日志

### 2. 判断是否需要干预

```bash
python main.py next_action
```

- `needAction: true` → 有站台到期或空闲，应该收/造
- `needAction: false` → 都在生产中，`nextSuggestedRun` 是下次该醒来的时间

### 3. 审计最近执行记录

```bash
# 读状态快照
Get-Content D:\delta-force-skill-minimal\logs\status.json

# 读最新日志
Get-Content D:\delta-force-skill-minimal\logs\scheduled_collect_produce_*.log | Select-Object -Last 100

# 查看生产历史
Get-Content D:\delta-force-skill-minimal\logs\production_state.json
```

### 4. Agent 该做什么

| 信号 | 行动 |
|---|---|
| `needAction: true`, `gameRunning: true`, 用户不在玩 | 直接 `collect_completed` + `produce_station_items` |
| `needAction: true`, 用户在玩/对战 | 等待，用户退出后再说 |
| 连续 3 轮 `game_unsafe_for_automation` 且物品严重超时 | 提醒用户尽快回基地收取 |
| `status.json` 超过 2 小时未更新 | 检查 watch loop 是否还活着 |
| 日志中有 `error` 或异常 | 读日志定位问题，人工介入 |
| `nextSuggestedRunDelta` > 8 小时 | 无需频繁检查，降低审视频率 |

## 安全机制

### 对战检测

所有键盘/鼠标操作前先截图检测是否在特勤处基地。不在 = 静默跳过，零按键。

```bash
python main.py safe_for_automation   # 独立检测，不按键
```

### 利润保护

制造前读取成本/收益，默认拒绝亏本制造。

```bash
python main.py produce_station_items "workbench=762x51mm M62" --allow-unprofitable   # 跳过利润保护
```

## 常用命令

### 截图与按钮

```bash
python main.py screenshot
python main.py desktop_screenshot
python main.py find <button_name>
python main.py findall
python main.py buttons
python main.py click_button <button_name> [--background]
python main.py click_text "描述文字"
python main.py key esc
```

### 特勤处收取

```bash
python main.py check_teqinchu_idle
python main.py check_complete <station>
python main.py collect_station <station>
python main.py collect_completed
```

### 物品制造

```bash
python main.py evaluate_production workbench "762x51mm M62"
python main.py produce_station_item workbench "762x51mm M62" [--dry-run] [--allow-unprofitable]
python main.py produce_station_items "tech_center=svd" "armor_bench=精英防弹背心" "pharmacy_station=精密护甲维修包"
```

### 屏幕数值读取

```bash
python main.py read_metric tax_after_price
```

支持两种模式：
- `rapidocr`: 本地 OCR，当前唯一保留的数值/剩余时间识别方案

```bash
```

### 状态与调度

```bash
python main.py status                       # 全局状态（Agent 审视入口）
python main.py next_action                  # 是否有活 + 下次建议时间
python main.py safe_for_automation          # 当前是否安全（在基地？）
python main.py launch_status                # 游戏是否在运行
```

### 被挤下线

```bash
python main.py check_forced_offline
python main.py handle_forced_offline
```

## 调度方案

### 方案 A：一次性执行

```powershell
cd D:\delta-force-skill-minimal
.\scheduled_collect_and_produce.ps1 -NotifyOnSuccess
```

### 方案 B：动态循环（推荐）

根据制造完成时间自动调整触发间隔，延后 2 分钟醒来确保物品已完成。

```powershell
cd D:\delta-force-skill-minimal
.\watch_collect_produce_dynamic.ps1 -NotifyOnSuccess
```

参数：`-BufferMinutes 2`（延后分钟数）、`-FallbackMinutes 30`（无数据时兜底间隔）。

### 方案 C：Windows 计划任务

```powershell
.\install_collect_produce_task.ps1 -Dynamic -NotifyOnSuccess    # 动态模式（开机自启）
.\install_collect_produce_task.ps1 -IntervalMinutes 30          # 固定间隔（旧模式）
.\install_collect_produce_task.ps1 -Uninstall                    # 卸载
```

## Agent 通知

定时脚本通过 `agent_notify.ps1` 发通知。默认成功不通知（避免噪音）。配置：

```powershell
Copy-Item agent_notify.config.example.json agent_notify.config.json
# 编辑 agent_notify.config.json，设置通知通道
```

### 触发 Agent 审视

异常时可以让脚本主动唤醒 Agent：

```powershell
.\scheduled_collect_and_produce.ps1 -NotifyProviders openclaw-agent
```

Agent 收到事件后读取 `logs/status.json` 和最新日志进行分析。

## 已验证按钮模板

`games/delta-force/assets/buttons/`：

- `teqinchu`: 顶部"特勤处"导航
- `idle_slot`: 生产槽"空闲中"
- `workbench`: 工作台部门卡片
- `tech_center`: 技术中心部门卡片
- `pharmacy_station`: 药房部门卡片
- `armor_bench`: 护甲台部门卡片
- `one_click_fill`: "一键补齐"按钮
- `produce_button`: "生产"按钮
- `forced_offline_exit`: 被挤下线"退出游戏"按钮

## 经验规则

- 不要用包含动态数字的模板（金额、倒计时、库存数）
- 大按钮匹配背景/边框，不要把无关边缘裁进去
- `Esc` 可能只退一层，需要循环检测目标页面
- 确认按钮金额动态变化 → 用 `find_fill_confirm` / `click_fill_confirm`（HSV 绿色检测）
- 制造前发现无空闲槽 → 代码自动尝试收取，收完再重新检测
- 被挤下线 → `handle_forced_offline` 点击退出后自动回到特勤处
 
## Agent CLI one-shot report

Use these providers when the script should start one agent turn and ask it to
read `logs/status.json`, the current round log, and the screenshot before
reporting back.

```powershell
# Codex one-shot agent report, then relay the final message via cc-connect.
.\scheduled_collect_and_produce.ps1 -NotifyOnSuccess -NotifyProviders codex-agent

# OpenClaw one-shot agent report. Set openclawAgent.deliver/reply fields in
# agent_notify.config.json when the reply should be delivered to a channel.
.\scheduled_collect_and_produce.ps1 -NotifyOnSuccess -NotifyProviders openclaw-agent

# Direct cc-connect message plus Codex agent report.
.\scheduled_collect_and_produce.ps1 -NotifyOnSuccess -NotifyProviders codex,codex-agent
```

Provider names:
- `codex`: direct `cc-connect.cmd send` message.
- `codex-agent`: runs `codex.cmd exec`, writes the final agent message under
  `logs/agent_reports/`, then optionally relays that message via `codex`.
- `openclaw-agent`: runs `openclaw.cmd agent` with the same event prompt.
- `openclaw-message`: direct OpenClaw message send.
