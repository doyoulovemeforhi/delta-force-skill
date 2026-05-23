---
name: delta-force-skill-minimal
description: 三角洲行动特勤处制造、收取、交易行购买、部门兑换与动态调度技能。
version: 0.3.0
---

# Delta Force Skill

## 目标

这个 skill 用于《三角洲行动》基地内自动化，重点覆盖：
- 特勤处收取
- 特勤处制造
- 利润最优制造策略
- 交易行购买
- 部门兑换
- 动态循环守护
- 本地统计页

## 核心命令

登录、启动和进入大厅：

```powershell
python main.py login_launch_and_enter_game --login-channel qq
python main.py login_launch_and_enter_game --login-channel wechat
python main.py refresh_qr_send --login-channel qq
python main.py launch_and_enter_game
python main.py enter_game_by_tab_prompt
```

执行规则：
- 优先使用 `login_launch_and_enter_game` 跑完整流程。
- 如果用户已经扫码并停在 WeGame 主界面，使用 `launch_and_enter_game`。
- 如果游戏已经打开且画面显示 `Tab 开始游戏`，使用 `enter_game_by_tab_prompt`，不要直接裸按 `Tab`。
- `enter_game_by_tab_prompt` 会先 OCR 识别提示，再激活游戏窗口、点击中心拿焦点，最后发送 `Tab`。

全局状态：

```powershell
python main.py status
python main.py next_action
python main.py safe_for_automation
python main.py screenshot
python main.py desktop_screenshot
```

特勤处收取：

```powershell
python main.py check_complete <station>
python main.py collect_station <station>
python main.py collect_completed
```

固定物品制造：

```powershell
python main.py evaluate_production workbench "4.6x30mm"
python main.py produce_station_item workbench "4.6x30mm" --dry-run
python main.py produce_station_items "tech_center=svd" "workbench=4.6x30mm" "pharmacy_station=精密护甲维修包" "armor_bench=精英防弹背心"
```

利润最优制造：

```powershell
python main.py plan_swat_products --metric hourlyProfit
python main.py produce_swat_products --metric hourlyProfit
python main.py produce_swat_products --metric profit
```

交易行：

```powershell
python main.py find_market_item "7.62x51 M80"
python main.py click_market_item "7.62x51 M80"
python main.py read_market_detail
python main.py set_market_quantity 200
python main.py buy_market_item "7.62x51 M80" 400
```

部门兑换：

```powershell
python main.py redeem_department_item "医疗部门" "户外医疗箱" 3
```

统计页：

```powershell
python main.py analytics_server --host 127.0.0.1 --port 8765
python main.py analytics_summary --limit 20
```

## 生产物品选择规则

当前生产物品选择已经改为纯 OCR 路径：

```text
produce_station_item
  -> 点击空闲槽位
  -> click_item_by_ocr_text(item_name)
```

`click_item_by_ocr_text` 的行为：
- 先 OCR 当前列表
- 若当前屏未找到目标物品，则在生产物品列表区域内滚动
- 滚动后重新截图再 OCR
- 检测到列表内容重复或达到最大滚动次数时停止
- 到底仍未找到，返回 `ocr_text_not_found_after_scroll`

注意：
- 不再先执行 `click_button(item_name)` 模板匹配
- 这个变化只影响“生产物品选择”这一步
- 不影响收取、补齐、生产按钮、交易行和兑换流程

## 生产物品列表滚动区域

当前确认可用的 4K 区域：

```text
区域：(270,815) 到 (770,1405)
滚动点：(520,1140)
```

实现方式：
- 区域常量保存在 `scripts/games/delta_force.py`
- 使用相对坐标，按当前窗口尺寸缩放
- 滚动时将鼠标移动到区域中部偏下位置再发送滚轮事件

## 分辨率适配

目标支持 16:9 游戏窗口：

```text
1920x1080
2560x1440
3840x2160
```

实现规则：
- 模板以 4K 截图为基准，运行时按游戏窗口宽度缩放
- 模板识别默认尝试 0.9、1.0、1.1 三个邻近尺度
- 交易行、生产物品列表滚动区域、按钮点击点都使用相对坐标
- 黄色完成态和空闲态相关阈值按窗口尺寸缩放

## 制造模式

### 1. 固定物品模式

适合你已经明确指定每个部门要做什么。

```powershell
python main.py produce_station_items "tech_center=svd" "workbench=4.6x30mm" "pharmacy_station=精密护甲维修包" "armor_bench=精英防弹背心"
```

### 2. 利润最优模式

适合根据远端利润接口自动选当前最优项目。

```powershell
python main.py produce_swat_products --metric hourlyProfit
```

策略层与执行层解耦：
- `scripts/swat_product_strategy.py` 负责拉取和规划利润最优项目
- `scripts/games/delta_force.py` 负责实际制造执行
- `main.py` 负责把计划与执行组合起来

## 动态循环脚本

推荐脚本：

```powershell
.\watch_collect_produce_dynamic.ps1
```

支持两种模式：

固定模式：

```powershell
.\watch_collect_produce_dynamic.ps1 -ProductionMode fixed
```

利润模式：

```powershell
.\watch_collect_produce_dynamic.ps1 -ProductionMode profit
.\watch_collect_produce_dynamic.ps1 -ProductionMode profit -SwatMetric hourlyProfit
.\watch_collect_produce_dynamic.ps1 -ProductionMode profit -SwatMetric profit
```

固定模式也支持自定义规格：

```powershell
.\watch_collect_produce_dynamic.ps1 -ProductionMode fixed -FixedSpecs "tech_center=svd","workbench=4.6x30mm","pharmacy_station=精密护甲维修包","armor_bench=精英防弹背心"
```

## 收益与统计

制造、购买、兑换、收取会写入本地 SQLite：

```text
logs/analytics.sqlite3
```

统计页：

```text
http://127.0.0.1:8765/
```

`4.6x30mm` 的当前配置已修正为：

```text
unitExpectedRevenue = 3997
outputQuantity = 150
expectedRevenue = 599550
```

同时制造流程加入了保护：
- 若 OCR 误读出的单价明显低于本地可信值，则忽略该异常值

## 实践规则

- 动态数字不要做模板。
- 生产物品名称不要做模板，统一走 OCR。
- 固定按钮、入口、空闲槽位、确认按钮适合继续保留模板。
- 对战页面或非基地页面不得自动执行破坏性操作。
- 如果 `safe_for_automation` 失败，优先退出，不要硬点。
