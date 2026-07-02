extends Control
## 夜间界面 - 拉帮结伙状态机

@onready var title_label: Label = $Margin/VBox/NightTitleLabel
@onready var message_label: RichTextLabel = $Margin/VBox/NightMessageLabel
@onready var button_bar: HBoxContainer = $Margin/VBox/ButtonBar
@onready var alliance_btn: Button = $Margin/VBox/ButtonBar/SpyBtn
@onready var sleep_btn: Button = $Margin/VBox/ButtonBar/NextDayBtn
@onready var chat_panel: VBoxContainer = $Margin/VBox/ChatPanel
@onready var chat_content: RichTextLabel = $Margin/VBox/ChatPanel/ChatContent
@onready var scout_btn: Button = $Margin/VBox/ChatPanel/RecordChatBtn

var _option_box: VBoxContainer
var _state: String = "entering"
var _day: int = 1
var _battery: int = 0
var _alive_npcs: Array = []
var _visitors: Array = []
var _visitor_proposals: Dictionary = {}
var _active_visitor_id: String = ""
var _seek_target_npc_id: String = ""
var _player_alliance_done: bool = false
var _player_scout_done: bool = false

const SCOUT_COST := 25


func _ready() -> void:
	visible = false
	alliance_btn.pressed.connect(_on_alliance_pressed)
	sleep_btn.pressed.connect(_on_sleep_pressed)
	scout_btn.pressed.connect(_on_scout_pressed)
	scout_btn.reparent(button_bar)

	_option_box = VBoxContainer.new()
	_option_box.add_theme_constant_override("separation", 8)
	chat_panel.add_child(_option_box)

	NetworkManager.door_result_received.connect(_on_door_result)
	NetworkManager.alliance_result_received.connect(_on_alliance_result)
	NetworkManager.seek_result_received.connect(_on_seek_result)
	NetworkManager.night_scout_result_received.connect(_on_night_scout_result)
	NetworkManager.error_received.connect(_on_error)


func setup(data: Dictionary) -> void:
	visible = true
	_day = int(data.get("day", 1))
	_battery = int(data.get("battery", 0))
	_alive_npcs = data.get("alive_npcs", [])
	_visitors = data.get("night_visitors", [])
	_visitor_proposals = data.get("night_visitor_proposals", {})
	_player_alliance_done = bool(data.get("player_alliance_done", false))
	_player_scout_done = bool(data.get("player_scout_done", false))
	_active_visitor_id = ""
	_seek_target_npc_id = ""

	title_label.text = "🌙 第%d天 夜晚" % _day
	_set_main_text(data.get("message", "夜幕降临，你回到了自己的房间……"))
	_enter_state("entering")
	_enter_state("visitors_check")


func _enter_state(next_state: String, keep_current_text: bool = false) -> void:
	_state = next_state
	_clear_options()
	match _state:
		"entering":
			_set_main_text("夜幕降临，你回到了自己的房间……")
			_update_free_buttons(false)
		"visitors_check":
			if _visitors.is_empty():
				_enter_state("free_phase")
			else:
				_enter_state("visitor_interaction")
		"visitor_interaction":
			_render_visitor_choices()
			_update_free_buttons(false)
		"free_phase":
			if not keep_current_text:
				_set_main_text("今晚暂时安静了。你还可以决定下一步行动。")
			_update_free_buttons(true)
		"sleeping":
			_update_free_buttons(false)


func _render_visitor_choices() -> void:
	chat_panel.visible = true
	if _visitors.size() <= 1:
		var visitor = _visitors[0]
		_set_main_text("%s在敲你的门。" % str(visitor.get("npc_name", "某人")))
	else:
		var names: Array[String] = []
		for v in _visitors:
			names.append(str(v.get("npc_name", "某人")))
		_set_main_text("有人在敲你的门：%s" % " / ".join(names))

	for v in _visitors:
		var npc_id := str(v.get("npc_id", ""))
		var npc_name := str(v.get("npc_name", npc_id))
		_add_option_button("给%s开门" % npc_name, Callable(self, "_open_visitor_door").bind(npc_id))
	_add_option_button("都不开门", Callable(self, "_close_all_doors"))


func _open_visitor_door(npc_id: String) -> void:
	_set_main_text("你轻轻把门拉开一条缝……")
	_disable_option_buttons()
	NetworkManager.night_open_door(npc_id)


func _close_all_doors() -> void:
	_set_main_text("你屏住呼吸，没有回应门外的敲门声。")
	_disable_option_buttons()
	NetworkManager.night_open_door("")


func _on_door_result(data: Dictionary) -> void:
	if not data.get("opened", false):
		_player_alliance_done = false
		_set_main_text(str(data.get("message", "你没有开门。")))
		_enter_state("free_phase", true)
		return

	_active_visitor_id = str(data.get("visitor_npc_id", ""))
	var story: String = str(data.get("story_text", "")).strip_edges()
	var target_name := str(data.get("target_name", "某人"))
	if story == "":
		story = "门外的人压低声音，提出了合作请求。"
	chat_panel.visible = true
	_set_main_text("%s\n\n[b]提议：[/b]明天一起投%s？" % [story, target_name])
	_clear_options()
	_add_option_button("同意结盟", Callable(self, "_respond_visitor").bind(true))
	_add_option_button("拒绝提议", Callable(self, "_respond_visitor").bind(false))


func _respond_visitor(agree: bool) -> void:
	_disable_option_buttons()
	NetworkManager.night_respond(agree)


func _on_alliance_result(data: Dictionary) -> void:
	_player_alliance_done = true
	var msg := str(data.get("message", ""))
	if msg == "":
		msg = "你结束了这次夜谈。"
	if bool(data.get("agreed", false)):
		_set_main_text("✅ 你们达成了结盟。\n%s" % msg)
	else:
		_set_main_text("❌ 你拒绝了对方的提议。\n%s" % msg)
	_enter_state("free_phase", true)


func _on_alliance_pressed() -> void:
	if _player_alliance_done:
		return
	chat_panel.visible = true
	_set_main_text("你想找谁结盟？")
	_clear_options()
	for npc in _alive_npcs:
		var npc_id := str(npc.get("npc_id", ""))
		var npc_name := str(npc.get("npc_name", npc_id))
		_add_option_button(npc_name, Callable(self, "_choose_seek_partner").bind(npc_id, npc_name))
	_update_free_buttons(false)


func _choose_seek_partner(npc_id: String, npc_name: String) -> void:
	_seek_target_npc_id = npc_id
	_set_main_text("你想拉%s一起投谁？" % npc_name)
	_clear_options()
	for npc in _alive_npcs:
		var vote_target_id := str(npc.get("npc_id", ""))
		if vote_target_id == _seek_target_npc_id:
			continue
		var vote_target_name := str(npc.get("npc_name", vote_target_id))
		_add_option_button(
			vote_target_name,
			Callable(self, "_confirm_seek_alliance").bind(_seek_target_npc_id, vote_target_id)
		)
	_add_option_button("取消", Callable(self, "_cancel_to_free_phase"))


func _confirm_seek_alliance(target_npc_id: String, vote_target_id: String) -> void:
	_disable_option_buttons()
	NetworkManager.night_seek_alliance(target_npc_id, vote_target_id)


func _on_seek_result(data: Dictionary) -> void:
	_player_alliance_done = true
	var agreed := bool(data.get("agreed", false))
	var msg := str(data.get("message", ""))
	if agreed:
		_set_main_text("✅ 对方同意了你的结盟请求。\n%s" % msg)
	else:
		_set_main_text("❌ 对方拒绝了你的结盟请求。\n%s" % msg)
	_enter_state("free_phase", true)


func _on_scout_pressed() -> void:
	if _player_scout_done:
		return
	chat_panel.visible = true
	_set_main_text("你想巡视谁的房间？")
	_clear_options()
	for npc in _alive_npcs:
		var npc_id := str(npc.get("npc_id", ""))
		var npc_name := str(npc.get("npc_name", npc_id))
		_add_option_button(npc_name, Callable(self, "_confirm_scout").bind(npc_id))
	_add_option_button("取消", Callable(self, "_cancel_to_free_phase"))
	_update_free_buttons(false)


func _confirm_scout(target_npc_id: String) -> void:
	_disable_option_buttons()
	NetworkManager.night_scout(target_npc_id)


func _on_night_scout_result(data: Dictionary) -> void:
	_player_scout_done = true
	_battery = int(data.get("battery_remaining", _battery))
	_set_main_text(str(data.get("message", "巡视结束。")))
	_enter_state("free_phase", true)


func _cancel_to_free_phase() -> void:
	_enter_state("free_phase")


func _on_sleep_pressed() -> void:
	var game_ui = get_parent()
	if game_ui and game_ui.has_method("is_action_blocked_by_pause") and game_ui.is_action_blocked_by_pause():
		return

	_enter_state("sleeping")
	visible = false
	NetworkManager.proceed_to_next_day()


func _set_main_text(text: String) -> void:
	message_label.bbcode_enabled = true
	message_label.text = text
	chat_panel.visible = true
	chat_content.bbcode_enabled = true
	chat_content.text = text


func _add_option_button(text: String, action: Callable) -> void:
	var btn := Button.new()
	btn.custom_minimum_size = Vector2(0, 38)
	btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	btn.text = text
	btn.pressed.connect(action)
	_option_box.add_child(btn)


func _clear_options() -> void:
	for child in _option_box.get_children():
		child.queue_free()


func _disable_option_buttons() -> void:
	for child in _option_box.get_children():
		if child is Button:
			child.disabled = true


func _update_free_buttons(in_free_phase: bool) -> void:
	alliance_btn.visible = true
	scout_btn.visible = true
	sleep_btn.visible = true
	sleep_btn.disabled = not in_free_phase
	sleep_btn.text = "💤 睡觉（结束当天）"
	alliance_btn.text = "🤝 找人结盟"
	scout_btn.text = "🔍 巡视其他房间（消耗25%%电量）"

	if not in_free_phase:
		alliance_btn.disabled = true
		scout_btn.disabled = true
		return

	alliance_btn.disabled = _player_alliance_done
	scout_btn.disabled = _player_scout_done or _battery < SCOUT_COST
	if _battery < SCOUT_COST:
		scout_btn.text = "🔋 电量不足（%d%%）" % _battery


func _on_error(data: Dictionary) -> void:
	var err_type := str(data.get("error_type", ""))
	var msg := str(data.get("message", "操作失败"))
	if err_type == "night_seek_failed":
		_player_alliance_done = true
		_set_main_text("❌ %s" % msg)
		_enter_state("free_phase", true)
		return
	if err_type in ["night_open_door_failed", "night_respond_failed", "night_scout_failed"]:
		_set_main_text("❌ %s" % msg)
		_enter_state("free_phase", true)
