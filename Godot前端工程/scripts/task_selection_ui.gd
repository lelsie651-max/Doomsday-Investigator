extends Control
## 任务选择界面
##
## 显示12个可选任务，玩家勾选最多5个，点确认提交。

signal tasks_submitted  # 提交成功后发出，通知GameUI切换阶段

@onready var title_label: Label = $MarginContainer/VBox/TitleLabel
@onready var hint_label: Label = $MarginContainer/VBox/HintLabel
@onready var task_list: VBoxContainer = $MarginContainer/VBox/ScrollContainer/TaskList
@onready var confirm_btn: Button = $MarginContainer/VBox/BottomBar/ConfirmBtn
@onready var shop_btn: Button = $MarginContainer/VBox/BottomBar/ShopBtn
@onready var selected_count_label: Label = $MarginContainer/VBox/BottomBar/SelectedCountLabel

var _task_pool: Array = []          # 当日任务池数据
var _selected_ids: Array = []       # 玩家已选任务ID
var _max_hours: int = 5             # 最大行动力
var _checkboxes: Array = []         # CheckBox引用列表

# 房间中文名映射
const ROOM_NAMES := {
    "office": "主办公区",
    "meeting": "会议室",
    "warehouse": "仓库",
    "pantry": "茶水间",
    "reception": "接待区",
}

# 房间颜色标记
const ROOM_COLORS := {
    "office": "cornflowerblue",
    "meeting": "coral",
    "warehouse": "darkkhaki",
    "pantry": "mediumseagreen",
    "reception": "mediumpurple",
}


func _ready() -> void:
    confirm_btn.pressed.connect(_on_confirm)
    shop_btn.pressed.connect(_on_open_shop)
    confirm_btn.disabled = true
    hint_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART

    # 监听工作阶段开始（自动隐藏）
    NetworkManager.work_started.connect(func(_d): visible = false)


func setup(data: Dictionary) -> void:
    """接收后端数据，初始化任务列表"""
    _task_pool = data.get("task_pool", [])
    _max_hours = data.get("action_points", 5)
    _selected_ids.clear()
    _checkboxes.clear()

    title_label.text = "第%d天 - 选择今日任务" % data.get("day", 1)
    var base_hint = "共%d个任务可选，你有%d小时行动力。勾选要做的任务：" % [_task_pool.size(), _max_hours]
    hint_label.text = base_hint

    # 清空旧的任务列表
    for child in task_list.get_children():
        child.queue_free()

    # 等一帧确保旧节点清除
    await get_tree().process_frame

    # 按房间分组
    var grouped: Dictionary = {}
    for task in _task_pool:
        var room: String = task.get("room", "unknown")
        if room not in grouped:
            grouped[room] = []
        grouped[room].append(task)

    # 按房间顺序创建UI(2 列网格布局)
    var room_order := ["office", "meeting", "warehouse", "pantry", "reception"]
    for room_key in room_order:
        if room_key not in grouped:
            continue
        var tasks: Array = grouped[room_key]
        var room_name: String = ROOM_NAMES.get(room_key, room_key)
        var room_color: String = ROOM_COLORS.get(room_key, "white")

        # 房间标题
        var room_label := RichTextLabel.new()
        room_label.bbcode_enabled = true
        room_label.fit_content = true
        room_label.scroll_active = false
        room_label.text = "[b][color=%s]━━ %s ━━[/color][/b]" % [room_color, room_name]
        room_label.custom_minimum_size = Vector2(0, 32)
        task_list.add_child(room_label)

        # 房间内任务卡片(2 列网格)
        var grid := GridContainer.new()
        grid.columns = 2
        grid.add_theme_constant_override("h_separation", 16)
        grid.add_theme_constant_override("v_separation", 12)
        grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        task_list.add_child(grid)

        for task in tasks:
            _create_task_card(task, room_color, grid)

        # 房间间距
        var spacer := Control.new()
        spacer.custom_minimum_size = Vector2(0, 8)
        task_list.add_child(spacer)

    _update_selection_ui()


func _create_task_card(task: Dictionary, room_color: String, parent: Node) -> void:
    """创建单个任务卡片(紧凑垂直布局,选中时整张高亮)。"""
    var task_id: String = task.get("id", "")

    # 卡片容器
    var card := PanelContainer.new()
    card.custom_minimum_size = Vector2(380, 90)
    card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    card.set_meta("task_id", task_id)

    # 卡片样式(默认 + 选中)
    var stylebox_normal := StyleBoxFlat.new()
    stylebox_normal.bg_color = Color(0.18, 0.18, 0.22, 0.9)
    stylebox_normal.border_width_left = 2
    stylebox_normal.border_width_right = 2
    stylebox_normal.border_width_top = 2
    stylebox_normal.border_width_bottom = 2
    stylebox_normal.border_color = Color(0.3, 0.3, 0.36, 0.8)
    stylebox_normal.corner_radius_top_left = 8
    stylebox_normal.corner_radius_top_right = 8
    stylebox_normal.corner_radius_bottom_left = 8
    stylebox_normal.corner_radius_bottom_right = 8
    stylebox_normal.content_margin_left = 12
    stylebox_normal.content_margin_right = 12
    stylebox_normal.content_margin_top = 10
    stylebox_normal.content_margin_bottom = 10
    card.add_theme_stylebox_override("panel", stylebox_normal)
    card.set_meta("stylebox_normal", stylebox_normal)
    card.set_meta("room_color_str", room_color)

    parent.add_child(card)

    # 卡片内部 VBox
    var vbox := VBoxContainer.new()
    vbox.add_theme_constant_override("separation", 6)
    card.add_child(vbox)

    # 顶部:CheckBox + 任务名
    var top_hbox := HBoxContainer.new()
    top_hbox.add_theme_constant_override("separation", 8)
    vbox.add_child(top_hbox)

    var checkbox := CheckBox.new()
    checkbox.text = ""
    checkbox.custom_minimum_size = Vector2(28, 0)
    checkbox.set_meta("task_id", task_id)
    checkbox.toggled.connect(_on_task_toggled.bind(task_id))
    # 选中状态变化时同步卡片高亮
    checkbox.toggled.connect(_on_card_toggled.bind(card))
    top_hbox.add_child(checkbox)
    _checkboxes.append(checkbox)

    var name_label := Label.new()
    name_label.text = task.get("name", "???")
    name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    name_label.add_theme_font_size_override("font_size", 16)
    name_label.add_theme_color_override("font_color", Color(0.95, 0.95, 0.92))
    top_hbox.add_child(name_label)

    # 分隔线
    var sep := HSeparator.new()
    sep.add_theme_color_override("separator", Color(0.4, 0.4, 0.45, 0.5))
    vbox.add_child(sep)

    # 底部:风险 + 奖励 紧凑横排
    var bottom_hbox := HBoxContainer.new()
    bottom_hbox.add_theme_constant_override("separation", 12)
    vbox.add_child(bottom_hbox)

    var risk: String = task.get("risk_tag", "")
    if risk != "":
        var risk_label := Label.new()
        risk_label.text = "⚠️ " + risk
        risk_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        risk_label.add_theme_font_size_override("font_size", 13)
        risk_label.add_theme_color_override("font_color", Color(0.85, 0.55, 0.35))
        risk_label.clip_text = true
        bottom_hbox.add_child(risk_label)

    var reward_type: String = task.get("reward_type", "none")
    if reward_type != "none":
        var reward_label := Label.new()
        reward_label.text = _get_reward_text(reward_type)
        reward_label.add_theme_font_size_override("font_size", 14)
        reward_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
        bottom_hbox.add_child(reward_label)


func _on_card_toggled(is_pressed: bool, card: PanelContainer) -> void:
    """卡片选中/取消时切换样式(整张高亮)。"""
    if not is_instance_valid(card):
        return
    var room_color_str: String = str(card.get_meta("room_color_str", "white"))

    if is_pressed:
        # 选中样式: 用房间色作边框
        var stylebox_selected := StyleBoxFlat.new()
        stylebox_selected.bg_color = Color(0.22, 0.24, 0.30, 0.95)
        stylebox_selected.border_width_left = 3
        stylebox_selected.border_width_right = 3
        stylebox_selected.border_width_top = 3
        stylebox_selected.border_width_bottom = 3
        stylebox_selected.border_color = Color.from_string(room_color_str, Color(0.5, 0.7, 0.95))
        stylebox_selected.corner_radius_top_left = 8
        stylebox_selected.corner_radius_top_right = 8
        stylebox_selected.corner_radius_bottom_left = 8
        stylebox_selected.corner_radius_bottom_right = 8
        stylebox_selected.content_margin_left = 12
        stylebox_selected.content_margin_right = 12
        stylebox_selected.content_margin_top = 10
        stylebox_selected.content_margin_bottom = 10
        card.add_theme_stylebox_override("panel", stylebox_selected)
    else:
        # 恢复默认样式
        var stylebox_normal = card.get_meta("stylebox_normal")
        if stylebox_normal:
            card.add_theme_stylebox_override("panel", stylebox_normal)


func _create_task_item(task: Dictionary, _color: String) -> void:
    """创建单个任务选项（CheckBox + 描述）"""
    var hbox := HBoxContainer.new()
    hbox.custom_minimum_size = Vector2(0, 32)
    hbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    hbox.add_theme_constant_override("separation", 8)

    # CheckBox
    var checkbox := CheckBox.new()
    checkbox.text = ""
    checkbox.custom_minimum_size = Vector2(24, 0)
    checkbox.set_meta("task_id", task.get("id", ""))
    checkbox.toggled.connect(_on_task_toggled.bind(task.get("id", "")))
    hbox.add_child(checkbox)
    _checkboxes.append(checkbox)

    # 任务名称（固定宽度，防止挤压右侧内容）
    var name_label := Label.new()
    name_label.text = task.get("name", "???")
    name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    name_label.size_flags_stretch_ratio = 1.8
    name_label.clip_text = true
    hbox.add_child(name_label)

    # 风险标签（固定宽度）
    var risk: String = task.get("risk_tag", "")
    if risk != "":
        var risk_label := Label.new()
        risk_label.text = risk
        risk_label.custom_minimum_size = Vector2(150, 0)
        risk_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        risk_label.size_flags_stretch_ratio = 1.2
        risk_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
        risk_label.add_theme_color_override("font_color", Color(0.8, 0.5, 0.3))
        risk_label.clip_text = true
        hbox.add_child(risk_label)

    # 奖励标签（固定宽度）
    var reward_type: String = task.get("reward_type", "none")
    if reward_type != "none":
        var reward_label := Label.new()
        reward_label.text = _get_reward_text(reward_type)
        reward_label.custom_minimum_size = Vector2(52, 0)
        reward_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
        reward_label.clip_text = true
        hbox.add_child(reward_label)

    task_list.add_child(hbox)


func _get_reward_text(reward_type: String) -> String:
    match reward_type:
        "gold": return "💰"
        "affinity_boss": return "👔+"
        "affinity_colleague": return "🤝+"
        "suspicion_down": return "🔽嫌疑"
        "info": return "💡情报"
        _: return ""


func _on_task_toggled(is_pressed: bool, task_id: String) -> void:
    """任务勾选/取消勾选"""
    if is_pressed:
        if _selected_ids.size() >= _max_hours:
            # 超过上限，取消这次勾选
            for cb in _checkboxes:
                if cb.get_meta("task_id") == task_id:
                    cb.set_pressed_no_signal(false)
                    break
            return
        if task_id not in _selected_ids:
            _selected_ids.append(task_id)
    else:
        _selected_ids.erase(task_id)

    _update_selection_ui()


func _update_selection_ui() -> void:
    """更新选择计数和按钮状态"""
    var count := _selected_ids.size()
    selected_count_label.text = "已选 %d/%d 小时" % [count, _max_hours]

    if count == _max_hours:
        confirm_btn.disabled = false
        confirm_btn.text = "确认出发！（%d个任务）" % count
    else:
        confirm_btn.disabled = true
        if count < _max_hours:
            confirm_btn.text = "还需选择%d个任务" % (_max_hours - count)
        else:
            confirm_btn.text = "请取消%d个任务" % (count - _max_hours)

    # 如果已满，禁用未选中的checkbox
    for cb in _checkboxes:
        if not cb.button_pressed:
            cb.disabled = (count >= _max_hours)


func _on_confirm() -> void:
    """提交任务选择"""
    if _selected_ids.size() != _max_hours:
        return

    confirm_btn.disabled = true
    confirm_btn.text = "提交中..."

    NetworkManager.submit_task_selection(_selected_ids)
    tasks_submitted.emit()


func _on_open_shop() -> void:
    # 通过父节点找到ShopUI
    var shop = get_parent().get_node_or_null("ShopUI")
    if shop and shop.has_method("open_shop"):
        shop.open_shop()

