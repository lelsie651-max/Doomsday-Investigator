extends Node

## 引导触发管理器(autoload 单例)
## 用法: TutorialManager.maybe_show("first_evidence_card")
## 内部: 检查 TutorialState.is_triggered, 未触发则加载 CSV 文本, 实例化 TutorialPopup 显示
##
## ⚠️ 设计原则:
## - 不要加"如果 TutorialState 异常就 fallback 到本地 flags"的兜底
##   ——autoload 是 Godot 启动时就注册好的,不会运行时丢失
##   兜底机制反而会掩盖真正的 bug

const CSV_PATH: String = "res://data/tutorial_texts.csv"
const POPUP_SCRIPT_PATH: String = "res://scripts/helper_popup.gd"

# 引导文本缓存: { key: { "title": "...", "body": "...", "priority": "modal" } }
var _texts: Dictionary = {}
# 当前正在显示的弹窗(单例,同时只显示一个)
var _current_popup: Node = null
var _pending_keys: Array[String] = []  # 排队等待弹出的引导 key


func _ready() -> void:
    _load_texts()


func maybe_show(key: String) -> bool:
    """
    检查某个引导是否需要触发。
    - 未触发过且 CSV 有文本 -> 立即弹出 OR 加入队列等待
    - 返回是否成功立即弹出(加入队列也返回 true)
    """
    if key.is_empty():
        return false

    if TutorialState.is_triggered(key):
        return false

    if not _texts.has(key):
        push_warning("[TutorialManager] CSV 中找不到 key: %s" % key)
        return false

    var entry: Dictionary = _texts[key]
    var title := str(entry.get("title", "")).strip_edges()
    var body := str(entry.get("body", "")).strip_edges()
    if title.is_empty() and body.is_empty():
        push_warning("[TutorialManager] key=%s 文本为空" % key)
        return false

    # 已经有弹窗在显示 -> 加入队列(不是丢弃),不立即标记 triggered
    if _current_popup and is_instance_valid(_current_popup):
        if not _pending_keys.has(key):
            _pending_keys.append(key)
            print("[TutorialManager] key=%s 排队等待(当前队列长度=%d)" % [key, _pending_keys.size()])
        return false

    # 立即弹出
    _show_popup(title, body)
    TutorialState.mark_triggered(key)
    print("[TutorialManager] 已弹出 key=%s" % key)
    return true


func get_sentences(key: String, params: Dictionary = {}, include_title: bool = true) -> Array:
    """
    读取指定 key 的文案并拆成句子数组（按 | 分隔）。
    - include_title=true 时，title 会作为第一句
    - params 用于替换占位符，如 {target_name} / {room_name}
    """
    if key.is_empty() or not _texts.has(key):
        return []
    var entry: Dictionary = _texts[key]
    var sentences: Array = []
    if include_title:
        var title_text := _format_text(str(entry.get("title", "")).strip_edges(), params)
        if not title_text.is_empty():
            sentences.append(title_text)
    var body_text := _format_text(str(entry.get("body", "")).strip_edges(), params)
    for s in body_text.split("|"):
        var clean := str(s).strip_edges()
        if not clean.is_empty():
            sentences.append(clean)
    if sentences.size() >= 2 and str(sentences[0]) == str(sentences[1]):
        sentences.remove_at(1)
    return sentences


func _load_texts() -> void:
    """加载 CSV 到 _texts 字典。"""
    _texts.clear()
    var file = FileAccess.open(CSV_PATH, FileAccess.READ)
    if file == null:
        push_warning("[TutorialManager] 无法打开 %s" % CSV_PATH)
        return

    var header_line = file.get_line()
    if header_line.is_empty():
        return
    var headers = _parse_csv_line(header_line)

    while not file.eof_reached():
        var line = file.get_line()
        if line.strip_edges().is_empty():
            continue
        var fields = _parse_csv_line(line)
        if fields.size() < headers.size():
            continue
        var entry := {}
        for i in range(headers.size()):
            entry[headers[i]] = fields[i]
        var key = str(entry.get("key", "")).strip_edges()
        if not key.is_empty():
            _texts[key] = entry

    file.close()
    print("[TutorialManager] 加载 %d 条引导文本" % _texts.size())


func _parse_csv_line(line: String) -> Array:
    """简易 CSV 解析(支持双引号包裹 + 引号内逗号)。"""
    var result: Array = []
    var current: String = ""
    var in_quote: bool = false
    var i: int = 0
    while i < line.length():
        var ch = line[i]
        if ch == '"':
            in_quote = not in_quote
        elif ch == ',' and not in_quote:
            result.append(current)
            current = ""
        else:
            current += ch
        i += 1
    result.append(current)
    # 去引号 + trim
    for j in range(result.size()):
        var s = str(result[j]).strip_edges()
        if s.length() >= 2 and s.begins_with('"') and s.ends_with('"'):
            s = s.substr(1, s.length() - 2)
        result[j] = s
    return result


func _show_popup(title: String, body: String) -> void:
    """实例化 HelperPopup 并加到当前场景树上。"""
    var script = load(POPUP_SCRIPT_PATH)
    if script == null:
        push_warning("[TutorialManager] 无法加载 %s" % POPUP_SCRIPT_PATH)
        return
    var sentences: Array = []
    var clean_title := str(title).strip_edges()
    if not clean_title.is_empty():
        sentences.append(clean_title)
    for s in str(body).split("|"):
        var clean = str(s).strip_edges()
        if not clean.is_empty():
            sentences.append(clean)
    if sentences.is_empty():
        return
    var popup = script.new()
    var tree = get_tree()
    if tree == null or tree.root == null:
        return
    tree.root.add_child(popup)
    popup.closed.connect(_on_popup_dismissed)
    popup.setup(sentences)
    _current_popup = popup


func _format_text(text: String, params: Dictionary) -> String:
    var result := text
    for key in params.keys():
        var token := "{%s}" % str(key)
        result = result.replace(token, str(params[key]))
    return result


func _on_popup_dismissed() -> void:
    _current_popup = null
    # 关闭后,从队列取下一个继续弹
    _process_pending_queue()


func reset_all_for_debug() -> void:
    """F8 调试: 重置所有 flags + 关闭当前弹窗。"""
    TutorialState.reset_all()
    if _current_popup and is_instance_valid(_current_popup):
        _current_popup.queue_free()
        _current_popup = null
    print("[TutorialManager] 全部 flags 已重置 (F8)")


func _process_pending_queue() -> void:
    """关闭当前弹窗后,从队列取下一个继续弹。"""
    if _pending_keys.is_empty():
        return
    if _current_popup and is_instance_valid(_current_popup):
        return

    var next_key = str(_pending_keys.pop_front())
    if TutorialState.is_triggered(next_key):
        _process_pending_queue()
        return

    if not _texts.has(next_key):
        _process_pending_queue()
        return

    var entry: Dictionary = _texts[next_key]
    var title := str(entry.get("title", "")).strip_edges()
    var body := str(entry.get("body", "")).strip_edges()
    if title.is_empty() and body.is_empty():
        _process_pending_queue()
        return

    _show_popup(title, body)
    TutorialState.mark_triggered(next_key)
    print("[TutorialManager] 队列弹出 key=%s (剩余=%d)" % [next_key, _pending_keys.size()])


func clear_pending_queue() -> void:
    """清空排队中的引导(重开局时调用)。"""
    _pending_keys.clear()
    print("[TutorialManager] pending queue cleared")
