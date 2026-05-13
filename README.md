# Delta Force Skill Minimal

一个用于“三角洲行动”基地/特勤处物品制造流程的最小 skill 骨架。

它遵循“截图 -> 识别 -> 点击 -> 再截图”的闭环：

- 固定按钮优先使用 OpenCV 模板识别。
- 目标物品名称、动态 UI 或模板缺失时，使用 GUI-Plus 多模态模型兜底。
- 每个关键动作之后都会再次截图并返回 JSON。

## 安装

```bash
cd E:\下载\delta-force-skill-minimal
pip install -r requirements.txt
```

如果要使用 `click_text`、`craft` 的物品名称定位能力，需要配置 API Key：

```bash
python main.py config --set-api-key YOUR_DASHSCOPE_API_KEY
```

或者设置环境变量：

```bash
set DASHSCOPE_API_KEY=YOUR_DASHSCOPE_API_KEY
```

## 命令

```bash
python main.py windows
python main.py screenshot
python main.py buttons
python main.py produce_762x51mm_m62 --dry-run
python main.py produce_762x51mm_m62
python main.py produce_station_item workbench "762x51mm M62" --dry-run
python main.py produce_station_items "tech_center=物品模板名" "workbench=762x51mm M62" "pharmacy_station=物品模板名" "armor_bench=物品模板名" --dry-run
python main.py collect
```

## 补模板的方法

1. 打开三角洲行动并停在目标 UI。
2. 运行 `python main.py screenshot`。
3. 从 `screenshots/三角洲行动/` 里裁剪按钮小图。
4. 把按钮图保存到 `games/delta-force/assets/buttons/`。
5. 文件名要和 `buttons.json` 中的 key 一致，例如 `produce_button.png`。
6. 根据按钮大致位置调整 `buttons.json` 的 `roi` 和 `threshold`。

## 当前占位按钮

- `base_logistics`: 基地特勤处/后勤入口。
- `manufacture_tab`: 制造/生产页面入口。
- `back_button`: 返回按钮。
- `material_insufficient`: 材料不足状态。
- `production_in_progress`: 生产中状态。

## 推荐迭代顺序

1. 先跑通 `produce_762x51mm_m62` 的固定制造流程。
2. 给高频按钮补模板：`workbench`、`idle_slot`、`one_click_fill`、`produce_button`。
3. 给异常状态补模板：`material_insufficient`、`production_in_progress`。
4. 再把流程拆成更精确的状态机。

## 注意

这个骨架定位为操作辅助，不建议做无人值守循环。涉及材料消耗的确认动作前，建议保留截图校验或人工确认。
