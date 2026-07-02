extends Control

## 结局过场剧情界面(仿开场剧情格式,自适应布局)
## 上图下文 + 打字机效果 + ESC 跳过 + 点击推进

signal finished

const TYPING_INTERVAL: float = 0.04
const SKIP_KEYCODE: int = KEY_ESCAPE

# 状态
var _sentences: Array = []
var _image_path: String = ""
var _current_sentence_index: int = 0
var _is_typing: bool = false
var _is_finished: bool = false

# UI 节点
var _bg: ColorRect = null
var _image_node: TextureRect = null
var _text_label: RichTextLabel = null
var _continue_hint: Label = null
var _skip_button: Button = null


func _ready() -> void:
    anchor_right = 1.0
    anchor_bottom = 1.0
    mouse_filter = Control.MOUSE_FILTER_STOP
    _build_ui()
    _layout_ui()


func _notification(what: int) -> void:
    if what == NOTIFICATION_RESIZED:
        _layout_ui()


func setup(image_path: String, sentences: Array) -> void:
    """传入图片路径 + 句子列表。"""
    _image_path = str(image_path).strip_edges()
    _sentences.clear()
    for s in sentences:
        var clean = str(s).strip_edges()
        if not clean.is_empty():
            _sentences.append(clean)

    # 加载图片
    var texture = null
    if not _image_path.is_empty():
        texture = load(_image_path)
    if texture:
        _image_node.texture = texture
    else:
        # 占位:暗红色色块
        var img = Image.create(1280, 540, false, Image.FORMAT_RGB8)
        img.fill(Color(0.2, 0.05, 0.05))
        _image_node.texture = ImageTexture.create_from_image(img)

    if _sentences.is_empty():
        _on_finish()
        return

    _play_sentence(0)


func _build_ui() -> void:
    _bg = ColorRect.new()
    _bg.color = Color(0.02, 0.02, 0.03, 1.0)
    _bg.anchor_right = 1.0
    _bg.anchor_bottom = 1.0
    add_child(_bg)

    _image_node = TextureRect.new()
    _image_node.expand_mode = TextureRect.EXPAND_FIT_WIDTH_PROPORTIONAL
    _image_node.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
    add_child(_image_node)

    _text_label = RichTextLabel.new()
    _text_label.bbcode_enabled = true
    _text_label.fit_content = true
    _text_label.scroll_active = false
    _text_label.add_theme_font_size_override("normal_font_size", 22)
    _text_label.add_theme_color_override("default_color", Color(0.95, 0.95, 0.92))
    add_child(_text_label)

    _continue_hint = Label.new()
    _continue_hint.text = "▼ 点击继续"
    _continue_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    _continue_hint.add_theme_font_size_override("font_size", 16)
    _continue_hint.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6, 0.8))
    _continue_hint.visible = false
    add_child(_continue_hint)

    _skip_button = Button.new()
    _skip_button.text = " 按 ESC 跳过 "
    _skip_button.add_theme_font_size_override("font_size", 14)
    _skip_button.modulate = Color(1.0, 1.0, 1.0, 0.6)
    _skip_button.pressed.connect(_on_skip)
    add_child(_skip_button)


func _layout_ui() -> void:
    """自适应布局(抄 opening_ui.gd 的写法)。"""
    if _image_node == null or _text_label == null or _continue_hint == null or _skip_button == null:
        return
    var viewport_size := get_viewport_rect().size

    # 图片区
    var image_width: float = min(1280.0, float(viewport_size.x) - 80.0)
    image_width = max(image_width, 640.0)
    var image_height: float = image_width * 540.0 / 1280.0
    _image_node.size = Vector2(image_width, image_height)
    _image_node.position = Vector2((viewport_size.x - image_width) * 0.5, 60.0)

    # 文字区
    var text_width: float = image_width
    var text_height: float = 220.0
    _text_label.size = Vector2(text_width, text_height)
    _text_label.position = Vector2((viewport_size.x - text_width) * 0.5, _image_node.position.y + image_height + 24.0)

    # 提示
    _continue_hint.size = Vector2(220.0, 30.0)
    _continue_hint.position = Vector2((viewport_size.x - _continue_hint.size.x) * 0.5, viewport_size.y - 64.0)

    # 跳过按钮
    _skip_button.size = Vector2(170.0, 36.0)
    _skip_button.position = Vector2(viewport_size.x - _skip_button.size.x - 20.0, viewport_size.y - _skip_button.size.y - 20.0)


func _play_sentence(index: int) -> void:
    if index >= _sentences.size():
        _on_finish()
        return

    _current_sentence_index = index
    var text = _sentences[index]
    _text_label.text = ""
    _continue_hint.visible = false
    _is_typing = true
    _typewriter_animate(text)


func _typewriter_animate(text: String) -> void:
    var char_index = 0
    while char_index < text.length():
        if not _is_typing or _is_finished:
            _text_label.text = text
            break
        await get_tree().create_timer(TYPING_INTERVAL).timeout
        char_index += 1
        if not is_instance_valid(self):
            return
        _text_label.text = text.substr(0, char_index)

    _is_typing = false
    if not _is_finished:
        _continue_hint.visible = true


func _input(event: InputEvent) -> void:
    if _is_finished:
        return

    if event is InputEventKey and event.pressed and not event.echo:
        if event.keycode == SKIP_KEYCODE:
            _on_skip()
            get_viewport().set_input_as_handled()
            return

    if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
        if _is_typing:
            _is_typing = false
            return
        _play_sentence(_current_sentence_index + 1)


func _on_finish() -> void:
    if _is_finished:
        return
    _is_finished = true
    finished.emit()
    queue_free()


func _on_skip() -> void:
    _on_finish()
