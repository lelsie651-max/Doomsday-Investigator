extends Node
## 网络管理器 - WebSocket 通讯单例
##
## 全局唯一，通过 Autoload 注册。
## 所有 UI 组件通过此单例与 Python 后端通讯。
##
## 使用方式：
##   发送：NetworkManager.send_message("play_cards", {"emotion": "E05", "action": "A08"})
##   接收：NetworkManager.message_received.connect(_on_message_received)
##   或监听具体类型：NetworkManager.card_result_received.connect(_on_card_result)

# ============================================================
# 信号定义（UI组件连接这些信号来接收数据）
# ============================================================

## 通用消息接收信号（所有消息都会触发）
signal message_received(msg_type: String, data: Dictionary)

## 连接状态信号
signal connected_to_server()
signal disconnected_from_server()
signal connection_error(error_msg: String)

## 各阶段专用信号（UI组件按需连接）
signal game_started(data: Dictionary)           # 新游戏创建，含任务池
signal work_started(data: Dictionary)            # 工作阶段开始，含第一个事件
signal movement_data_received(data: Dictionary)  # 移动阶段数据
signal event_ready_received(data: Dictionary)    # 移动后Act 1事件
signal card_result_received(data: Dictionary)    # 卡牌结算结果
signal negotiation_result_received(data: Dictionary) # 协商响应结果
signal record_card_used(data: Dictionary)        # 记录卡使用结果 + 下一小时
signal hour_advanced(data: Dictionary)           # 小时推进（跳过记录卡后）
signal vote_result_received(data: Dictionary)    # 投票结果
signal night_phase_entered(data: Dictionary)     # 进入夜间
signal night_phase_data_received(data: Dictionary)
signal door_result_received(data: Dictionary)
signal alliance_result_received(data: Dictionary)
signal seek_result_received(data: Dictionary)
signal night_scout_result_received(data: Dictionary)
signal blame_card_used_received(data: Dictionary)
signal blackmail_result_received(data: Dictionary)
signal scout_result_received(data: Dictionary)
signal scout_dispatched_received(data: Dictionary)
signal record_scout_result_received(data: Dictionary)
signal buy_result_received(data: Dictionary)
signal shop_data_received(data: Dictionary)
signal new_day_started(data: Dictionary)         # 新的一天开始
signal game_status_received(data: Dictionary)    # 游戏状态查询结果
signal debug_seeded_received(data: Dictionary)   # Debug强制布置结果
signal error_received(data: Dictionary)          # 后端返回错误
signal ending_summary_received(data: Dictionary)

# ============================================================
# 配置
# ============================================================

const SERVER_URL: String = "ws://localhost:8765"
const RECONNECT_DELAY: float = 3.0   # 重连等待秒数
const MAX_RECONNECT_ATTEMPTS: int = 5

# ============================================================
# 内部状态
# ============================================================

var _socket: WebSocketPeer = WebSocketPeer.new()
var _is_connected: bool = false
var _is_connecting: bool = false
var _reconnect_attempts: int = 0
var _reconnect_timer: float = 0.0
var _core_locked: bool = false   # 核心操作锁（出牌/投票/推进）

# ============================================================
# 生命周期
# ============================================================

func _ready() -> void:
    print("[NetworkManager] 初始化完成，准备连接服务器...")
    connect_to_server()


func _process(delta: float) -> void:
    # 每帧轮询 WebSocket
    _socket.poll()

    var state := _socket.get_ready_state()

    match state:
        WebSocketPeer.STATE_OPEN:
            if not _is_connected:
                _is_connected = true
                _is_connecting = false
                _reconnect_attempts = 0
                print("[NetworkManager] ✅ 已连接到服务器")
                connected_to_server.emit()

            # 读取所有待处理消息
            while _socket.get_available_packet_count() > 0:
                var raw := _socket.get_packet().get_string_from_utf8()
                _handle_message(raw)

        WebSocketPeer.STATE_CLOSING:
            pass  # 正在关闭，等待

        WebSocketPeer.STATE_CLOSED:
            if _is_connected:
                _is_connected = false
                _core_locked = false
                var code := _socket.get_close_code()
                var reason := _socket.get_close_reason()
                print("[NetworkManager] ❌ 连接断开 (code=%d, reason=%s)" % [code, reason])
                disconnected_from_server.emit()

            # 自动重连
            if _reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
                _reconnect_timer += delta
                if _reconnect_timer >= RECONNECT_DELAY:
                    _reconnect_timer = 0.0
                    _try_reconnect()

        WebSocketPeer.STATE_CONNECTING:
            pass  # 正在连接，等待

# ============================================================
# 连接管理
# ============================================================

func connect_to_server() -> void:
    """连接到 WebSocket 服务器"""
    if _is_connected or _is_connecting:
        return

    _is_connecting = true
    print("[NetworkManager] 正在连接 %s ..." % SERVER_URL)
    var err := _socket.connect_to_url(SERVER_URL)
    if err != OK:
        _is_connecting = false
        var msg := "连接失败，错误码：%d" % err
        print("[NetworkManager] ❌ %s" % msg)
        connection_error.emit(msg)


func disconnect_from_server() -> void:
    """断开连接"""
    if _is_connected:
        _socket.close()
        _is_connected = false
        _core_locked = false


func _try_reconnect() -> void:
    """尝试重连"""
    _reconnect_attempts += 1
    print("[NetworkManager] 重连尝试 %d/%d ..." % [_reconnect_attempts, MAX_RECONNECT_ATTEMPTS])

    # 重新创建 WebSocketPeer（Godot 4 需要）
    _socket = WebSocketPeer.new()
    connect_to_server()


func is_connected_to_server() -> bool:
    return _is_connected

# ============================================================
# 消息发送（前端 → 后端）
# ============================================================

func send_message(msg_type: String, data: Dictionary = {}) -> bool:
    if not _is_connected:
        print("[NetworkManager] ⚠️ 未连接，无法发送消息")
        connection_error.emit("未连接到服务器")
        return false

    # 只有核心操作才检查锁
    var is_core := msg_type in ["play_cards", "cast_vote", "enter_night", "next_day", "new_game", "select_tasks"]
    if is_core and _core_locked:
        print("[NetworkManager] ⚠️ 核心操作锁定中，请等待上一个操作完成")
        return false

    var message := {"type": msg_type, "data": data}
    var json_str := JSON.stringify(message)
    var err := _socket.send_text(json_str)

    if err != OK:
        print("[NetworkManager] ❌ 发送失败：%s" % msg_type)
        return false

    print("[NetworkManager] → 发送 [%s]%s" % [msg_type, " (核心)" if is_core else ""])
    if is_core:
        _core_locked = true
    return true

# ============================================================
# 便捷发送方法（给UI组件调用）
# ============================================================

func request_new_game() -> bool:
    return send_message("new_game")


func submit_task_selection(task_ids: Array) -> bool:
    return send_message("select_tasks", {"task_ids": task_ids})


func play_cards(emotion_id: String, action_id: String) -> bool:
    return send_message("play_cards", {"emotion": emotion_id, "action": action_id})


func play_solo_action(action_id: String) -> bool:
    return send_message("play_cards", {"mode": "solo_action", "solo_action": action_id})


func choose_work_mode(mode_id: String, target_npc_id: String = "", card_id: String = "") -> bool:
    var payload := {"mode": mode_id}
    if target_npc_id.strip_edges() != "":
        payload["target_npc"] = target_npc_id
    if card_id.strip_edges() != "":
        payload["card_id"] = card_id
    return send_message("choose_work_mode", payload)


func start_movement(task_index: int) -> bool:
    return send_message("start_move", {"task_index": task_index})


func notify_movement_done() -> bool:
    return send_message("movement_done")


# 兼容旧调用名
func start_move(task_index: int) -> bool:
    return start_movement(task_index)


# 兼容旧调用名
func movement_done() -> bool:
    return notify_movement_done()


func use_record_card(card_id: String, record_type: String = "evidence") -> bool:
    return send_message("use_record_card", {"card_id": card_id, "record_type": record_type})


func use_blame_card(target_npc_id: String) -> bool:
    return send_message("use_blame_card", {"target_npc": target_npc_id})


func use_blackmail(card_id: String, target_npc_id: String) -> bool:
    return send_message("use_blackmail", {"card_id": card_id, "target_npc": target_npc_id})


func scout_room(target_room: String, target_npc_id: String = "") -> bool:
    var payload := {"target_room": target_room}
    if target_npc_id.strip_edges() != "":
        payload["target_npc_id"] = target_npc_id.strip_edges()
    var sent := send_message("scout_room", payload)
    if not sent:
        error_received.emit({"error_type": "scout_error", "message": "侦察请求未发出，请检查网络连接"})
    return sent


func dispatch_scout(target_room: String, target_npc_id: String = "") -> bool:
    var payload := {"target_room": target_room}
    if target_npc_id.strip_edges() != "":
        payload["target_npc_id"] = target_npc_id.strip_edges()
    var sent := send_message("scout_dispatch", payload)
    if not sent:
        error_received.emit({"error_type": "scout_error", "message": "小助理派遣失败，请稍后重试"})
    return sent


func record_scout_evidence(evidence_tag: String) -> bool:
    # 已废弃：仅作"记录为证据"的兼容入口保留可回滚。
    # 新流程统一走 record_scout_evidence_v2(record_type, evidence_tag)。
    return send_message("record_scout", {"evidence_tag": evidence_tag, "record_type": "evidence"})


func record_scout_evidence_v2(record_type: String, evidence_tag: String) -> bool:
    # v2：把小助理带回的信息记为证据或黑料。
    # record_type: "evidence" 或 "blackmail"
    var rt := record_type.strip_edges().to_lower()
    if rt != "evidence" and rt != "blackmail":
        rt = "evidence"
    return send_message("record_scout", {"evidence_tag": evidence_tag, "record_type": rt})

func skip_record_card() -> bool:
    return send_message("skip_record")


func cast_vote(target_npc_id: String) -> bool:
    return send_message("cast_vote", {"target_npc": target_npc_id})


func enter_night() -> bool:
    return send_message("enter_night")


func night_open_door(npc_id: String = "") -> bool:
    var trimmed := npc_id.strip_edges()
    return send_message("night_open_door", {"npc_id": trimmed, "open_door": trimmed != ""})


func night_respond(agree: bool) -> bool:
    return send_message("night_respond", {"agree": agree})


func night_seek_alliance(target_npc_id: String, vote_target_id: String) -> bool:
    return send_message(
        "night_seek_alliance",
        {
            "target_npc_id": target_npc_id.strip_edges(),
            "vote_target_id": vote_target_id.strip_edges(),
        }
    )


func night_scout(target_npc_id: String) -> bool:
    return send_message("night_scout", {"target_npc_id": target_npc_id.strip_edges()})


func buy_item(item_key: String) -> bool:
    return send_message("buy_item", {"item_key": item_key})


func request_shop_data() -> bool:
    return send_message("get_shop")


func proceed_to_next_day() -> bool:
    return send_message("next_day")


func request_game_status() -> bool:
    return send_message("get_status")


func request_ending_summary() -> void:
    """请求结算界面数据(在游戏结束时由 game_ui 调用)。"""
    send_message("get_ending_summary", {})


func debug_seed_work_snapshot(payload: Dictionary) -> bool:
    return send_message("debug_seed_work_snapshot", payload)

# ============================================================
# 消息接收与分发（后端 → 前端）
# ============================================================

func _handle_message(raw: String) -> void:
    """解析后端消息并分发信号"""
    var parsed = JSON.parse_string(raw)
    if parsed == null:
        print("[NetworkManager] ⚠️ 无法解析消息：%s" % raw.substr(0, 100))
        _core_locked = false
        return

    var msg_type: String = parsed.get("type", "")
    var data: Dictionary = parsed.get("data", {})
    print("[NetworkManager] ← 收到 [%s]" % msg_type)

    # 解锁核心操作锁
    _core_locked = false

    # 发送通用信号
    message_received.emit(msg_type, data)

    # 发送专用信号
    match msg_type:
        "game_started":
            game_started.emit(data)
        "work_started":
            work_started.emit(data)
        "movement_data":
            movement_data_received.emit(data)
        "event_ready":
            event_ready_received.emit(data)
        "card_result":
            card_result_received.emit(data)
        "negotiation_result":
            negotiation_result_received.emit(data)
        "record_card_used":
            record_card_used.emit(data)
        "hour_advanced":
            hour_advanced.emit(data)
        "vote_result":
            vote_result_received.emit(data)
        "night_phase_data":
            night_phase_data_received.emit(data)
            night_phase_entered.emit(data)
        "door_result":
            door_result_received.emit(data)
        "alliance_result":
            alliance_result_received.emit(data)
        "seek_result":
            seek_result_received.emit(data)
        "scout_result":
            if data.has("target_npc_id"):
                night_scout_result_received.emit(data)
            else:
                scout_result_received.emit(data)
        "night_phase":
            night_phase_entered.emit(data)
        "blame_card_used":
            blame_card_used_received.emit(data)
        "blackmail_result":
            blackmail_result_received.emit(data)
        "scout_dispatched":
            scout_dispatched_received.emit(data)
        "record_scout_result":
            record_scout_result_received.emit(data)
        "buy_result":
            buy_result_received.emit(data)
        "shop_data":
            shop_data_received.emit(data)
        "new_day":
            new_day_started.emit(data)
        "game_status":
            game_status_received.emit(data)
        "debug_seeded":
            debug_seeded_received.emit(data)
        "ending_summary":
            ending_summary_received.emit(data)
        "error":
            error_received.emit(data)
            print("[NetworkManager] ⚠️ 后端错误：%s" % data.get("message", "未知错误"))
        _:
            print("[NetworkManager] ⚠️ 未知响应类型：%s" % msg_type)
