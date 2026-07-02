extends Control

## 新手引导弹窗(模态)
## 显示: 小助理头像(占位) + 标题 + body 文本 + 关闭按钮
## 玩家可以: 点 [×] / 按空格 / 按ESC / 点底部按钮 关闭
## 关闭后发出 dismissed 信号

signal dismissed

var _title_text: String = ""
var _body_text: String = ""

# UI 节点引用
var _bg_dim: ColorRect = null
var _panel: PanelContainer = null
var _title_label: Label = null
var _body_label: Label = null
var _close_button: Button = null
var _ok_button: Button = null


func _ready() -> void:
	anchor_right = 1.0
	anchor_bottom = 1.0
	mouse_filter = Control.MOUSE_FILTER_STOP
	_build_ui()


func setup(title: String, body: String) -> void:
	"""由 TutorialManager 调用,传入要显示的引导文本。"""
	_title_text = title
	_body_text = body
	if _title_label:
		_title_label.text = title
	if _body_label:
		_body_label.text = body


func _build_ui() -> void:
	# 半透明背景遮罩
	_bg_dim = ColorRect.new()
	_bg_dim.color = Color(0, 0, 0, 0.65)
	_bg_dim.anchor_right = 1.0
	_bg_dim.anchor_bottom = 1.0
	_bg_dim.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(_bg_dim)

	# 居中容器
	var center = CenterContainer.new()
	center.anchor_right = 1.0
	center.anchor_bottom = 1.0
	add_child(center)

	# 主面板
	_panel = PanelContainer.new()
	_panel.custom_minimum_size = Vector2(560, 300)
	var stylebox = StyleBoxFlat.new()
	stylebox.bg_color = Color(0.10, 0.11, 0.16, 0.98)
	stylebox.border_width_left = 2
	stylebox.border_width_right = 2
	stylebox.border_width_top = 2
	stylebox.border_width_bottom = 2
	stylebox.border_color = Color(0.4, 0.85, 0.95, 1.0)  # 青色边框
	stylebox.corner_radius_top_left = 12
	stylebox.corner_radius_top_right = 12
	stylebox.corner_radius_bottom_left = 12
	stylebox.corner_radius_bottom_right = 12
	stylebox.content_margin_left = 24
	stylebox.content_margin_right = 24
	stylebox.content_margin_top = 20
	stylebox.content_margin_bottom = 20
	_panel.add_theme_stylebox_override("panel", stylebox)
	center.add_child(_panel)

	# 主 VBox
	var vbox = VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 14)
	_panel.add_child(vbox)

	# 顶部 HBox: 头像 + 名字 + 关闭按钮
	var top_hbox = HBoxContainer.new()
	top_hbox.add_theme_constant_override("separation", 14)
	vbox.add_child(top_hbox)

	# 头像占位(80x80 圆形紫底白字 S)
	var avatar = _build_avatar_placeholder()
	top_hbox.add_child(avatar)

	# 名字 + 副标题(竖排)
	var name_vbox = VBoxContainer.new()
	name_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	top_hbox.add_child(name_vbox)

	var name_label = Label.new()
	name_label.text = "S-Helper"
	name_label.add_theme_font_size_override("font_size", 20)
	name_label.add_theme_color_override("font_color", Color(0.95, 0.95, 0.95))
	name_vbox.add_child(name_label)

	var subtitle_label = Label.new()
	subtitle_label.text = "调查局 · 远程支援 AI"
	subtitle_label.add_theme_font_size_override("font_size", 13)
	subtitle_label.add_theme_color_override("font_color", Color(0.5, 0.85, 0.95))
	name_vbox.add_child(subtitle_label)

	# 关闭按钮 [×]
	_close_button = Button.new()
	_close_button.text = " × "
	_close_button.add_theme_font_size_override("font_size", 22)
	_close_button.custom_minimum_size = Vector2(40, 40)
	_close_button.pressed.connect(_on_dismiss)
	top_hbox.add_child(_close_button)

	# 分隔线
	var sep = HSeparator.new()
	vbox.add_child(sep)

	# 标题
	_title_label = Label.new()
	_title_label.text = _title_text
	_title_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_title_label.add_theme_font_size_override("font_size", 22)
	_title_label.add_theme_color_override("font_color", Color(0.95, 0.85, 0.4))
	vbox.add_child(_title_label)

	# 正文
	_body_label = Label.new()
	_body_label.text = _body_text
	_body_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_body_label.add_theme_font_size_override("font_size", 16)
	_body_label.add_theme_color_override("font_color", Color(0.92, 0.92, 0.92))
	_body_label.add_theme_constant_override("line_spacing", 6)
	vbox.add_child(_body_label)

	# 底部 [我懂了] 按钮
	var ok_hbox = HBoxContainer.new()
	ok_hbox.alignment = BoxContainer.ALIGNMENT_END
	vbox.add_child(ok_hbox)

	_ok_button = Button.new()
	_ok_button.text = "  我懂了 (空格)  "
	_ok_button.add_theme_font_size_override("font_size", 16)
	_ok_button.custom_minimum_size = Vector2(160, 44)
	_ok_button.pressed.connect(_on_dismiss)
	ok_hbox.add_child(_ok_button)


func _build_avatar_placeholder() -> Control:
	"""构建占位头像: 80x80 紫底圆形 + 白色 'S' 字"""
	var avatar_root = Control.new()
	avatar_root.custom_minimum_size = Vector2(80, 80)

	# 圆形紫底
	var circle = Panel.new()
	circle.custom_minimum_size = Vector2(80, 80)
	circle.size = Vector2(80, 80)
	var sb = StyleBoxFlat.new()
	sb.bg_color = Color(0.3, 0.15, 0.55, 1.0)  # 深紫
	sb.corner_radius_top_left = 40
	sb.corner_radius_top_right = 40
	sb.corner_radius_bottom_left = 40
	sb.corner_radius_bottom_right = 40
	sb.border_width_left = 2
	sb.border_width_right = 2
	sb.border_width_top = 2
	sb.border_width_bottom = 2
	sb.border_color = Color(0.6, 0.4, 0.85, 1.0)
	circle.add_theme_stylebox_override("panel", sb)
	avatar_root.add_child(circle)

	# 中心字母 'S'
	var s_label = Label.new()
	s_label.text = "S"
	s_label.size = Vector2(80, 80)
	s_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	s_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	s_label.add_theme_font_size_override("font_size", 38)
	s_label.add_theme_color_override("font_color", Color(1.0, 1.0, 1.0))
	avatar_root.add_child(s_label)

	return avatar_root


func _input(event: InputEvent) -> void:
	if not visible:
		return
	# 空格 / 回车 / ESC 关闭
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_SPACE or event.keycode == KEY_ENTER or event.keycode == KEY_ESCAPE:
			_on_dismiss()
			get_viewport().set_input_as_handled()


func _on_dismiss() -> void:
	visible = false
	dismissed.emit()
	queue_free()
