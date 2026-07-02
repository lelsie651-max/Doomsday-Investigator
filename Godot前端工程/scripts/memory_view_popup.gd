extends CanvasLayer

## 记忆查看独立弹窗(模态)
## 显示所有 NPC 的分天记忆 Tab,关闭后回主结局页

signal closed

var _summary_data: Dictionary = {}
var _tab_order: Array = []
var _current_tab_npc_id: String = ""

# UI 节点
var _bg: ColorRect = null
var _panel: Panel = null
var _close_button: Button = null
var _tab_container: HBoxContainer = null
var _content_scroll: ScrollContainer = null
var _content_label: RichTextLabel = null


func _ready() -> void:
    layer = 110  # 比 HelperPopup 还高
    _build_ui()


func setup(data: Dictionary) -> void:
    _summary_data = data
    _tab_order = data.get("tab_order", [])
    _build_tabs()
    if not _tab_order.is_empty():
        _switch_to_npc(str(_tab_order[0]))


func _build_ui() -> void:
    # 暗色蒙版
    _bg = ColorRect.new()
    _bg.color = Color(0, 0, 0, 0.75)
    _bg.anchor_right = 1.0
    _bg.anchor_bottom = 1.0
    _bg.mouse_filter = Control.MOUSE_FILTER_STOP
    add_child(_bg)

    # 主面板
    _panel = Panel.new()
    _panel.custom_minimum_size = Vector2(1400, 800)
    _panel.size = Vector2(1400, 800)
    _panel.position = Vector2((1908 - 1400) / 2, (960 - 800) / 2)
    var stylebox = StyleBoxFlat.new()
    stylebox.bg_color = Color(0.08, 0.10, 0.14, 0.98)
    stylebox.border_width_left = 3
    stylebox.border_width_right = 3
    stylebox.border_width_top = 3
    stylebox.border_width_bottom = 3
    stylebox.border_color = Color(0.4, 0.85, 0.95, 0.9)
    stylebox.corner_radius_top_left = 12
    stylebox.corner_radius_top_right = 12
    stylebox.corner_radius_bottom_left = 12
    stylebox.corner_radius_bottom_right = 12
    _panel.add_theme_stylebox_override("panel", stylebox)
    _bg.add_child(_panel)

    # 标题
    var title_label = Label.new()
    title_label.text = "📋 同事们眼中的故事"
    title_label.position = Vector2(40, 24)
    title_label.add_theme_font_size_override("font_size", 24)
    title_label.add_theme_color_override("font_color", Color(0.4, 0.85, 0.95))
    _panel.add_child(title_label)

    # 关闭按钮(右上角)
    _close_button = Button.new()
    _close_button.text = "  ✕ 关闭  "
    _close_button.add_theme_font_size_override("font_size", 16)
    _close_button.size = Vector2(100, 40)
    _close_button.position = Vector2(1280, 24)
    _close_button.pressed.connect(_on_close)
    _panel.add_child(_close_button)

    # Tab 按钮容器
    _tab_container = HBoxContainer.new()
    _tab_container.alignment = BoxContainer.ALIGNMENT_CENTER
    _tab_container.add_theme_constant_override("separation", 8)
    _tab_container.position = Vector2(40, 80)
    _tab_container.size = Vector2(1320, 50)
    _panel.add_child(_tab_container)

    # 内容滚动区
    _content_scroll = ScrollContainer.new()
    _content_scroll.position = Vector2(40, 150)
    _content_scroll.size = Vector2(1320, 620)
    _panel.add_child(_content_scroll)

    _content_label = RichTextLabel.new()
    _content_label.bbcode_enabled = true
    _content_label.fit_content = true
    _content_label.scroll_active = false
    _content_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _content_label.custom_minimum_size = Vector2(1280, 0)
    _content_label.add_theme_font_size_override("normal_font_size", 17)
    _content_label.add_theme_color_override("default_color", Color(0.92, 0.92, 0.92))
    _content_scroll.add_child(_content_label)


func _build_tabs() -> void:
    for child in _tab_container.get_children():
        child.queue_free()

    var npc_memories = _summary_data.get("npc_memories", {})
    for npc_id in _tab_order:
        var npc_id_str = str(npc_id)
        var npc_data = npc_memories.get(npc_id_str, {})
        var npc_name = str(npc_data.get("name", npc_id_str))

        var btn = Button.new()
        btn.text = "  %s  " % npc_name
        btn.add_theme_font_size_override("font_size", 16)
        btn.custom_minimum_size = Vector2(110, 40)
        btn.pressed.connect(_switch_to_npc.bind(npc_id_str))
        _tab_container.add_child(btn)


func _switch_to_npc(npc_id: String) -> void:
    _current_tab_npc_id = npc_id
    _render_npc_memories(npc_id)

    var npc_memories = _summary_data.get("npc_memories", {})
    for child in _tab_container.get_children():
        if child is Button:
            var is_current = (child.text.strip_edges() == str(npc_memories.get(npc_id, {}).get("name", "")))
            child.modulate = Color(1.2, 1.2, 0.8) if is_current else Color(1, 1, 1)


func _render_npc_memories(npc_id: String) -> void:
    var npc_memories = _summary_data.get("npc_memories", {})
    var npc_data = npc_memories.get(npc_id, {})
    var npc_name = str(npc_data.get("name", npc_id))
    var identity = str(npc_data.get("identity", "")).strip_edges()
    var memories_by_day = npc_data.get("memories_by_day", {})

    var lines: Array = []
    lines.append("[b][color=#f0d870]%s 眼中的剧情[/color][/b]" % npc_name)
    lines.append("")

    if not identity.is_empty():
        lines.append("[i][color=#888888]%s[/color][/i]" % identity)
        lines.append("")

    if memories_by_day.is_empty():
        lines.append("[color=#666666](TA 没有产生任何记忆。)[/color]")
        _content_label.text = "\n".join(lines)
        return

    var day_keys: Array = []
    for k in memories_by_day.keys():
        day_keys.append(int(k))
    day_keys.sort()

    for day in day_keys:
        var day_targets = memories_by_day.get(day, memories_by_day.get(str(day), {}))
        if day_targets.is_empty():
            continue

        lines.append("")
        lines.append("[b]📅 第 %d 天[/b]" % day)

        for target_id in day_targets.keys():
            var target_data = day_targets[target_id]
            var target_name = str(target_data.get("target_name", target_id))
            var texts = target_data.get("texts", [])
            if texts.is_empty():
                continue

            lines.append("[color=#7ec8e3]· 对 %s[/color]" % target_name)
            for text in texts:
                lines.append("  「%s」" % str(text))

    _content_label.text = "\n".join(lines)


func _on_close() -> void:
    closed.emit()
    queue_free()
