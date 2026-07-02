extends Control
## NetworkManager 连接测试场景
##
## 验证 WebSocket 通讯是否正常。
## 使用前请先启动 Python 后端：python server.py

@onready var status_label: Label = $VBoxContainer/StatusLabel
@onready var log_label: RichTextLabel = $VBoxContainer/LogLabel
@onready var new_game_btn: Button = $VBoxContainer/HBoxContainer/NewGameBtn
@onready var auto_play_btn: Button = $VBoxContainer/HBoxContainer/AutoPlayBtn
@onready var status_btn: Button = $VBoxContainer/HBoxContainer/StatusBtn

var _auto_playing: bool = false
var _current_task_pool: Array = []
var _current_event: Dictionary = {}


func _ready() -> void:
	# 设置UI
	status_label.text = "正在连接服务器..."
	log_label.bbcode_enabled = true
	log_label.text = ""
	new_game_btn.text = "新游戏"
	auto_play_btn.text = "自动试玩1天"
	status_btn.text = "查询状态"

	# 连接按钮信号
	new_game_btn.pressed.connect(_on_new_game)
	auto_play_btn.pressed.connect(_on_auto_play)
	status_btn.pressed.connect(_on_status)

	# 连接 NetworkManager 信号
	NetworkManager.connected_to_server.connect(_on_connected)
	NetworkManager.disconnected_from_server.connect(_on_disconnected)
	NetworkManager.connection_error.connect(_on_connection_error)

	# 连接所有游戏消息信号
	NetworkManager.game_started.connect(_on_game_started)
	NetworkManager.work_started.connect(_on_work_started)
	NetworkManager.card_result_received.connect(_on_card_result)
	NetworkManager.record_card_used.connect(_on_record_card_used)
	NetworkManager.hour_advanced.connect(_on_hour_advanced)
	NetworkManager.vote_result_received.connect(_on_vote_result)
	NetworkManager.night_phase_entered.connect(_on_night_phase)
	NetworkManager.new_day_started.connect(_on_new_day)
	NetworkManager.game_status_received.connect(_on_game_status)
	NetworkManager.error_received.connect(_on_error)


func _log(text: String) -> void:
	log_label.append_text(text + "\n")
	# 自动滚动到底部
	await get_tree().process_frame
	log_label.scroll_to_line(log_label.get_line_count() - 1)


# ============================================================
# 连接状态回调
# ============================================================

func _on_connected() -> void:
	status_label.text = "✅ 已连接到服务器"
	_log("[color=green]已连接到 WebSocket 服务器[/color]")


func _on_disconnected() -> void:
	status_label.text = "❌ 连接断开"
	_log("[color=red]连接已断开[/color]")


func _on_connection_error(msg: String) -> void:
	status_label.text = "❌ 连接错误"
	_log("[color=red]连接错误：%s[/color]" % msg)


# ============================================================
# 按钮操作
# ============================================================

func _on_new_game() -> void:
	_log("\n--- 请求新游戏 ---")
	NetworkManager.request_new_game()


func _on_status() -> void:
	NetworkManager.request_game_status()


func _on_auto_play() -> void:
	"""自动试玩1天：新游戏→选任务→打完所有牌→投票"""
	_auto_playing = true
	_log("\n[color=yellow]========== 自动试玩开始 ==========[/color]")
	NetworkManager.request_new_game()


# ============================================================
# 游戏消息回调
# ============================================================

func _on_game_started(data: Dictionary) -> void:
	var day = data.get("day", 0)
	_current_task_pool = data.get("task_pool", [])
	_log("🎮 游戏开始！第%d天，%d个任务可选" % [day, _current_task_pool.size()])

	if _auto_playing:
		# 自动选前6个任务
		var pick_count = mini(_current_task_pool.size(), 6)
		var task_ids: Array = []
		for i in range(pick_count):
			task_ids.append(_current_task_pool[i]["id"])
		_log("  自动选择%d个任务..." % pick_count)
		NetworkManager.submit_task_selection(task_ids)


func _on_work_started(data: Dictionary) -> void:
	var hour = data.get("hour", 0)
	_log("🏢 工作开始！第%d小时" % (hour + 1))

	_current_event = data.get("event", {})
	if _auto_playing and not _current_event.is_empty():
		_auto_play_event()


func _auto_play_event() -> void:
	"""自动打牌"""
	if _current_event.is_empty():
		return

	var emotions = _current_event.get("emotion_cards", [])
	var actions = _current_event.get("action_cards", [])
	if emotions.size() > 0 and actions.size() > 0:
		var e_id = emotions[0]["id"]
		var a_id = actions[0]["id"]
		_log("  🃏 自动出牌：%s + %s" % [emotions[0]["name"], actions[0]["name"]])
		NetworkManager.play_cards(e_id, a_id)


func _on_card_result(data: Dictionary) -> void:
	var combo = data.get("combination_type", "?")
	var text = data.get("result_text", "")
	_log("  结果[%s]：%s" % [combo, text.substr(0, 60)])

	if _auto_playing:
		# 跳过记录卡，推进下一小时
		NetworkManager.skip_record_card()


func _on_record_card_used(data: Dictionary) -> void:
	_log("  📼 记录卡已使用")
	var next_hour = data.get("next_hour", {})
	_process_next_hour(next_hour)


func _on_hour_advanced(data: Dictionary) -> void:
	_process_next_hour(data)


func _process_next_hour(data: Dictionary) -> void:
	"""处理小时推进后的响应"""
	var phase = data.get("phase", "")

	if phase == "voting":
		_log("\n⏰ 工作结束，进入投票")
		if _auto_playing:
			# 投票阶段的candidates在data里
			var candidates = data.get("candidates", [])
			if candidates.size() > 0:
				var target = candidates[0]["id"]
				_log("  自动投票给：%s" % candidates[0].get("name", target))
				NetworkManager.cast_vote(target)
		return

	# 还在工作阶段
	var hour = data.get("hour", 0)
	_log("  ⏰ 第%d小时" % (hour + 1))

	if data.get("boss_alert"):
		_log("  ⚠️ %s" % data["boss_alert"])

	if data.get("pua_interruption"):
		var pua = data["pua_interruption"]
		_log("  😱 %s被经理PUA了！" % pua.get("target_name", "?"))

	_current_event = data.get("event", {})
	if _auto_playing and not _current_event.is_empty():
		_auto_play_event()
	elif _auto_playing and _current_event.is_empty():
		# 无事件，继续推进
		NetworkManager.skip_record_card()


func _on_vote_result(data: Dictionary) -> void:
	var tally = data.get("tally", {})
	var outcome = data.get("outcome_text", "")
	_log("🗳️ 投票结果：%s" % str(tally))
	_log("  %s" % outcome.substr(0, 80))

	if data.get("game_over", false):
		_log("\n[color=red]游戏结束：%s[/color]" % data.get("game_result", ""))
		_auto_playing = false
		return

	if _auto_playing:
		_log("  进入夜间...")
		NetworkManager.enter_night()


func _on_night_phase(data: Dictionary) -> void:
	var msg = data.get("message", "")
	_log("🌙 %s" % msg.substr(0, 60))

	if data.get("phase") == "game_over":
		_log("\n[color=yellow]游戏结束！[/color]")
		_auto_playing = false
		return

	if _auto_playing:
		_auto_playing = false  # 只自动玩1天
		_log("\n[color=yellow]========== 自动试玩结束（1天）==========[/color]")
		_log("点击'查询状态'查看当前数据")


func _on_new_day(data: Dictionary) -> void:
	var day = data.get("day", 0)
	_current_task_pool = data.get("task_pool", [])
	_log("\n🌅 第%d天开始，%d个任务可选" % [day, _current_task_pool.size()])


func _on_game_status(data: Dictionary) -> void:
	_log("\n📊 游戏状态：")
	_log("  第%s天 阶段:%s" % [str(data.get("day", "?")), data.get("phase", "?")])
	_log("  金币:%s 电量:%s%% 证据:%s份" % [
		str(data.get("player_gold", "?")),
		str(data.get("player_battery", "?")),
		str(data.get("evidence_count", "?"))
	])
	_log("  存活NPC：%s" % str(data.get("alive_npcs", [])))
	_log("  游戏结果：%s" % str(data.get("game_result", "进行中")))


func _on_error(data: Dictionary) -> void:
	_log("[color=red]❌ 错误：%s[/color]" % data.get("message", "未知错误"))
