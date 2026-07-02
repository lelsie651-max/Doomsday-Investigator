extends Control

## 主结局页(停留页)
## 显示结局结果 + 三个按钮:[查看回忆] [重新开始] [退出]
## NPC 记忆由独立 MemoryViewPopup 弹窗显示,不在本界面内

signal view_memories_pressed
signal restart_pressed
signal exit_pressed

var _ending_data: Dictionary = {}

# UI 节点
var _bg: ColorRect = null
var _ending_title_label: Label = null
var _ending_subtitle_label: Label = null
var _ending_stats_label: Label = null
var _view_memories_button: Button = null
var _restart_button: Button = null
var _exit_button: Button = null


func _ready() -> void:
    anchor_right = 1.0
    anchor_bottom = 1.0
    mouse_filter = Control.MOUSE_FILTER_STOP
    _build_ui()


func setup(data: Dictionary) -> void:
    _ending_data = data
    var ending = data.get("ending", {})

    _ending_title_label.text = "%s %s" % [str(ending.get("icon", "")), str(ending.get("title", ""))]
    _ending_subtitle_label.text = str(ending.get("subtitle", ""))

    var stats_text = "生存天数: %d/%d 天    收集证据: %d/%d 份" % [
        int(ending.get("current_day", 0)),
        5,
        int(ending.get("evidence_count", 0)),
        int(ending.get("required_evidence", 5)),
    ]
    _ending_stats_label.text = stats_text

    var ending_type = str(ending.get("ending_type", ""))
    var title_color = Color(0.95, 0.85, 0.4)
    if ending_type == "perfect_victory":
        title_color = Color(0.4, 0.95, 0.5)
    elif ending_type == "eliminated":
        title_color = Color(0.95, 0.4, 0.4)
    elif ending_type == "survived_no_evidence":
        title_color = Color(0.95, 0.85, 0.4)
    _ending_title_label.add_theme_color_override("font_color", title_color)


func _build_ui() -> void:
    _bg = ColorRect.new()
    _bg.color = Color(0.05, 0.05, 0.08, 0.97)
    _bg.anchor_right = 1.0
    _bg.anchor_bottom = 1.0
    add_child(_bg)

    var margin = MarginContainer.new()
    margin.anchor_right = 1.0
    margin.anchor_bottom = 1.0
    margin.add_theme_constant_override("margin_left", 80)
    margin.add_theme_constant_override("margin_right", 80)
    margin.add_theme_constant_override("margin_top", 200)
    margin.add_theme_constant_override("margin_bottom", 80)
    add_child(margin)

    var vbox = VBoxContainer.new()
    vbox.add_theme_constant_override("separation", 24)
    vbox.alignment = BoxContainer.ALIGNMENT_CENTER
    margin.add_child(vbox)

    _ending_title_label = Label.new()
    _ending_title_label.text = "..."
    _ending_title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    _ending_title_label.add_theme_font_size_override("font_size", 64)
    _ending_title_label.add_theme_color_override("font_color", Color(0.95, 0.85, 0.4))
    vbox.add_child(_ending_title_label)

    _ending_subtitle_label = Label.new()
    _ending_subtitle_label.text = ""
    _ending_subtitle_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    _ending_subtitle_label.add_theme_font_size_override("font_size", 26)
    _ending_subtitle_label.add_theme_color_override("font_color", Color(0.85, 0.85, 0.85))
    vbox.add_child(_ending_subtitle_label)

    _ending_stats_label = Label.new()
    _ending_stats_label.text = ""
    _ending_stats_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    _ending_stats_label.add_theme_font_size_override("font_size", 20)
    _ending_stats_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.7))
    vbox.add_child(_ending_stats_label)

    var spacer = Control.new()
    spacer.custom_minimum_size = Vector2(0, 60)
    vbox.add_child(spacer)

    # 三个按钮
    var btn_hbox = HBoxContainer.new()
    btn_hbox.alignment = BoxContainer.ALIGNMENT_CENTER
    btn_hbox.add_theme_constant_override("separation", 24)
    vbox.add_child(btn_hbox)

    _view_memories_button = Button.new()
    _view_memories_button.text = "  📋 查看同事们的回忆  "
    _view_memories_button.add_theme_font_size_override("font_size", 18)
    _view_memories_button.custom_minimum_size = Vector2(240, 56)
    _view_memories_button.pressed.connect(_on_view_memories)
    btn_hbox.add_child(_view_memories_button)

    _restart_button = Button.new()
    _restart_button.text = "  🔄 重新开始  "
    _restart_button.add_theme_font_size_override("font_size", 18)
    _restart_button.custom_minimum_size = Vector2(180, 56)
    _restart_button.pressed.connect(_on_restart)
    btn_hbox.add_child(_restart_button)

    _exit_button = Button.new()
    _exit_button.text = "  退出游戏  "
    _exit_button.add_theme_font_size_override("font_size", 18)
    _exit_button.custom_minimum_size = Vector2(180, 56)
    _exit_button.pressed.connect(_on_exit)
    btn_hbox.add_child(_exit_button)


func _on_view_memories() -> void:
    view_memories_pressed.emit()


func _on_restart() -> void:
    restart_pressed.emit()
    queue_free()


func _on_exit() -> void:
    exit_pressed.emit()
    get_tree().quit()
