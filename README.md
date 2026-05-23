# Delta Force Skill Minimal

> 注意：利润最优模式暂时不要使用。该模式依赖远程利润接口，目前远程接口不可用；请使用固定物品制造模式。

## 免责声明

本项目及其自动化能力仅用于个人场景下减少重复性游戏负担：希望让使用者在游戏时间之外更专注生活、工作和学习，在游戏时间之内降低重复操作成本、提升正常游戏体验。

本项目不支持、不鼓励、也不应被用于影响游戏经济平衡、破坏公平性、批量牟利、规避游戏规则或对其他玩家体验产生负面影响的操作。使用者应自行遵守游戏服务条款、社区规则和所在地区的相关规定，并自行承担使用自动化工具带来的账号、数据和合规风险。

如果你发现本项目中的能力可能被误用，欢迎通过 issue 提出收敛建议、风险提示或安全边界优化。

用于《三角洲行动》基地内特勤处、交易行、部门兑换和统计页面的本地自动化工具。

当前设计原则：
- 固定入口、固定按钮优先使用模板匹配。
- 动态文本、倒计时、价格、物品名称优先使用 OCR。
- 生产物品选择已经改为 OCR 路径，并支持在左侧物品列表中滚动查找。
- 制造策略和游戏执行解耦：策略层决定“造什么”，游戏执行层决定“怎么造”。

## 安装依赖

推荐使用仓库自带安装脚本：

```powershell
cd D:\delta-force-skill-minimal
.\install_dependencies.ps1
```

这个脚本会：
- 使用当前系统 Python 安装依赖。
- 安装 `requirements.txt` 中的 GUI、OCR、图像识别、统计和 API 依赖。
- 安装完成后验证关键模块能否导入。

如果希望隔离环境，可以创建 `.venv`：

```powershell
.\install_dependencies.ps1 -UseVenv
.\.venv\Scripts\Activate.ps1
```

只检查依赖是否可用，不执行安装：

```powershell
.\install_dependencies.ps1 -VerifyOnly
```

依赖来源：

```text
requirements.txt
```

主要依赖包括：
- `pywin32`：Windows 窗口、截图、鼠标键盘操作。
- `Pillow`、`opencv-python`、`numpy`：截图处理和模板匹配。
- `rapidocr`、`onnxruntime-directml`：本地 OCR。
- `openai`、`python-dotenv`：可选的外部模型/API 配置。
- `psutil`：进程检测。

`cc-connect.cmd` 属于外部通信环境，不由本仓库安装脚本安装。

## 脚本清单

当前仓库根目录下的脚本：

```text
install_dependencies.ps1
watch_collect_produce_dynamic.ps1
main.py
```

用途说明：
- `install_dependencies.ps1`：安装并验证 Python 依赖。
- `watch_collect_produce_dynamic.ps1`：动态循环执行特勤处收取和制造，根据下一次预计完成时间安排下轮执行。
- `main.py`：所有自动化能力的 CLI 入口，包含截图、识别、收取、制造、购买、兑换、统计页面等命令。

## 常用命令

登录、启动和进入大厅：

```powershell
# 一键流程：未登录时发送二维码，扫码后启动游戏，并在识别到 Tab 开始游戏时进入大厅
python main.py login_launch_and_enter_game --login-channel qq
python main.py login_launch_and_enter_game --login-channel wechat

# 分段流程：只发送/刷新登录二维码
python main.py refresh_qr_send --login-channel qq --message "WeGame QQ扫码登录二维码"
python main.py refresh_qr_send --login-channel wechat --message "WeGame 微信二维码"

# 分段流程：已登录 WeGame 后启动三角洲并进入大厅
python main.py launch_and_enter_game

# 仅处理游戏内 Tab 开始游戏提示
python main.py enter_game_by_tab_prompt
```

说明：
- QQ/微信登录页切换使用 WeGame 登录窗口的归一化坐标。
- 二维码失效时优先匹配二维码中心旋转箭头模板；二维码有效时只截图发送。
- 进入游戏时会先 OCR 识别 `Tab` 和 `开始游戏`，再激活游戏窗口、点击中心拿焦点、发送 `Tab`。

基础状态：

```powershell
python main.py windows
python main.py screenshot
python main.py buttons
python main.py status
python main.py next_action
python main.py collect_completed
```

特勤处固定物品制造：

```powershell
python main.py produce_station_item workbench "4.6x30mm" --dry-run
python main.py produce_station_items "tech_center=svd" "workbench=4.6x30mm" "pharmacy_station=精密护甲维修包" "armor_bench=精英防弹背心"
```

利润最优制造：

> 暂时不要使用以下利润最优命令：该模式依赖远程利润接口，目前该接口不可用。请改用固定物品制造模式。

```powershell
python main.py plan_swat_products --metric hourlyProfit
python main.py produce_swat_products --metric hourlyProfit
python main.py produce_swat_products --metric profit
```

交易行购买：

```powershell
python main.py buy_market_item "7.62x51 M80" 400
```

部门兑换：

```powershell
python main.py redeem_department_item "医疗部门" "户外医疗箱" 3
```

统计页面：

```powershell
python main.py analytics_server --host 127.0.0.1 --port 8765
python main.py analytics_summary --limit 20
```

统计页面地址：

```text
http://127.0.0.1:8765/
```

## 动态循环脚本

固定物品模式：

```powershell
.\watch_collect_produce_dynamic.ps1 -ProductionMode fixed
```

利润最优模式：

> 暂时不要使用以下利润最优循环模式：该模式依赖远程利润接口，目前该接口不可用。请改用 `-ProductionMode fixed`。

```powershell
.\watch_collect_produce_dynamic.ps1 -ProductionMode profit
.\watch_collect_produce_dynamic.ps1 -ProductionMode profit -SwatMetric hourlyProfit
.\watch_collect_produce_dynamic.ps1 -ProductionMode profit -SwatMetric profit
```

固定模式自定义物品：

```powershell
.\watch_collect_produce_dynamic.ps1 -ProductionMode fixed -FixedSpecs "tech_center=svd","workbench=4.6x30mm","pharmacy_station=精密护甲维修包","armor_bench=精英防弹背心"
```

## 生产物品选择

当前生产物品选择链路：

```text
produce_station_item
  -> 点击空闲槽位
  -> click_item_by_ocr_text(item_name)
     -> OCR 当前列表
     -> 找不到则在物品列表区域内滚动
     -> 重新 OCR
     -> 到底或超过最大滚动次数才失败
```

说明：
- 生产物品名称不再先走模板匹配。
- 固定按钮、入口、确认按钮仍保留模板匹配。
- 生产物品列表滚动区域使用相对坐标，会按当前游戏窗口尺寸缩放。

当前确认可用的 4K 基准区域：

```text
区域：(270,815) 到 (770,1405)
滚动点：(520,1140)
```

## 分辨率适配

目标支持 16:9 游戏窗口：

```text
1920x1080
2560x1440
3840x2160
```

实现方式：
- 模板以 4K 截图为基准，识别时按窗口宽度自动缩放。
- 模板匹配会尝试临近尺度，降低 DPI 或截图缩放误差带来的影响。
- ROI、交易行滑条、购买按钮、生产物品列表滚动区域使用相对坐标。
- 黄色完成态、空闲态、倒计时 OCR 的局部检测阈值按窗口面积或高度缩放。

## 利润数据

远端利润接口配置：

> 当前远端利润接口不可用，利润最优模式暂时不要使用。本节仅保留历史配置说明。

```powershell
python main.py config --swat-cookie "..." --swat-version "..." --swat-swimlane "..."
```

`4.6x30mm` 当前本地配置已对齐远端利润接口：

```text
unitExpectedRevenue = 3997
outputQuantity = 150
expectedRevenue = 599550
```

运行时如果 OCR 读出的单价明显低于本地可信值，会忽略该异常读数，避免把收益写成错误的小值。

## 模板与 OCR 边界

仍然建议使用模板匹配的场景：
- 特勤处入口。
- 空闲槽位。
- 固定按钮。
- 退出、确认类按钮。

优先使用 OCR 的场景：
- 生产物品名称。
- 动态数字。
- 会滚动的列表。
- 价格、倒计时、库存等动态文本。
