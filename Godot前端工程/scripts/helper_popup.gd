extends CanvasLayer

## S-Helper 通用对话弹窗
## 暗色蒙版 + 头像 + 多句打字机 + 点击推进

signal closed

const TYPING_INTERVAL: float = 0.035  # 打字机字间隔
const HELPER_AVATAR_PATH: String = "res://assets/helper/helper_avatar.png"

# 状态
var _sentences: Array[String] = []
var _current_sentence_index: int = 0
var _is_typing: bool = false
var _is_closing: bool = false
var _full_text_buffer: String = ""

# UI
var _bg: ColorRect = null
var _bubble: Panel = null
var _avatar: TextureRect = null
var _text_label: RichTextLabel = null
var _continue_hint: Label = null


func _ready() -> void:
    layer = 100
    _build_ui()


func setup(sentences: Array) -> void:
    """传入要显示的句子列表(每句单独打字机+点击推进)。

    用法:
        var popup = HelperPopupScene.instantiate()
        get_tree().root.add_child(popup)
        popup.setup(["第一句话。", "第二句话。", "第三句话。"])
        popup.closed.connect(_on_helper_closed)
    """
    _sentences = []
    for s in sentences:
        var clean = str(s).strip_edges()
        if not clean.is_empty():
            _sentences.append(clean)

    if _sentences.is_empty():
        _close()
        return

    _current_sentence_index = 0
    _play_sentence(0)


func _build_ui() -> void:
    # 暗色半透明蒙版
    _bg = ColorRect.new()
    _bg.color = Color(0, 0, 0, 0.65)
    _bg.anchor_right = 1.0
    _bg.anchor_bottom = 1.0
    _bg.mouse_filter = Control.MOUSE_FILTER_STOP
    add_child(_bg)

    # 对话气泡(中央偏下)
    _bubble = Panel.new()
    _bubble.custom_minimum_size = Vector2(900, 240)
    _bubble.size = Vector2(900, 240)
    # 居中:屏幕大约 1908x960,气泡放在 (504, 600)
    _bubble.position = Vector2((1908 - 900) / 2, 600)
    var stylebox = StyleBoxFlat.new()
    stylebox.bg_color = Color(0.12, 0.14, 0.20, 0.96)
    stylebox.border_width_left = 3
    stylebox.border_width_right = 3
    stylebox.border_width_top = 3
    stylebox.border_width_bottom = 3
    stylebox.border_color = Color(0.4, 0.85, 0.95, 0.9)  # 蓝色科技边
    stylebox.corner_radius_top_left = 12
    stylebox.corner_radius_top_right = 12
    stylebox.corner_radius_bottom_left = 12
    stylebox.corner_radius_bottom_right = 12
    _bubble.add_theme_stylebox_override("panel", stylebox)
    _bg.add_child(_bubble)

    # 头像(左侧)
    _avatar = TextureRect.new()
    _avatar.position = Vector2(30, 30)
    _avatar.size = Vector2(180, 180)
    _avatar.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
    _avatar.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
    var helper_tex = load(HELPER_AVATAR_PATH) if HELPER_AVATAR_PATH else null
    if helper_tex != null:
        _avatar.texture = helper_tex
    else:
        # 占位:蓝色色块
        var img = Image.create(180, 180, false, Image.FORMAT_RGB8)
        img.fill(Color(0.3, 0.7, 0.85))
        _avatar.texture = ImageTexture.create_from_image(img)
    _bubble.add_child(_avatar)

    # 名字标签
    var name_label = Label.new()
    name_label.text = "小助理"
    name_label.position = Vector2(230, 24)
    name_label.add_theme_font_size_override("font_size", 18)
    name_label.add_theme_color_override("font_color", Color(0.4, 0.85, 0.95))
    _bubble.add_child(name_label)

    # 分隔线
    var sep_line = ColorRect.new()
    sep_line.position = Vector2(230, 50)
    sep_line.size = Vector2(640, 2)
    sep_line.color = Color(0.4, 0.85, 0.95, 0.4)
    _bubble.add_child(sep_line)

    # 文字区
    _text_label = RichTextLabel.new()
    _text_label.bbcode_enabled = true
    _text_label.fit_content = true
    _text_label.scroll_active = false
    _text_label.position = Vector2(230, 60)
    _text_label.size = Vector2(640, 140)
    _text_label.add_theme_font_size_override("normal_font_size", 19)
    _text_label.add_theme_color_override("default_color", Color(0.95, 0.95, 0.92))
    _bubble.add_child(_text_label)

    # 底部"▼ 点击继续"提示
    _continue_hint = Label.new()
    _continue_hint.text = "▼ 点击继续"
    _continue_hint.position = Vector2(720, 200)
    _continue_hint.size = Vector2(160, 30)
    _continue_hint.add_theme_font_size_override("font_size", 14)
    _continue_hint.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6, 0.8))
    _continue_hint.visible = false
    _bubble.add_child(_continue_hint)


func _play_sentence(index: int) -> void:
    if index >= _sentences.size():
        _close()
        return

    _current_sentence_index = index
    _full_text_buffer = _sentences[index]
    _text_label.text = ""
    _continue_hint.visible = false
    _is_typing = true
    _typewriter_animate(_full_text_buffer)


func _typewriter_animate(text: String) -> void:
    var char_index = 0
    while char_index < text.length():
        if not _is_typing:
            # 玩家点击跳过当前打字
            _text_label.text = text
            break
        await get_tree().create_timer(TYPING_INTERVAL).timeout
        char_index += 1
        _text_label.text = text.substr(0, char_index)
        if not is_instance_valid(self) or _is_closing:
            return

    _is_typing = false
    _continue_hint.visible = true


func _input(event: InputEvent) -> void:
    if _is_closing:
        return

    if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
        # 第一次点: 跳过当前打字
        if _is_typing:
            _is_typing = false
            return
        # 第二次点: 切下一句
        _play_sentence(_current_sentence_index + 1)
        get_viewport().set_input_as_handled()


func _close() -> void:
    if _is_closing:
        return
    _is_closing = true
    closed.emit()
    queue_free()
