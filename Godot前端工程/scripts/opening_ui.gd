extends Control

## 开场剧情界面 v2(VA-11 HALL-A 风格)
## 上图下文 + 打字机效果 + ESC 跳过 + 点击推进

signal finished

const TYPING_INTERVAL: float = 0.04
const SKIP_KEYCODE: int = KEY_ESCAPE
const CSV_PATH: String = "res://data/opening_scenes.csv"

var _scenes: Array = []
var _current_scene_index: int = 0
var _is_typing: bool = false
var _full_text_buffer: String = ""
var _is_finishing: bool = false

var _bg: ColorRect = null
var _image_node: TextureRect = null
var _text_label: RichTextLabel = null
var _continue_hint: Label = null
var _skip_button: Button = null
var _is_initialized: bool = false


func _ready() -> void:
    _ensure_initialized()


func _ensure_initialized() -> void:
    if _is_initialized:
        return
    anchor_right = 1.0
    anchor_bottom = 1.0
    mouse_filter = Control.MOUSE_FILTER_STOP
    _build_ui()
    _layout_ui()
    _load_scenes()
    _is_initialized = true


func setup(_opening_data: Dictionary = {}) -> void:
    # 新版从 CSV 加载,不需要外部数据,但保留兼容签名
    _ensure_initialized()
    set_process_input(true)
    _is_finishing = false
    _is_typing = false
    _current_scene_index = 0
    _full_text_buffer = ""
    if _continue_hint:
        _continue_hint.visible = false
    if _text_label:
        _text_label.text = ""
    if _scenes.is_empty():
        _load_scenes()
    if _scenes.is_empty():
        push_warning("[OpeningUI] 无法加载开场剧情数据,跳过开场")
        _finish_opening()
        return
    _play_scene(0)


func _notification(what: int) -> void:
    if what == NOTIFICATION_RESIZED:
        _layout_ui()


func _build_ui() -> void:
    _bg = ColorRect.new()
    _bg.color = Color(0.02, 0.02, 0.03, 1.0)
    _bg.anchor_right = 1.0
    _bg.anchor_bottom = 1.0
    add_child(_bg)

    _image_node = TextureRect.new()
    _image_node.expand_mode = TextureRect.EXPAND_FIT_WIDTH_PROPORTIONAL
    _image_node.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
    _image_node.custom_minimum_size = Vector2(1280, 540)
    add_child(_image_node)

    _text_label = RichTextLabel.new()
    _text_label.bbcode_enabled = false
    _text_label.fit_content = true
    _text_label.scroll_active = false
    _text_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _text_label.custom_minimum_size = Vector2(1280, 200)
    _text_label.add_theme_font_size_override("normal_font_size", 20)
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
    _skip_button.text = " 按 ESC 跳过开场 "
    _skip_button.add_theme_font_size_override("font_size", 14)
    _skip_button.modulate = Color(1.0, 1.0, 1.0, 0.6)
    _skip_button.pressed.connect(_on_skip)
    add_child(_skip_button)


func _layout_ui() -> void:
    if _image_node == null or _text_label == null or _continue_hint == null or _skip_button == null:
        return
    var viewport_size := get_viewport_rect().size
    var image_width: float = min(1280.0, float(viewport_size.x) - 80.0)
    image_width = max(image_width, 640.0)
    var image_height: float = image_width * 540.0 / 1280.0
    _image_node.size = Vector2(image_width, image_height)
    _image_node.position = Vector2((viewport_size.x - image_width) * 0.5, 60.0)

    # 文本对齐到“图片实际可见区域”而不是 TextureRect 外框，
    # 避免贴图按比例居中后出现文字看起来偏左的问题。
    var image_content_rect := _get_image_content_rect()
    var text_width: float = image_content_rect.size.x
    var text_height: float = 220.0
    _text_label.size = Vector2(text_width, text_height)
    _text_label.position = Vector2(image_content_rect.position.x, _image_node.position.y + image_height + 24.0)

    _continue_hint.size = Vector2(220.0, 30.0)
    _continue_hint.position = Vector2((viewport_size.x - _continue_hint.size.x) * 0.5, viewport_size.y - 64.0)

    _skip_button.size = Vector2(170.0, 36.0)
    _skip_button.position = Vector2(viewport_size.x - _skip_button.size.x - 20.0, viewport_size.y - _skip_button.size.y - 20.0)


func _get_image_content_rect() -> Rect2:
    var content_pos: Vector2 = _image_node.position
    var content_size: Vector2 = _image_node.size
    if _image_node.texture == null:
        return Rect2(content_pos, content_size)

    var tex_size_i: Vector2i = _image_node.texture.get_size()
    if tex_size_i.x <= 0 or tex_size_i.y <= 0:
        return Rect2(content_pos, content_size)
    var tex_size: Vector2 = Vector2(tex_size_i)

    var scale: float = min(_image_node.size.x / tex_size.x, _image_node.size.y / tex_size.y)
    var draw_size: Vector2 = tex_size * scale
    var draw_pos: Vector2 = _image_node.position + (_image_node.size - draw_size) * 0.5
    return Rect2(draw_pos, draw_size)


func _load_scenes() -> void:
    _scenes.clear()
    var file := FileAccess.open(CSV_PATH, FileAccess.READ)
    if file == null:
        push_warning("[OpeningUI] 无法打开 %s" % CSV_PATH)
        return

    var header_line := file.get_line()
    if header_line.is_empty():
        file.close()
        return

    while not file.eof_reached():
        var line := file.get_line()
        if line.strip_edges().is_empty():
            continue
        var fields := _parse_csv_line(line)
        if fields.size() < 3:
            continue
        var text := str(fields[2]).replace("\\n", "\n")
        _scenes.append({
            "image_path": str(fields[1]).strip_edges(),
            "text": text
        })

    file.close()
    print("[OpeningUI] 加载 %d 个场景" % _scenes.size())


func _parse_csv_line(line: String) -> Array:
    var result: Array = []
    var current := ""
    var in_quote := false
    var i := 0
    while i < line.length():
        var ch = line[i]
        if ch == '"':
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            result.append(current)
            current = ""
        else:
            current += ch
        i += 1
    result.append(current)

    for j in range(result.size()):
        var s := str(result[j]).strip_edges()
        if s.length() >= 2 and s.begins_with('"') and s.ends_with('"'):
            s = s.substr(1, s.length() - 2)
        result[j] = s
    return result


func _play_scene(index: int) -> void:
    if index >= _scenes.size():
        _finish_opening()
        return

    _current_scene_index = index
    var scene: Dictionary = _scenes[index]

    var img_path := str(scene.get("image_path", ""))
    var texture: Texture2D = load(img_path) if img_path != "" else null
    if texture:
        _image_node.texture = texture
    else:
        _image_node.texture = _make_placeholder_texture(index)

    var text := str(scene.get("text", ""))
    _full_text_buffer = text
    _text_label.text = ""
    _continue_hint.visible = false
    _is_typing = true
    _typewriter_animate(text)


func _make_placeholder_texture(index: int) -> ImageTexture:
    var img := Image.create(1280, 540, false, Image.FORMAT_RGB8)
    var colors = [
        Color(0.3, 0.1, 0.1),
        Color(0.1, 0.2, 0.3),
        Color(0.15, 0.15, 0.1),
        Color(0.2, 0.15, 0.25),
        Color(0.25, 0.05, 0.05),
        Color(0.05, 0.05, 0.15)
    ]
    var color: Color = colors[index % colors.size()] if colors.size() > 0 else Color(0.2, 0.2, 0.2)
    img.fill(color)
    return ImageTexture.create_from_image(img)


func _typewriter_animate(text: String) -> void:
    var char_index := 0
    while char_index < text.length():
        if not _is_typing:
            _text_label.text = text
            break
        await get_tree().create_timer(TYPING_INTERVAL).timeout
        char_index += 1
        _text_label.text = text.substr(0, char_index)
    _is_typing = false
    _continue_hint.visible = true


func _input(event: InputEvent) -> void:
    if not visible:
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
        _play_scene(_current_scene_index + 1)


func _on_skip() -> void:
    _finish_opening()


func _finish_opening() -> void:
    if _is_finishing:
        return
    _is_finishing = true
    _is_typing = false
    set_process_input(false)
    finished.emit()
