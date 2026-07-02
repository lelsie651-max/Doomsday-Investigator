extends Control
## 工作阶段底层面板
##
## 显示房间信息、同事列表、小时进度、通知消息。
## EventPopup叠在此面板上方。

signal movement_finished

@onready var hour_label: Label = $Margin/VBox/HourBar/HourLabel
@onready var hour_progress: ProgressBar = $Margin/VBox/HourBar/HourProgress
@onready var room_overview_panel: PanelContainer = $Margin/VBox/MainContent/RoomOverviewPanel
@onready var room_label: Label = $Margin/VBox/MainContent/EventContentPanel/RoomSection/RoomLabel
@onready var coworker_list: VBoxContainer = $Margin/VBox/MainContent/EventContentPanel/RoomSection/CoworkerList
@onready var boss_indicator: Label = $Margin/VBox/MainContent/EventContentPanel/RoomSection/BossIndicator
@onready var notification_label: RichTextLabel = $Margin/VBox/MainContent/EventContentPanel/NotificationArea
@onready var status_bar: HBoxContainer = $Margin/VBox/MainContent/EventContentPanel/StatusBar
@onready var gold_label: Label = $Margin/VBox/MainContent/EventContentPanel/StatusBar/GoldLabel
@onready var battery_label: Label = $Margin/VBox/MainContent/EventContentPanel/StatusBar/BatteryLabel
@onready var evidence_label: Label = $Margin/VBox/MainContent/EventContentPanel/StatusBar/EvidenceLabel
@onready var cards_label: Label = $Margin/VBox/MainContent/EventContentPanel/StatusBar/CardsLabel

var _notification_timer: float = 0.0
var _total_hours: int = 8
var _current_positions: Dictionary = {}
var _is_moving: bool = false
var _movement_timer: float = 0.0
var _movement_duration: float = 0.0
var _current_task_index: int = 0
var _total_tasks: int = 5
var _movement_progress_bar: ProgressBar = null
var _current_player_room_key: String = "office"
var _room_detail_cache: Dictionary = {}
var _pua_incoming_overlay: ColorRect = null
var _pua_incoming_label: RichTextLabel = null
var _pua_incoming_confirm_btn: Button = null
var _pending_movement_payload: Dictionary = {}

const ROOM_NAMES := {
    "office": "🏢 主办公区",
    "meeting": "📋 会议室",
    "warehouse": "📦 仓库",
    "pantry": "☕ 茶水间",
    "reception": "🚪 接待区",
    "boss_office": "👔 经理办公室",
}

const NPC_DISPLAY_NAMES := {
    "player": "👤 你",
    "laowang": "老王",
    "xiaoli": "小李",
    "ahua": "阿花",
    "dazhuang": "大壮",
    "zhoujie": "周姐",
    "boss": "🐙 鲍斯",
}

func _ready() -> void:
    visible = false
    notification_label.text = ""
    notification_label.bbcode_enabled = true
    NetworkManager.card_result_received.connect(_on_card_result_refresh)
    NetworkManager.movement_data_received.connect(_on_movement_data)
    NetworkManager.event_ready_received.connect(_on_event_ready)
    _ensure_movement_progress_bar()
    _setup_pua_incoming_overlay()


func _process(delta: float) -> void:
    # 通知自动消失
    if _notification_timer > 0:
        _notification_timer -= delta
        if _notification_timer <= 0:
            notification_label.text = ""
    if _is_moving:
        _movement_timer += delta
        _update_movement_progress()
        if _movement_timer >= _movement_duration:
            _finish_movement()


func setup(data: Dictionary, total_hours: int) -> void:
    """工作阶段开始时调用"""
    visible = true
    _total_hours = total_hours
    _total_tasks = total_hours
    _current_positions = data.get("positions", {})
    update_from_data(data, 0)
    if data.has("positions") and data.has("player_room"):
        update_room_overview(data["positions"], str(data["player_room"]))


func start_task_movement(task_index: int, total_tasks: int = -1) -> void:
    """开始移动到下一个任务房间"""
    _current_task_index = task_index
    if total_tasks > 0:
        _total_tasks = total_tasks
    update_hour_progress(_current_task_index, _total_hours)
    _show_moving_state()
    NetworkManager.start_movement(task_index)


func _on_movement_data(data: Dictionary) -> void:
    """收到后端移动数据，开始播放移动动画"""
    if bool(data.get("is_player_pua_incoming", false)):
        _pending_movement_payload = data.duplicate(true)
        _show_pua_incoming_overlay(str(data.get("player_pua_incoming_text", "糟糕！经理喊你去他办公室一趟。")))
        return
    _start_movement_with_payload(data)


func _start_movement_with_payload(data: Dictionary) -> void:
    """正式开始移动动画（用于常规进入或紧迫提示确认后进入）"""
    _movement_duration = float(data.get("max_duration", 2.0))
    _movement_timer = 0.0
    _is_moving = true
    _ensure_movement_progress_bar()
    if _movement_progress_bar:
        _movement_progress_bar.visible = true
        _movement_progress_bar.value = 0

    var task_name = str(data.get("task_name", ""))
    var target_room_key = str(data.get("target_room_key", "")).strip_edges()
    if target_room_key == "":
        var fallback_room = str(data.get("target_room", "office")).strip_edges()
        if ROOM_NAMES.has(fallback_room):
            target_room_key = fallback_room
        elif fallback_room == "经理办公室":
            target_room_key = "boss_office"
        else:
            target_room_key = "office"
    _current_player_room_key = target_room_key

    if bool(data.get("is_player_pua_incoming", false)):
        _show_pua_transit_text()
    else:
        _show_transit_text(target_room_key, task_name)
    _animate_room_overview(data.get("movements", []))

    if data.has("positions"):
        update_room_overview(data["positions"], target_room_key)


func _show_pua_transit_text() -> void:
    var text := "你被经理拖向办公室..."
    text += "\n\n空气里全是消毒水和铁锈味，你的脚步越来越沉。"
    text += "\n\n第 %d / %d 个任务" % [_current_task_index + 1, _total_tasks]
    show_notification(text, 999.0, "orange")


func _setup_pua_incoming_overlay() -> void:
    if _pua_incoming_overlay != null:
        return
    var overlay := ColorRect.new()
    overlay.name = "PuaIncomingOverlay"
    overlay.anchor_left = 0.0
    overlay.anchor_top = 0.0
    overlay.anchor_right = 1.0
    overlay.anchor_bottom = 1.0
    overlay.offset_left = 0.0
    overlay.offset_top = 0.0
    overlay.offset_right = 0.0
    overlay.offset_bottom = 0.0
    overlay.color = Color(0.0, 0.0, 0.0, 0.92)
    overlay.visible = false
    overlay.mouse_filter = Control.MOUSE_FILTER_STOP
    overlay.z_index = 100
    add_child(overlay)

    var center := CenterContainer.new()
    center.anchor_left = 0.0
    center.anchor_top = 0.0
    center.anchor_right = 1.0
    center.anchor_bottom = 1.0
    center.offset_left = 0.0
    center.offset_top = 0.0
    center.offset_right = 0.0
    center.offset_bottom = 0.0
    overlay.add_child(center)

    var panel := PanelContainer.new()
    panel.custom_minimum_size = Vector2(700, 280)
    center.add_child(panel)
    var panel_style := StyleBoxFlat.new()
    panel_style.bg_color = Color(0.0, 0.0, 0.0, 0.98)
    panel_style.border_width_left = 2
    panel_style.border_width_top = 2
    panel_style.border_width_right = 2
    panel_style.border_width_bottom = 2
    panel_style.border_color = Color(0.86, 0.12, 0.22, 1.0)
    panel_style.corner_radius_top_left = 12
    panel_style.corner_radius_top_right = 12
    panel_style.corner_radius_bottom_left = 12
    panel_style.corner_radius_bottom_right = 12
    panel.add_theme_stylebox_override("panel", panel_style)

    var vbox := VBoxContainer.new()
    vbox.add_theme_constant_override("separation", 20)
    vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
    panel.add_child(vbox)

    var margin := MarginContainer.new()
    margin.add_theme_constant_override("margin_left", 28)
    margin.add_theme_constant_override("margin_top", 24)
    margin.add_theme_constant_override("margin_right", 28)
    margin.add_theme_constant_override("margin_bottom", 24)
    margin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    margin.size_flags_vertical = Control.SIZE_EXPAND_FILL
    vbox.add_child(margin)

    var inner := VBoxContainer.new()
    inner.add_theme_constant_override("separation", 16)
    inner.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    inner.size_flags_vertical = Control.SIZE_EXPAND_FILL
    margin.add_child(inner)

    var title := Label.new()
    title.text = "⚠ 经理召见"
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.add_theme_color_override("font_color", Color(0.86, 0.12, 0.22))
    inner.add_child(title)

    var body := RichTextLabel.new()
    body.bbcode_enabled = true
    body.fit_content = true
    body.scroll_active = false
    body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    body.add_theme_color_override("default_color", Color(0.86, 0.12, 0.22))
    body.text = "糟糕！经理喊你去他办公室一趟。"
    inner.add_child(body)

    var confirm := Button.new()
    confirm.text = "硬着头皮过去"
    confirm.custom_minimum_size = Vector2(240, 44)
    confirm.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    confirm.pressed.connect(_on_pua_incoming_confirm)
    inner.add_child(confirm)

    _pua_incoming_overlay = overlay
    _pua_incoming_label = body
    _pua_incoming_confirm_btn = confirm


func _show_pua_incoming_overlay(text: String) -> void:
    if _pua_incoming_overlay == null:
        _setup_pua_incoming_overlay()
    if _pua_incoming_label:
        var final_text := text.strip_edges()
        if final_text == "":
            final_text = "糟糕！经理喊你去他办公室一趟。"
        _pua_incoming_label.text = "[center][b]%s[/b][/center]" % final_text
    if _pua_incoming_confirm_btn:
        _pua_incoming_confirm_btn.disabled = false
    _pua_incoming_overlay.visible = true


func _on_pua_incoming_confirm() -> void:
    if _pua_incoming_confirm_btn:
        _pua_incoming_confirm_btn.disabled = true
    if _pua_incoming_overlay:
        _pua_incoming_overlay.visible = false
    var payload := _pending_movement_payload
    _pending_movement_payload = {}
    if payload.is_empty():
        return
    _start_movement_with_payload(payload)


func _on_event_ready(_data: Dictionary) -> void:
    """Act 1准备好后，确保移动UI已收束"""
    _is_moving = false
    if _movement_progress_bar:
        _movement_progress_bar.visible = false


func _show_moving_state() -> void:
    show_notification("正在前往目标房间...", 999.0, "yellow")
    _ensure_movement_progress_bar()
    if _movement_progress_bar:
        _movement_progress_bar.visible = true
        _movement_progress_bar.value = 0


func _show_transit_text(target_room: String, task_name: String) -> void:
    var room_names := {
        "office": "主办公区",
        "meeting": "会议室",
        "warehouse": "仓库",
        "pantry": "茶水间",
        "reception": "接待区",
        "boss_office": "经理办公室",
    }
    var room_cn = room_names.get(target_room, target_room)

    var transit_texts := [
        "你拖着疲惫的身体穿过走廊，前往%s……",
        "走廊的灯一闪一闪的，你加快脚步赶往%s……",
        "你在走廊里和一只变异老鼠擦肩而过，继续走向%s……",
        "天花板上的水管漏着不明液体，你低头快步走向%s……",
    ]
    var text = transit_texts[randi() % transit_texts.size()] % room_cn
    text += "\n\n📋 即将执行：%s" % task_name
    text += "\n\n第 %d / %d 个任务" % [_current_task_index + 1, _total_tasks]
    show_notification(text, 999.0, "yellow")


func _update_movement_progress() -> void:
    if not _movement_progress_bar:
        return
    var progress: float = _movement_timer / max(_movement_duration, 0.001)
    progress = clampf(progress, 0.0, 1.0)
    _movement_progress_bar.value = progress * 100.0


func _animate_room_overview(_movements: Array) -> void:
    # MVP简化：直接由 positions 刷新房间概览，不做逐帧动画
    pass


func _finish_movement() -> void:
    _is_moving = false
    _movement_timer = 0.0
    if _movement_progress_bar:
        _movement_progress_bar.visible = false
    show_notification("到达目标房间，正在观察周围的情况……", 1.5, "yellow")
    movement_finished.emit()


func _ensure_movement_progress_bar() -> void:
    if _movement_progress_bar:
        return
    var event_panel = get_node_or_null("Margin/VBox/MainContent/EventContentPanel")
    if event_panel == null:
        return
    var existing = event_panel.get_node_or_null("MovementProgressBar")
    if existing and existing is ProgressBar:
        _movement_progress_bar = existing
        return
    var bar := ProgressBar.new()
    bar.name = "MovementProgressBar"
    bar.min_value = 0
    bar.max_value = 100
    bar.value = 0
    bar.visible = false
    bar.custom_minimum_size = Vector2(0, 8)
    event_panel.add_child(bar)


func update_from_data(data: Dictionary, hour: int) -> void:
    """每小时更新"""
    _current_positions = data.get("positions", _current_positions)

    # 小时进度
    update_hour_progress(hour, _total_hours)

    # 房间
    var room_key: String = data.get("player_room", "office")
    _current_player_room_key = room_key
    var room_name: String = ROOM_NAMES.get(room_key, room_key)
    room_label.text = room_name

    # 同事列表
    for child in coworker_list.get_children():
        child.queue_free()

    var coworkers = data.get("coworkers", {})
    var npc_names = coworkers.get("npc_names", [])
    var boss_here: bool = coworkers.get("boss_present", false)

    if npc_names.size() == 0 and not boss_here:
        var alone_label := Label.new()
        alone_label.text = "  这里只有你一个人..."
        alone_label.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
        coworker_list.add_child(alone_label)
    else:
        for npc_name in npc_names:
            var npc_label := Label.new()
            npc_label.text = "  👤 %s" % npc_name
            coworker_list.add_child(npc_label)

    # 经理
    if boss_here:
        boss_indicator.visible = true
        boss_indicator.text = "  🐙 鲍斯（经理）在这里！"
    else:
        boss_indicator.visible = false

    # 状态栏 - 从coworkers或data中读取
    # 注意：精确数据需要从get_status获取，这里用可获得的信息
    # 状态栏在TopBar已有，这里补充记录卡信息

    if data.has("positions") and data.has("player_room"):
        update_room_overview(data["positions"], str(data["player_room"]))


func update_hour_progress(hour: int, total_hours: int = -1) -> void:
    """仅刷新小时进度UI，避免误触发房间/同事列表刷新。"""
    if total_hours > 0:
        _total_hours = total_hours
    _current_task_index = max(0, hour)
    hour_label.text = "第 %d / %d 小时" % [_current_task_index + 1, _total_hours]
    hour_progress.max_value = _total_hours
    hour_progress.value = _current_task_index + 1


func update_status(gold: int, battery: int, evidence: int, blank_cards: int) -> void:
    """更新底部状态栏"""
    gold_label.text = "💰 %d" % gold
    battery_label.text = "🔋 %d%%" % battery
    evidence_label.text = "📋 %d份" % evidence
    cards_label.text = "📼 %d张" % blank_cards


func show_notification(text: String, duration: float = 3.0, color: String = "yellow") -> void:
    """显示临时通知"""
    notification_label.text = "[color=%s]%s[/color]" % [color, text]
    _notification_timer = duration


func show_boss_alert(hint: String) -> void:
    """经理预警"""
    show_notification("⚠️ %s" % hint, 4.0, "orange")


func show_pua_interruption(target_name: String, is_player: bool) -> void:
    """PUA打断"""
    if is_player:
        show_notification("😱 经理把你拉去'赋能谈话'了！这个小时什么都干不了！", 5.0, "red")
    else:
        show_notification("😱 经理把%s拉去'赋能谈话'了！" % target_name, 4.0, "coral")

func _on_card_result_refresh(data: Dictionary) -> void:
    if data.has("positions") and data.has("player_room"):
        update_room_overview(data["positions"], str(data["player_room"]))


func update_room_overview(positions: Dictionary, player_room: String) -> void:
    """
    更新常驻房间概览面板。
    positions 支持两种格式：
    1) {"office": {"npc_details":[...], "boss_present": bool, "player_present": bool}, ...}
    2) {"player":"office", "laowang":"meeting", ...}
    """
    var room_detail_positions := _normalize_positions(positions)
    _room_detail_cache = room_detail_positions

    for room_key in ROOM_NAMES.keys():
        var row_node = room_overview_panel.get_node_or_null("Margin/VBox/RoomList/RoomRow_" + room_key)
        if row_node == null:
            continue

        var room_data = room_detail_positions.get(room_key, {})
        var names := []

        if room_data.get("player_present", false):
            names.append("👤你")

        var npc_details = room_data.get("npc_details", [])
        for npc in npc_details:
            names.append(str(npc.get("name", "")))

        if room_data.get("boss_present", false):
            names.append("🐙鲍斯")

        var room_name_label = row_node.get_node_or_null("RoomName")
        var people_label = row_node.get_node_or_null("PeopleLabel")

        if room_name_label:
            room_name_label.text = ROOM_NAMES[room_key]
            if room_key == player_room:
                room_name_label.add_theme_color_override("font_color", Color.YELLOW)
            else:
                room_name_label.remove_theme_color_override("font_color")

        if people_label:
            people_label.text = "(空)" if names.is_empty() else ", ".join(names)


func _normalize_positions(positions: Dictionary) -> Dictionary:
    var result := {}
    for room_key in ROOM_NAMES.keys():
        result[room_key] = {
            "npc_details": [],
            "boss_present": false,
            "player_present": false,
        }

    if positions.is_empty():
        return result

    # 房间详情结构：{"office": {"npc_details":[...], ...}}
    var sample = positions.values()[0]
    if sample is Dictionary:
        for room_key in ROOM_NAMES.keys():
            if positions.has(room_key):
                result[room_key] = positions[room_key]
        return result

    # 位置映射结构：{"player":"office", "laowang":"meeting", ...}
    for char_id in positions.keys():
        var room_key = str(positions[char_id])
        if not result.has(room_key):
            continue
        if char_id == "player":
            result[room_key]["player_present"] = true
        elif char_id == "boss":
            result[room_key]["boss_present"] = true
        else:
            result[room_key]["npc_details"].append({
                "id": char_id,
                "name": NPC_DISPLAY_NAMES.get(char_id, str(char_id)),
            })
    return result


func get_current_room_key() -> String:
    return _current_player_room_key


func get_available_scout_rooms() -> Array:
    """返回当前可侦察房间（排除玩家所在房间和无NPC房间）。"""
    var ordered_rooms := ["office", "meeting", "warehouse", "pantry", "reception", "boss_office"]
    var room_detail_positions := _room_detail_cache if not _room_detail_cache.is_empty() else _normalize_positions(_current_positions)
    var available: Array = []
    for room_key in ordered_rooms:
        if room_key == _current_player_room_key:
            continue
        var room_data = room_detail_positions.get(room_key, {})
        var npc_count = int((room_data.get("npc_details", []) as Array).size())
        if npc_count > 0:
            available.append(room_key)
    return available


func get_room_scout_targets(room_key: String) -> Array:
    """返回指定房间可盯梢NPC列表：[{id,name}]。"""
    var room_detail_positions := _room_detail_cache if not _room_detail_cache.is_empty() else _normalize_positions(_current_positions)
    var room_data = room_detail_positions.get(room_key, {})
    var targets: Array = []
    var npc_details: Array = room_data.get("npc_details", [])
    var has_normal_npc := npc_details.size() > 0
    var should_hide_boss_target := room_key == "boss_office" and has_normal_npc
    if bool(room_data.get("boss_present", false)) and not should_hide_boss_target:
        targets.append({
            "id": "boss",
            "name": "鲍斯（经理）",
        })
    for npc in npc_details:
        var npc_id := str(npc.get("id", "")).strip_edges()
        if npc_id == "":
            continue
        targets.append({
            "id": npc_id,
            "name": str(npc.get("name", npc_id)),
        })
    return targets
