extends Control

## 登录界面
## 显示游戏标题 + 副标题 + 简介 + [开始游戏] 按钮。
## 点击按钮后发出 start_pressed 信号,由 game_ui.gd 接管后续流程。

signal start_pressed

func _ready() -> void:
    anchor_right = 1.0
    anchor_bottom = 1.0
    mouse_filter = Control.MOUSE_FILTER_STOP
    _build_ui()

func _build_ui() -> void:
    # 黑色背景
    var bg = ColorRect.new()
    bg.color = Color(0.05, 0.05, 0.08, 1.0)
    bg.anchor_right = 1.0
    bg.anchor_bottom = 1.0
    add_child(bg)

    # 居中容器
    var center = CenterContainer.new()
    center.anchor_right = 1.0
    center.anchor_bottom = 1.0
    add_child(center)

    var vbox = VBoxContainer.new()
    vbox.alignment = BoxContainer.ALIGNMENT_CENTER
    vbox.add_theme_constant_override("separation", 24)
    center.add_child(vbox)

    # 主标题
    var title = Label.new()
    title.text = "《末日调查员》"
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.add_theme_font_size_override("font_size", 56)
    title.add_theme_color_override("font_color", Color(0.95, 0.85, 0.4))
    vbox.add_child(title)

    # 副标题
    var subtitle = Label.new()
    subtitle.text = "Doomsday Investigator"
    subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    subtitle.add_theme_font_size_override("font_size", 24)
    subtitle.add_theme_color_override("font_color", Color(0.7, 0.7, 0.7))
    vbox.add_child(subtitle)

    # 间距
    var spacer1 = Control.new()
    spacer1.custom_minimum_size = Vector2(0, 20)
    vbox.add_child(spacer1)

    # 介绍三行
    var intro_lines = [
        "AI 驱动的 Multi-Agent 社交推理游戏",
        "6 个独立 AI Agent 各怀鬼胎",
        "你能在 5 天内活下来吗?",
    ]
    for line_text in intro_lines:
        var line = Label.new()
        line.text = "* " + line_text
        line.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        line.add_theme_font_size_override("font_size", 18)
        line.add_theme_color_override("font_color", Color(0.85, 0.85, 0.85))
        vbox.add_child(line)

    # 间距
    var spacer2 = Control.new()
    spacer2.custom_minimum_size = Vector2(0, 30)
    vbox.add_child(spacer2)

    # 开始按钮
    var btn = Button.new()
    btn.text = "  开 始 游 戏  "
    btn.add_theme_font_size_override("font_size", 28)
    btn.custom_minimum_size = Vector2(280, 70)
    btn.pressed.connect(_on_start_pressed)
    vbox.add_child(btn)

func _on_start_pressed() -> void:
    start_pressed.emit()
