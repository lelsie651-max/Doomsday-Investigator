extends Control
## 游戏UI主控 - 阶段管理器（最终版）

@onready var task_selection_ui: Control = $TaskSelectionUI
@onready var event_popup: Control = $WorkingUI/Margin/VBox/MainContent/EventContentPanel/EventPopup
@onready var working_ui: Control = $WorkingUI
@onready var voting_ui: Control = $VotingUI
@onready var night_ui: Control = $NightUI
@onready var shop_ui: Control = $ShopUI
@onready var pause_button: Button = $PauseButton
@onready var pause_overlay: ColorRect = $PauseOverlay
@onready var work_shop_button: Button = $WorkingUI/Margin/VBox/BottomBar/ShopButton
@onready var work_scout_button: Button = $WorkingUI/Margin/VBox/BottomBar/ScoutButton
@onready var work_status_label: Label = $WorkingUI/Margin/VBox/BottomBar/StatusLabel
@onready var work_skip_button: Button = $WorkingUI/Margin/VBox/BottomBar/SkipButton

@onready var day_label: Label = $TopBar/DayLabel
@onready var gold_label: Label = $TopBar/GoldLabel
@onready var battery_label: Label = $TopBar/BatteryLabel
@onready var evidence_label: Label = $TopBar/EvidenceLabel
@onready var cards_top_label: Label = $TopBar/CardsTopLabel
@onready var pause_status_label: Label = $TopBar/PauseStatusLabel

var _all_panels: Array[Control] = []
var _current_hour: int = 0
var _total_hours: int = 0
var _pending_game_over: Dictionary = {}
var is_paused: bool = false
var _current_task_index: int = 0
var _work_phase: String = "moving"
var _latest_gold: int = 0
var _latest_battery: int = 100
var _latest_day: int = 1
var _scout_room_menu: PopupMenu
var _scout_target_menu: PopupMenu
var _scout_room_keys: Array[String] = []
var _scout_target_rows: Array[Dictionary] = []
var _pending_scout_room_key: String = ""
var _scout_in_flight: bool = false
var _npc_status_button: Button = null
var _npc_status_popup: PopupPanel = null
var _npc_status_text: RichTextLabel = null
var _npc_status_waiting: bool = false
var _helper_popup_instance: Node = null
# 动态创建的 panels(无 .tscn 节点,在 _ready 中实例化)
var login_ui: Control = null
var opening_ui: Control = null
var _ending_ui_instance: Control = null
var _ending_summary_cache: Dictionary = {}
var _memory_popup_instance: CanvasLayer = null
var _pending_opening_data: Dictionary = {}
var _ending_summary_requested: bool = false

const SCOUT_ROOM_LABELS := {
    "office": "🏢 主办公区",
    "meeting": "📋 会议室",
    "warehouse": "📦 仓库",
    "pantry": "☕ 茶水间",
    "reception": "🚪 接待区",
    "boss_office": "👔 经理办公室",
}


func _ready() -> void:
    var top_bar := get_node_or_null("TopBar")
    if top_bar:
        move_child(top_bar, get_child_count() - 1)

    _all_panels = [task_selection_ui, working_ui, voting_ui, night_ui]
    # 动态创建 LoginUI
    var login_script = load("res://scripts/login_ui.gd")
    if login_script:
        login_ui = login_script.new()
        add_child(login_ui)
        login_ui.start_pressed.connect(_on_login_start_pressed)
        _all_panels.append(login_ui)

    # 动态创建 OpeningUI
    var opening_script = load("res://scripts/opening_ui.gd")
    if opening_script:
        opening_ui = opening_script.new()
        add_child(opening_ui)
        opening_ui.finished.connect(_on_opening_finished)
        _all_panels.append(opening_ui)

    _hide_all_panels()
    event_popup.visible = false
    pause_overlay.visible = false
    pause_button.visible = false
    pause_status_label.visible = false
    pause_status_label.add_theme_color_override("font_color", Color(1.0, 0.85, 0.2))
    pause_button.pressed.connect(_on_pause_pressed)
    pause_overlay.gui_input.connect(_on_overlay_clicked)
    work_shop_button.pressed.connect(_on_work_shop_pressed)
    work_scout_button.pressed.connect(_on_work_scout_pressed)
    work_skip_button.pressed.connect(_on_work_skip_pressed)

    NetworkManager.connected_to_server.connect(_on_connected)
    NetworkManager.game_started.connect(_on_game_started)
    NetworkManager.work_started.connect(_on_work_started)
    NetworkManager.event_ready_received.connect(_on_event_ready)
    NetworkManager.card_result_received.connect(_on_card_result_top_bar)
    NetworkManager.negotiation_result_received.connect(_on_negotiation_result_top_bar)
    NetworkManager.buy_result_received.connect(_on_card_result_top_bar)
    NetworkManager.hour_advanced.connect(_on_hour_advanced)
    NetworkManager.record_card_used.connect(_on_record_card_ui_update)
    NetworkManager.record_scout_result_received.connect(_on_record_scout_ui_update)
    NetworkManager.vote_result_received.connect(_on_vote_result)
    NetworkManager.night_phase_data_received.connect(_on_night_phase)
    NetworkManager.new_day_started.connect(_on_new_day)
    NetworkManager.game_status_received.connect(_on_status_update)
    NetworkManager.error_received.connect(_on_error)
    NetworkManager.scout_dispatched_received.connect(_on_scout_dispatched)
    NetworkManager.scout_result_received.connect(_on_scout_result_ui)
    NetworkManager.night_scout_result_received.connect(_on_night_scout_result_ui)
    NetworkManager.ending_summary_received.connect(_on_ending_summary_received)
    if event_popup and event_popup.has_signal("request_next_task"):
        event_popup.request_next_task.connect(_on_request_next_task)
    if working_ui and working_ui.has_signal("movement_finished"):
        working_ui.movement_finished.connect(_on_movement_finished)
    _scout_room_menu = PopupMenu.new()
    _scout_room_menu.name = "ScoutRoomMenu"
    _scout_room_menu.id_pressed.connect(_on_scout_room_selected)
    add_child(_scout_room_menu)
    _scout_target_menu = PopupMenu.new()
    _scout_target_menu.name = "ScoutTargetMenu"
    _scout_target_menu.id_pressed.connect(_on_scout_target_selected)
    add_child(_scout_target_menu)
    _setup_npc_status_debug_ui()


func _on_connected() -> void:
    # 不再立即开始新游戏,而是先显示登录界面
    if login_ui:
        _show_panel(login_ui)
    else:
        # fallback:动态创建失败时直接走旧流程
        NetworkManager.request_new_game()


func _on_game_started(data: Dictionary) -> void:
    _update_top_bar(data)
    # 收到后端 game_started 后,先播放开场剧情,等剧情结束再进入任务选择
    var opening = data.get("opening", {})
    if opening_ui and opening is Dictionary and not opening.is_empty():
        _pending_opening_data = data  # 缓存数据,等开场结束后再 setup task_selection_ui
        _show_panel(opening_ui)
        opening_ui.setup(opening)
    else:
        # 没有 opening 数据时直接进任务选择(兜底)
        _show_panel(task_selection_ui)
        task_selection_ui.setup(data)
        # 首次进入任务选择阶段,触发引导
        TutorialManager.maybe_show("first_task_selection")
    shop_ui.visible = false


func _on_login_start_pressed() -> void:
    # 玩家在登录界面点击"开始游戏",请求后端创建新游戏
    # 重开局重置引导触发状态(防止同进程重开后引导不再弹)
    if has_node("/root/TutorialState"):
        TutorialState.reset_all()
    if has_node("/root/TutorialManager") and TutorialManager.has_method("clear_pending_queue"):
        TutorialManager.clear_pending_queue()
    NetworkManager.request_new_game()


func _on_opening_finished() -> void:
    # 开场剧情播完,玩家点击"开始游戏",进入任务选择阶段
    if not opening_ui or not task_selection_ui:
        return
    _show_panel(task_selection_ui)
    if not _pending_opening_data.is_empty():
        task_selection_ui.setup(_pending_opening_data)
        _pending_opening_data = {}
        # 首次进入任务选择阶段,触发引导
        TutorialManager.maybe_show("first_task_selection")


func _on_work_started(data: Dictionary) -> void:
    _hide_all_panels()
    _total_hours = data.get("total_hours", 8)
    _current_hour = 0
    _current_task_index = 0
    _scout_in_flight = false
    _show_panel(working_ui)
    working_ui.setup(data, _total_hours)
    _update_top_bar(data)
    work_status_label.text = "第%d/%d小时" % [_current_task_index + 1, _total_hours]
    set_work_phase("moving")
    if working_ui and working_ui.has_method("start_task_movement"):
        working_ui.start_task_movement(_current_task_index, _total_hours)


func _on_movement_finished() -> void:
    set_work_phase("moving")
    NetworkManager.notify_movement_done()


func _on_event_ready(data: Dictionary) -> void:
    if data.get("error", "") != "":
        print("[GameUI] event_ready error: %s" % data.get("error", ""))
        return
    _show_npc_pua_notification(data)
    if data.has("positions") and working_ui and working_ui.has_method("update_room_overview"):
        var current_room := "office"
        if working_ui.has_method("get_current_room_key"):
            current_room = str(working_ui.get_current_room_key())
        working_ui.update_room_overview(data["positions"], current_room)
    event_popup.show_event(data, _current_task_index, _total_hours)
    set_work_phase("act1")


func _on_hour_advanced(data: Dictionary) -> void:
    _update_top_bar(data)
    _sync_scout_state_from_payload(data)
    _show_npc_pua_notification(data)
    var phase = data.get("phase", "")
    if phase == "voting":
        event_popup.visible = false
        working_ui.visible = false
        var candidates = data.get("candidates", [])
        var day = data.get("day", 1)
        _show_panel(voting_ui)
        voting_ui.setup(candidates, day, data)
        # 首次进入投票阶段,触发引导
        TutorialManager.maybe_show("first_voting")
        return

    if _current_task_index >= _total_hours - 1:
        return

    _current_hour = data.get("hour", _current_hour + 1)
    _current_task_index = _current_hour
    work_status_label.text = "第%d/%d小时" % [_current_hour + 1, _total_hours]
    working_ui.update_from_data(data, _current_hour)

    if data.get("boss_alert"):
        working_ui.show_boss_alert(data["boss_alert"])
    var anomaly_text := str(data.get("anomaly_event_text", "")).strip_edges()
    if anomaly_text != "" and working_ui and working_ui.has_method("show_notification"):
        working_ui.show_notification("👀 异常目击：%s" % anomaly_text, 4.0, "orange")

    # PUA打断
    if data.get("pua_interruption"):
        var pua = data["pua_interruption"]
        var is_player: bool = pua.get("target_id", "") == "player"
        if is_player:
            _show_pua_warning_popup(true, pua.get("target_name", "?"))
        else:
            # 经理叫同事谈话只提醒一次（走引导状态）
            TutorialManager.maybe_show("helper_npc_pua_watch_tip")
        working_ui.show_pua_interruption(pua.get("target_name", "?"), is_player)

        # 如果玩家被PUA，弹出PUA事件让玩家用卡牌应对
        var pua_event = data.get("pua_event")
        if is_player and pua_event:
            event_popup.show_event(pua_event, _current_hour, _total_hours)
            return  # PUA事件会走正常的出牌流程

    var event = data.get("event", {})
    if not event.is_empty():
        event_popup.show_event(event, _current_hour, _total_hours)
    else:
        NetworkManager.skip_record_card()


func _on_request_next_task() -> void:
    _current_task_index += 1
    if _current_task_index >= _total_hours:
        # 触发后端日结算，进入投票阶段
        NetworkManager.skip_record_card()
        return
    work_status_label.text = "第%d/%d小时" % [_current_task_index + 1, _total_hours]
    set_work_phase("moving")
    if working_ui and working_ui.has_method("start_task_movement"):
        working_ui.start_task_movement(_current_task_index, _total_hours)


func _on_record_card_ui_update(data: Dictionary) -> void:
    var remaining = data.get("remaining_blank", 0)
    working_ui.cards_label.text = "📼 %d张" % remaining
    cards_top_label.text = "空白卡: %d张" % remaining
    var metrics := _extract_evidence_metrics(data)
    if metrics.get("valid", -1) >= 0:
        update_evidence_metrics(int(metrics.get("valid", 0)), int(metrics.get("recorded", -1)))


func _on_card_result_top_bar(data: Dictionary) -> void:
    _update_top_bar(data)
    _sync_scout_state_from_payload(data)
    if data.has("positions") and working_ui and working_ui.has_method("update_room_overview"):
        var current_room := "office"
        if working_ui.has_method("get_current_room_key"):
            current_room = str(working_ui.get_current_room_key())
        working_ui.update_room_overview(data["positions"], current_room)
    _update_button_states(_work_phase)
    # 协商系统引导预埋(Batch 6 后端接通后生效)
    var negotiation = data.get("negotiation", null)
    if negotiation != null and typeof(negotiation) == TYPE_DICTIONARY:
        var offer = negotiation.get("offer", {})
        var method = str((offer as Dictionary).get("method", "无")).strip_edges()
        # 只有 AI 真同意协商（method != "无"）才触发引导
        if method != "" and method != "无":
            var nego_type = str(negotiation.get("type", "")).strip_edges()
            if nego_type == "extortion":
                TutorialManager.maybe_show("first_extortion")
            elif nego_type == "plea":
                TutorialManager.maybe_show("first_plea")
    # 首次获得证据卡,触发引导
    var got_evidence = data.get("evidence_card") != null or data.get("got_evidence", false)
    if not got_evidence and data.has("record_result"):
        var record_result = data.get("record_result", {})
        got_evidence = str(record_result.get("record_type", "")).strip_edges().to_lower() == "evidence"
    if got_evidence:
        TutorialManager.maybe_show("first_evidence_card")


func _on_negotiation_result_top_bar(data: Dictionary) -> void:
    _update_top_bar(data)
    _update_button_states(_work_phase)


func _on_record_scout_ui_update(data: Dictionary) -> void:
    if data.has("remaining_blank"):
        var remaining = int(data.get("remaining_blank", 0))
        working_ui.cards_label.text = "📼 %d张" % remaining
        cards_top_label.text = "空白卡: %d张" % remaining
    var metrics := _extract_evidence_metrics(data)
    if metrics.get("valid", -1) >= 0:
        update_evidence_metrics(int(metrics.get("valid", 0)), int(metrics.get("recorded", -1)))

func _on_vote_result(data: Dictionary) -> void:
    if data.get("game_over", false):
        _pending_game_over = data


func _on_night_phase(data: Dictionary) -> void:
    if data.get("phase") == "game_over":
        _pending_game_over = data
        return
    _show_panel(night_ui)
    night_ui.setup(data)
    # 首次进入夜间阶段,触发引导
    TutorialManager.maybe_show("first_night")


func _on_new_day(data: Dictionary) -> void:
    _update_top_bar(data)
    event_popup.visible = false
    _show_panel(task_selection_ui)
    task_selection_ui.setup(data)
    shop_ui.visible = false


func _on_status_update(data: Dictionary) -> void:
    _update_top_bar_from_status(data)
    _refresh_npc_status_popup(data)


func _on_error(data: Dictionary) -> void:
    print("[GameUI] 错误：%s" % data.get("message", ""))
    if _npc_status_waiting and data.get("error_type", "") == "status_error":
        _npc_status_waiting = false
        if _npc_status_text:
            _npc_status_text.bbcode_enabled = false
            _npc_status_text.text = "❌ 状态请求失败：%s" % str(data.get("message", "未知错误"))
    if data.get("error_type", "") == "scout_error":
        _scout_in_flight = false
        _pending_scout_room_key = ""
        _scout_target_rows.clear()
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("❌ %s" % data.get("message", "侦察失败"), 3.0, "red")
        _update_button_states(_work_phase)


func _show_npc_pua_notification(data: Dictionary) -> void:
    # 若已有结构化 pua_interruption，则由该路径统一处理，避免重复提醒。
    if data.has("pua_interruption"):
        var pua = data.get("pua_interruption", {})
        if pua is Dictionary and str(pua.get("target_id", "")) != "player":
            return
    var text := str(data.get("npc_pua_notification", "")).strip_edges()
    if text == "":
        return
    # 同事被经理叫去谈话：走引导状态，仅首次提醒。
    TutorialManager.maybe_show("helper_npc_pua_watch_tip")


func _sync_scout_state_from_payload(data: Dictionary) -> void:
    var scout = data.get("scout_result", null)
    if scout is Dictionary:
        _scout_in_flight = false
        if scout.has("battery_remaining"):
            _latest_battery = int(scout.get("battery_remaining", _latest_battery))
            battery_label.text = "电量: %d%%" % _latest_battery
        _show_scout_feedback_popup(scout)
        _update_button_states(_work_phase)


func _refresh_scout_button_text() -> void:
    if not work_scout_button:
        return
    if _scout_in_flight:
        work_scout_button.text = "侦察派遣中..."
        return
    work_scout_button.text = "🔍 侦察其他房间" if _latest_battery >= 33 else "🔋 电量不足"


func _show_panel(panel: Control) -> void:
    _hide_all_panels()
    panel.visible = true
    if panel == working_ui:
        _show_working_phase()
    else:
        _hide_working_phase()


func _hide_all_panels() -> void:
    for panel in _all_panels:
        panel.visible = false


func _on_pause_pressed() -> void:
    _toggle_pause()


func _on_overlay_clicked(event: InputEvent) -> void:
    if event is InputEventMouseButton and event.pressed:
        _toggle_pause()


func _toggle_pause() -> void:
    is_paused = !is_paused
    pause_overlay.visible = is_paused
    pause_status_label.visible = is_paused
    if is_paused:
        pause_button.text = "▶ 继续"
    else:
        pause_button.text = "⏸ 暂停"


func _show_working_phase() -> void:
    pause_button.visible = true
    is_paused = false
    pause_overlay.visible = false
    pause_status_label.visible = false
    pause_button.text = "⏸ 暂停"


func _hide_working_phase() -> void:
    pause_button.visible = false
    is_paused = false
    pause_overlay.visible = false
    pause_status_label.visible = false
    pause_button.text = "⏸ 暂停"
    event_popup.visible = false


func is_action_blocked_by_pause() -> bool:
    if is_paused:
        print("暂停中，请先取消暂停再操作")
        return true
    return false


func _unhandled_input(event: InputEvent) -> void:
    # F8 重置所有引导 flags(开发调试用)
    if event is InputEventKey and event.pressed and not event.echo:
        if event.keycode == KEY_F8:
            if has_node("/root/TutorialManager"):
                TutorialManager.reset_all_for_debug()
                get_viewport().set_input_as_handled()
                return
    if event.is_action_pressed("ui_cancel") and pause_button.visible:
        _toggle_pause()
        get_viewport().set_input_as_handled()


func _on_work_shop_pressed() -> void:
    if shop_ui and shop_ui.has_method("open_shop"):
        shop_ui.open_shop()
    else:
        NetworkManager.request_shop_data()


func _on_work_scout_pressed() -> void:
    print("[ScoutDebug] click phase=%s battery=%d in_flight=%s" % [_work_phase, _latest_battery, str(_scout_in_flight)])
    if is_action_blocked_by_pause():
        return
    if _work_phase != "act1":
        print("[ScoutDebug] blocked: not act1")
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("🔍 侦察仅可在 Act1 阶段使用。", 2.5, "orange")
        return
    if _latest_battery < 33:
        print("[ScoutDebug] blocked: low battery")
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("🔋 电量不足，无法侦察。", 2.5, "red")
        return
    if not working_ui or not working_ui.has_method("get_available_scout_rooms"):
        print("[ScoutDebug] blocked: working_ui missing get_available_scout_rooms")
        return
    var rooms: Array = working_ui.get_available_scout_rooms()
    print("[ScoutDebug] available_rooms=%s" % str(rooms))
    if rooms.is_empty():
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("📡 当前没有可侦察的目标房间。", 2.5, "yellow")
        return
    _show_scout_menu(rooms)


func _on_work_skip_pressed() -> void:
    if is_action_blocked_by_pause():
        return
    if event_popup and event_popup.has_method("quick_continue_from_bottom"):
        event_popup.quick_continue_from_bottom()


func _update_top_bar(data: Dictionary) -> void:
    if data.has("day"):
        _latest_day = int(data.get("day", _latest_day))
    elif data.has("total_days_survived"):
        _latest_day = int(data.get("total_days_survived", _latest_day))
    day_label.text = "第%d天" % _latest_day
    if data.has("player_gold"):
        _latest_gold = int(data.get("player_gold", _latest_gold))
    elif data.has("gold"):
        _latest_gold = int(data.get("gold", _latest_gold))
    elif data.has("gold_remaining"):
        _latest_gold = int(data.get("gold_remaining", _latest_gold))
    elif data.has("gold_after"):
        _latest_gold = int(data.get("gold_after", _latest_gold))
    gold_label.text = "金币: %d" % _latest_gold
    if data.has("battery"):
        _latest_battery = int(data.get("battery", _latest_battery))
        battery_label.text = "电量: %s%%" % str(data.get("battery", "?"))
    elif data.has("player_battery"):
        _latest_battery = int(data.get("player_battery", _latest_battery))
        battery_label.text = "电量: %s%%" % str(data.get("player_battery", "?"))

    var metrics := _extract_evidence_metrics(data)
    if metrics.get("valid", -1) >= 0:
        update_evidence_metrics(int(metrics.get("valid", 0)), int(metrics.get("recorded", -1)))
    elif data.has("evidence_collected"):
        var evs = data.get("evidence_collected", [])
        update_evidence_metrics(evs.size(), int(data.get("recorded_cards_count", -1)))

    var blank_cards_value = null
    if data.has("remaining_blank"):
        blank_cards_value = int(data.get("remaining_blank", 0))
    elif data.has("player_blank_cards"):
        blank_cards_value = int(data.get("player_blank_cards", 0))
    elif data.has("blank_cards_count"):
        blank_cards_value = int(data.get("blank_cards_count", 0))
    elif data.has("blank_cards"):
        blank_cards_value = int(data.get("blank_cards", 0))
    if blank_cards_value != null:
        cards_top_label.text = "空白卡: %d张" % int(blank_cards_value)
        if working_ui and working_ui.has_node("Margin/VBox/MainContent/EventContentPanel/StatusBar/CardsLabel"):
            working_ui.cards_label.text = "📼 %d张" % int(blank_cards_value)


func _update_top_bar_from_status(data: Dictionary) -> void:
    _latest_day = int(data.get("day", _latest_day))
    day_label.text = "第%d天" % _latest_day
    _latest_gold = int(data.get("player_gold", _latest_gold))
    gold_label.text = "金币: %d" % _latest_gold
    _latest_battery = int(data.get("player_battery", _latest_battery))
    battery_label.text = "电量: %s%%" % str(data.get("player_battery", "?"))
    var metrics := _extract_evidence_metrics(data)
    if metrics.get("valid", -1) >= 0:
        update_evidence_metrics(int(metrics.get("valid", 0)), int(metrics.get("recorded", -1)))
    else:
        evidence_label.text = "有效证据: %s份 | 已记录卡: ?" % str(data.get("evidence_count", "?"))
    if data.has("remaining_blank"):
        cards_top_label.text = "空白卡: %d张" % int(data.get("remaining_blank", 0))
    elif data.has("player_blank_cards"):
        cards_top_label.text = "空白卡: %d张" % int(data.get("player_blank_cards", 0))
    elif data.has("blank_cards_count"):
        cards_top_label.text = "空白卡: %d张" % int(data.get("blank_cards_count", 0))
    else:
        cards_top_label.text = "空白卡: ?张"


func update_evidence_count(count: int) -> void:
    update_evidence_metrics(count, -1)


func update_evidence_metrics(valid_count: int, recorded_count: int = -1) -> void:
    if recorded_count >= 0:
        evidence_label.text = "有效证据: %d份 | 已记录卡: %d张" % [valid_count, recorded_count]
    else:
        evidence_label.text = "有效证据: %d份 | 已记录卡: ?" % valid_count


func _extract_evidence_metrics(data: Dictionary) -> Dictionary:
    var valid := -1
    var recorded := -1
    if data.has("valid_evidence_count"):
        valid = int(data.get("valid_evidence_count", -1))
    elif data.has("evidence_count"):
        valid = int(data.get("evidence_count", -1))
    elif data.get("record_result", {}).has("valid_evidence_count"):
        valid = int(data.get("record_result", {}).get("valid_evidence_count", -1))
    elif data.get("record_result", {}).has("evidence_count"):
        valid = int(data.get("record_result", {}).get("evidence_count", -1))

    if data.has("recorded_cards_count"):
        recorded = int(data.get("recorded_cards_count", -1))
    elif data.get("record_result", {}).has("recorded_cards_count"):
        recorded = int(data.get("record_result", {}).get("recorded_cards_count", -1))
    return {"valid": valid, "recorded": recorded}


func set_work_phase(phase: String) -> void:
    _work_phase = phase
    _update_button_states(phase)


func _update_button_states(phase: String) -> void:
    if not work_shop_button or not work_scout_button or not work_skip_button:
        return
    work_skip_button.text = "继续 →"
    match phase:
        "moving":
            work_shop_button.disabled = false
            work_scout_button.disabled = true
            work_skip_button.disabled = true
            work_skip_button.text = "移动中..."
        "act1":
            work_shop_button.disabled = false
            work_scout_button.disabled = (_latest_battery < 33)
            work_skip_button.disabled = true
            work_skip_button.text = "请出牌"
        "act2":
            work_shop_button.disabled = false
            work_scout_button.disabled = true
            work_skip_button.disabled = false
            work_skip_button.text = "继续 →"
        "waiting_ai":
            work_shop_button.disabled = false
            work_scout_button.disabled = true
            work_skip_button.disabled = true
            work_skip_button.text = "NPC思考中..."
        _:
            work_shop_button.disabled = false
            work_scout_button.disabled = (_latest_battery < 33)
            work_skip_button.disabled = false
    _refresh_scout_button_text()


func _show_scout_menu(rooms: Array) -> void:
    print("[ScoutDebug] show room menu rooms=%s" % str(rooms))
    _scout_room_keys.clear()
    _scout_room_menu.clear()
    for i in range(rooms.size()):
        var room_key = str(rooms[i])
        _scout_room_keys.append(room_key)
        var label = SCOUT_ROOM_LABELS.get(room_key, room_key)
        _scout_room_menu.add_item("侦察 " + label, i)
    var btn_pos = work_scout_button.global_position
    _scout_room_menu.position = Vector2i(int(btn_pos.x), int(btn_pos.y - 8))
    _scout_room_menu.popup()


func _on_scout_room_selected(id: int) -> void:
    print("[ScoutDebug] room selected id=%d room_keys=%s" % [id, str(_scout_room_keys)])
    if id < 0 or id >= _scout_room_keys.size():
        print("[ScoutDebug] blocked: room id out of range")
        return
    var room_key = _scout_room_keys[id]
    var targets := _fetch_room_scout_targets(room_key)
    print("[ScoutDebug] targets room=%s targets=%s" % [room_key, str(targets)])
    if targets.is_empty():
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("📡 房间里没有人，不值得侦察。", 2.8, "yellow")
        _update_button_states(_work_phase)
        return
    if targets.size() == 1:
        _dispatch_scout_to_target(room_key, str(targets[0].get("id", "")))
        return
    _pending_scout_room_key = room_key
    _show_scout_target_menu(targets)


func _show_scout_target_menu(targets: Array) -> void:
    _scout_target_rows.clear()
    _scout_target_menu.clear()
    for i in range(targets.size()):
        var row: Dictionary = targets[i]
        var npc_name := str(row.get("name", row.get("id", "")))
        _scout_target_rows.append(row)
        _scout_target_menu.add_item("盯 " + npc_name, i)
    var btn_pos = work_scout_button.global_position
    _scout_target_menu.position = Vector2i(int(btn_pos.x), int(btn_pos.y - 8))
    _scout_target_menu.popup()


func _on_scout_target_selected(id: int) -> void:
    print("[ScoutDebug] target selected id=%d pending_room=%s rows=%s" % [id, _pending_scout_room_key, str(_scout_target_rows)])
    if id < 0 or id >= _scout_target_rows.size():
        print("[ScoutDebug] blocked: target id out of range")
        return
    if _pending_scout_room_key.strip_edges() == "":
        print("[ScoutDebug] blocked: pending room empty")
        return
    var npc_id := str(_scout_target_rows[id].get("id", "")).strip_edges()
    _dispatch_scout_to_target(_pending_scout_room_key, npc_id)


func _dispatch_scout_to_target(room_key: String, npc_id: String) -> void:
    print("[ScoutDebug] dispatch attempt room=%s npc=%s connected=%s" % [room_key, npc_id, str(NetworkManager.is_connected_to_server())])
    if npc_id.strip_edges() == "":
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("⚠️ 侦察目标无效，请重新选择。", 2.8, "orange")
        return
    _scout_in_flight = true
    work_scout_button.disabled = true
    work_scout_button.text = "侦察派遣中..."
    var sent := NetworkManager.dispatch_scout(room_key, npc_id)
    print("[ScoutDebug] dispatch sent=%s" % str(sent))
    if not sent:
        _scout_in_flight = false
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("❌ 小助理派遣失败，请检查连接后重试。", 3.0, "red")
        _update_button_states(_work_phase)
        return
    _pending_scout_room_key = ""
    _scout_target_rows.clear()


func _fetch_room_scout_targets(room_key: String) -> Array:
    if not working_ui or not working_ui.has_method("get_room_scout_targets"):
        return []
    return working_ui.get_room_scout_targets(room_key)


func get_scout_targets_for_room(room_key: String) -> Array:
    return _fetch_room_scout_targets(room_key)


func _on_scout_dispatched(data: Dictionary) -> void:
    _latest_battery = int(data.get("battery_remaining", _latest_battery))
    battery_label.text = "电量: %d%%" % _latest_battery
    if working_ui and working_ui.has_method("show_notification"):
        working_ui.show_notification("🔍 %s" % data.get("message", "小助理已出发"), 3.0, "yellow")
    _update_button_states(_work_phase)


func _on_scout_result_ui(data: Dictionary) -> void:
    _scout_in_flight = false
    _latest_battery = int(data.get("battery_remaining", _latest_battery))
    battery_label.text = "电量: %d%%" % _latest_battery
    _show_scout_feedback_popup(data)
    _update_button_states(_work_phase)


func _on_night_scout_result_ui(data: Dictionary) -> void:
    _scout_in_flight = false
    _latest_battery = int(data.get("battery_remaining", _latest_battery))
    battery_label.text = "电量: %d%%" % _latest_battery
    _show_scout_feedback_popup(data)
    _update_button_states(_work_phase)


func _show_scout_feedback_popup(data: Dictionary) -> void:
    var sentences = _build_scout_feedback_sentences(data)
    _show_helper_popup_sentences(sentences)


func _show_helper_popup_sentences(sentences: Array) -> void:
    var cleaned: Array = []
    for s in sentences:
        var line := str(s).strip_edges()
        if line != "":
            cleaned.append(line)
    if cleaned.is_empty():
        return
    if sentences.is_empty():
        return
    var script = load("res://scripts/helper_popup.gd")
    if script == null:
        push_warning("[GameUI] 无法加载 helper_popup.gd")
        return
    if _helper_popup_instance and is_instance_valid(_helper_popup_instance):
        _helper_popup_instance.queue_free()
    var popup = script.new()
    _helper_popup_instance = popup
    get_tree().root.add_child(popup)
    popup.setup(cleaned)
    popup.closed.connect(func() -> void:
        if _helper_popup_instance == popup:
            _helper_popup_instance = null
    )


func _show_pua_warning_popup(is_player: bool, target_name: String) -> void:
    var sentences: Array = []
    if is_player:
        sentences = _get_helper_sentences(
            "helper_pua_warning_player",
            {},
            [
            "⚠️ 糟糕!",
            "你似乎被经理盯上了。",
            "他让你去一趟办公室——做好心理准备。",
            ]
        )
    else:
        var display_name := str(target_name).strip_edges()
        if display_name == "":
            display_name = "某位同事"
        sentences = _get_helper_sentences(
            "helper_pua_warning_npc",
            {"target_name": display_name},
            [
            "📡 注意:",
            "%s 被经理叫到办公室谈话了。" % display_name,
            "你可以用我侦察经理办公室,查看具体发生了什么。",
            ]
        )
    _show_helper_popup_sentences(sentences)


func _build_scout_feedback_sentences(data: Dictionary) -> Array:
    var sentences: Array = []
    var title_sentences := _get_helper_sentences(
        "helper_scout_feedback_title",
        {},
        ["📡 侦察反馈："],
        false
    )
    if title_sentences.is_empty():
        sentences.append("📡 侦察反馈：")
    else:
        sentences.append(str(title_sentences[0]))

    if bool(data.get("accident", false)):
        var accident_text = str(data.get("accident_text", "")).strip_edges()
        if accident_text != "":
            sentences.append(accident_text)
        else:
            var fallback_list := _get_helper_sentences(
                "helper_scout_failed_fallback",
                {},
                ["侦察失败。"],
                false
            )
            var fallback_default := "侦察失败。"
            if not fallback_list.is_empty():
                fallback_default = str(fallback_list[0])
            var fallback_msg = str(data.get("message", fallback_default)).strip_edges()
            if fallback_msg != "":
                sentences.append(fallback_msg)
        return sentences

    var room_name = str(data.get("room_name", "")).strip_edges()
    var display_room_name = str(SCOUT_ROOM_LABELS.get(room_name, room_name)).strip_edges()
    if display_room_name != "":
        var room_line := _get_helper_sentences(
            "helper_scout_target_room",
            {"room_name": display_room_name},
            ["目标区域：%s" % display_room_name],
            false
        )
        if not room_line.is_empty():
            sentences.append(str(room_line[0]))
        else:
            sentences.append("目标区域：%s" % display_room_name)

    var observation = str(data.get("observation", "")).strip_edges()
    var message = str(data.get("message", "")).strip_edges()
    var body_text = observation if observation != "" else message
    if body_text == "":
        return []

    var raw_lines = body_text.split("|")
    if raw_lines.size() == 1:
        raw_lines = body_text.split("\n")
    for line in raw_lines:
        var clean = str(line).strip_edges()
        if not clean.is_empty():
            sentences.append(clean)

    if sentences.size() <= 1:
        sentences.append(body_text)
    return sentences


func _get_helper_sentences(key: String, params: Dictionary = {}, fallback: Array = [], include_title: bool = true) -> Array:
    if has_node("/root/TutorialManager") and TutorialManager.has_method("get_sentences"):
        var csv_sentences = TutorialManager.get_sentences(key, params, include_title)
        if csv_sentences is Array and not csv_sentences.is_empty():
            return csv_sentences
    return fallback.duplicate()


func _apply_opening_to_task_selection(_data: Dictionary) -> void:
    # 已废弃:opening 现在由 OpeningUI 独立播放,不再注入 task_selection_ui
    pass

func _request_ending_summary_once() -> void:
    # 防止同一局多次触发 game_over 导致重复请求
    if _ending_summary_requested:
        return
    _ending_summary_requested = true
    NetworkManager.request_ending_summary()


func _on_ending_summary_received(data: Dictionary) -> void:
    """收到结算数据,启动完整结局流程。"""
    _ending_summary_requested = false
    _ending_summary_cache = data

    # Step 1: 播放过场剧情(必有,因为段 1 修复了后端字段)
    var ending = data.get("ending", {})
    var sentences: Array = []
    var raw_sentences = ending.get("sentences", [])
    if raw_sentences is Array:
        for s in raw_sentences:
            var line := str(s).strip_edges()
            if line != "":
                sentences.append(line)

    if sentences.size() > 0:
        var cutscene_script = load("res://scripts/ending_cutscene_ui.gd")
        if cutscene_script != null:
            var cutscene_ui = cutscene_script.new()
            add_child(cutscene_ui)
            var image_path = str(ending.get("image_path", ""))
            cutscene_ui.setup(image_path, sentences)
            await cutscene_ui.finished

    # Step 2: 显示主结局页(三个按钮始终在)
    _show_ending_main_page()


func _show_ending_main_page() -> void:
    """显示主结局页(完整三个按钮)。"""
    if _ending_ui_instance and is_instance_valid(_ending_ui_instance):
        _ending_ui_instance.queue_free()
    _ending_ui_instance = null

    var script = load("res://scripts/ending_ui.gd")
    if script == null:
        push_warning("[GameUI] 无法加载 ending_ui.gd")
        return

    _ending_ui_instance = script.new()
    add_child(_ending_ui_instance)
    _ending_ui_instance.setup(_ending_summary_cache)
    _ending_ui_instance.view_memories_pressed.connect(_on_view_memories_pressed)
    _ending_ui_instance.restart_pressed.connect(_on_ending_restart)
    _ending_ui_instance.exit_pressed.connect(_on_ending_exit)


func _on_view_memories_pressed() -> void:
    """玩家点击[查看回忆]按钮,弹出独立 MemoryViewPopup。"""
    if _memory_popup_instance and is_instance_valid(_memory_popup_instance):
        return

    var script = load("res://scripts/memory_view_popup.gd")
    if script == null:
        push_warning("[GameUI] 无法加载 memory_view_popup.gd")
        return

    _memory_popup_instance = script.new()
    get_tree().root.add_child(_memory_popup_instance)
    _memory_popup_instance.setup(_ending_summary_cache)
    _memory_popup_instance.closed.connect(_on_memory_popup_closed)


func _on_memory_popup_closed() -> void:
    """记忆弹窗关闭,主结局页保持不变。"""
    _memory_popup_instance = null


func _on_ending_restart() -> void:
    """玩家点[重新开始]: 关闭所有弹窗,回登录页。"""
    if _memory_popup_instance and is_instance_valid(_memory_popup_instance):
        _memory_popup_instance.queue_free()
        _memory_popup_instance = null
    if _ending_ui_instance and is_instance_valid(_ending_ui_instance):
        _ending_ui_instance.queue_free()
        _ending_ui_instance = null

    if has_method("_show_panel") and login_ui:
        _show_panel(login_ui)


func _on_ending_exit() -> void:
    """玩家点[退出],EndingUI 已经处理 quit。"""
    pass


func _setup_npc_status_debug_ui() -> void:
    var top_bar := get_node_or_null("TopBar")
    if top_bar == null:
        return
    _npc_status_button = Button.new()
    _npc_status_button.name = "NpcStatusButton"
    _npc_status_button.text = "📊 NPC状态"
    _npc_status_button.custom_minimum_size = Vector2(110, 28)
    _npc_status_button.pressed.connect(_on_npc_status_pressed)
    top_bar.add_child(_npc_status_button)
    top_bar.move_child(_npc_status_button, top_bar.get_child_count() - 1)

    _npc_status_popup = PopupPanel.new()
    _npc_status_popup.name = "NpcStatusPopup"
    _npc_status_popup.size = Vector2i(900, 560)
    _npc_status_popup.visible = false
    add_child(_npc_status_popup)

    var root := VBoxContainer.new()
    root.add_theme_constant_override("separation", 8)
    root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    root.size_flags_vertical = Control.SIZE_EXPAND_FILL
    _npc_status_popup.add_child(root)

    var title := Label.new()
    title.text = "全员状态（调试）"
    root.add_child(title)

    _npc_status_text = RichTextLabel.new()
    _npc_status_text.bbcode_enabled = false
    _npc_status_text.fit_content = false
    _npc_status_text.custom_minimum_size = Vector2(860, 470)
    _npc_status_text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _npc_status_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
    root.add_child(_npc_status_text)

    var close_btn := Button.new()
    close_btn.text = "关闭"
    close_btn.custom_minimum_size = Vector2(100, 28)
    close_btn.pressed.connect(func() -> void:
        if _npc_status_popup:
            _npc_status_popup.hide()
    )
    root.add_child(close_btn)


func _on_npc_status_pressed() -> void:
    if _npc_status_popup == null or _npc_status_text == null:
        print("[NPC_STATUS] popup ui missing")
        return
    print("[NPC_STATUS] button pressed")
    _npc_status_waiting = true
    _npc_status_text.bbcode_enabled = false
    _npc_status_text.text = "正在拉取全员状态..."
    var sent := NetworkManager.request_game_status()
    if not sent:
        _npc_status_waiting = false
        _npc_status_text.text = "❌ 状态请求失败，请检查后端连接。"
        if working_ui and working_ui.has_method("show_notification"):
            working_ui.show_notification("❌ 状态请求失败：后端未连接", 2.8, "red")
    _npc_status_popup.popup_centered(Vector2i(900, 560))


func _refresh_npc_status_popup(data: Dictionary) -> void:
    if _npc_status_popup == null or _npc_status_text == null:
        return
    if not _npc_status_waiting and not _npc_status_popup.visible:
        return
    print("[NPC_STATUS] status received day=%s hour=%s" % [str(data.get("day", "?")), str(data.get("hour", "?"))])
    _npc_status_waiting = false
    var lines := PackedStringArray()
    lines.append("day=%s phase=%s hour=%s forced_duo_count=%s" % [
        str(data.get("day", "?")),
        str(data.get("phase", "?")),
        str(data.get("hour", "?")),
        str(data.get("forced_duo_trigger_count", 0)),
    ])
    var rows_variant: Variant = data.get("npc_status_list", [])
    if rows_variant is Array:
        var rows: Array = rows_variant
        for row_variant in rows:
            if not (row_variant is Dictionary):
                continue
            var row: Dictionary = row_variant
            lines.append("- %s | 金币:%d fear:%d 好感:%d 怀疑:%d | 房间:%s | 任务:%s" % [
                str(row.get("name", row.get("id", "NPC"))),
                int(row.get("gold", 0)),
                int(row.get("fear", 0)),
                int(row.get("affinity_to_player", 0)),
                int(row.get("suspicion_to_player", 0)),
                str(row.get("current_room", "-")),
                str(row.get("current_task", "-")),
            ])
    _npc_status_text.bbcode_enabled = false
    _npc_status_text.text = "\n".join(lines)
