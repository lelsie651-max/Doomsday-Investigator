extends Control
## Voting UI

@onready var root_vbox: VBoxContainer = $Margin/VBox
@onready var title_label: Label = $Margin/VBox/TitleLabel
@onready var hint_label: Label = $Margin/VBox/HintLabel
@onready var candidate_list: VBoxContainer = $Margin/VBox/CandidateList
@onready var result_section: VBoxContainer = $Margin/VBox/ResultSection
@onready var tally_label: RichTextLabel = $Margin/VBox/ResultSection/TallyLabel
@onready var outcome_label: RichTextLabel = $Margin/VBox/ResultSection/OutcomeLabel
@onready var continue_btn: Button = $Margin/VBox/ResultSection/VoteContinueBtn

var _candidates: Array = []
var _is_game_over: bool = false
var _game_over_data: Dictionary = {}
var _forced_vote_target_id: String = ""
var _forced_vote_warning_label: Label = null


func _ready() -> void:
    visible = false
    result_section.visible = false
    continue_btn.pressed.connect(_on_continue)
    NetworkManager.vote_result_received.connect(_on_vote_result)


func setup(candidates: Array, day: int, payload: Dictionary = {}) -> void:
    """Show voting panel."""
    visible = true
    _candidates = candidates
    _is_game_over = bool(payload.get("game_over", false))
    _game_over_data = payload
    _forced_vote_target_id = str(payload.get("forced_vote_target_id", "")).strip_edges()
    result_section.visible = false
    candidate_list.visible = true

    title_label.text = "第%d天 - 投票阶段" % day
    hint_label.text = str(payload.get("message", "投票时间到，请选择你认为最可疑的目标。"))
    _render_forced_vote_warning()

    for child in candidate_list.get_children():
        child.queue_free()

    for c in candidates:
        var npc_id := str(c.get("id", "")).strip_edges()
        var btn := Button.new()
        btn.text = "投票给 %s（%s）" % [c.get("name", "?"), c.get("species", "?")]
        btn.custom_minimum_size = Vector2(0, 45)
        btn.set_meta("npc_id", npc_id)
        btn.set_meta("base_text", btn.text)
        _apply_forced_vote_lock_to_button(btn)
        btn.pressed.connect(_on_vote_cast.bind(npc_id))
        candidate_list.add_child(btn)

    if payload.get("vote_cancelled_by_boss", false):
        candidate_list.visible = false
        result_section.visible = true
        tally_label.text = "[b]投票已取消[/b]"
        outcome_label.text = payload.get("outcome_text", "经理临时取消了本轮投票。")
        _is_game_over = payload.get("game_over", false)
        _game_over_data = payload
        continue_btn.text = "查看结局" if _is_game_over else "进入夜间"


func _on_vote_cast(target_id: String) -> void:
    if not _forced_vote_target_id.is_empty() and target_id != _forced_vote_target_id:
        push_warning("[VotingUI] 强制投票生效，只能投给 %s" % _forced_vote_target_id)
        hint_label.text = "⚠️ 你被胁迫了，今晚必须投票给：%s" % _get_npc_name_by_id(_forced_vote_target_id)
        return

    var game_ui = get_parent()
    if game_ui and game_ui.has_method("is_action_blocked_by_pause") and game_ui.is_action_blocked_by_pause():
        return

    for child in candidate_list.get_children():
        if child is Button:
            child.disabled = true
    hint_label.text = "已提交投票，正在等待计票结果..."
    NetworkManager.cast_vote(target_id)


func _on_vote_result(data: Dictionary) -> void:
    if not bool(data.get("success", true)):
        var error := str(data.get("error", "")).strip_edges()
        if error == "forced_vote_violation":
            var msg := str(data.get("message", "你被胁迫了，无法投这个目标。")).strip_edges()
            push_warning("[VotingUI] " + msg)
            hint_label.text = msg
            _restore_candidate_button_states()
            return
        return

    _clear_forced_vote_state()
    result_section.visible = true

    var tally_text := "[b]投票明细：[/b]\n"
    var details = data.get("vote_details", [])
    var reasons = data.get("vote_reasons", {})
    for d in details:
        var voter = d.get("voter_name", "?")
        var target = d.get("target_name", "?")
        var voter_id = d.get("voter_id", "")
        var reason = reasons.get(voter_id, "")
        if reason:
            tally_text += "  %s -> %s  [%s]\n" % [voter, target, reason]
        else:
            tally_text += "  %s -> %s\n" % [voter, target]

    var tally = data.get("tally", {})
    var target_name_map: Dictionary = {}
    for d in details:
        var target_id = str(d.get("target_id", "")).strip_edges()
        var target_name = str(d.get("target_name", "")).strip_edges()
        if target_id != "" and target_name != "":
            target_name_map[target_id] = target_name
    tally_text += "\n[b]计票结果：[/b]\n"
    for char_id in tally:
        var count = tally[char_id]
        var key := str(char_id).strip_edges()
        var display_name := ""
        if key == "player":
            display_name = "你"
        elif target_name_map.has(key):
            display_name = str(target_name_map.get(key, key)).strip_edges()
        else:
            display_name = _get_npc_name_by_id(key)
        tally_text += "  %s：%d票\n" % [display_name, int(count)]

    tally_label.text = tally_text
    outcome_label.text = data.get("outcome_text", "")
    continue_btn.text = "查看结局" if data.get("game_over", false) else "进入夜间"

    candidate_list.visible = false
    _is_game_over = data.get("game_over", false)
    _game_over_data = data


func _on_continue() -> void:
    var game_ui = get_parent()
    if game_ui and game_ui.has_method("is_action_blocked_by_pause") and game_ui.is_action_blocked_by_pause():
        return

    visible = false
    if _is_game_over:
        NetworkManager.request_ending_summary()
    else:
        NetworkManager.enter_night()


func _render_forced_vote_warning() -> void:
    if _forced_vote_warning_label != null and is_instance_valid(_forced_vote_warning_label):
        _forced_vote_warning_label.queue_free()
        _forced_vote_warning_label = null

    if _forced_vote_target_id.is_empty():
        return

    var target_name := _get_npc_name_by_id(_forced_vote_target_id)
    _forced_vote_warning_label = Label.new()
    _forced_vote_warning_label.text = "⚠️ 你被胁迫了，今晚必须投票给：%s" % target_name
    _forced_vote_warning_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    _forced_vote_warning_label.add_theme_font_size_override("font_size", 18)
    _forced_vote_warning_label.add_theme_color_override("font_color", Color(0.95, 0.3, 0.3))
    _forced_vote_warning_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    root_vbox.add_child(_forced_vote_warning_label)
    root_vbox.move_child(_forced_vote_warning_label, 2)


func _get_npc_name_by_id(npc_id: String) -> String:
    for c in _candidates:
        if str(c.get("id", "")).strip_edges() == npc_id:
            return str(c.get("name", npc_id)).strip_edges()
    return npc_id


func _apply_forced_vote_lock_to_button(btn: Button) -> void:
    var base_text := str(btn.get_meta("base_text", btn.text))
    var npc_id := str(btn.get_meta("npc_id", "")).strip_edges()
    btn.text = base_text
    btn.modulate = Color(1.0, 1.0, 1.0, 1.0)
    btn.disabled = false

    if _forced_vote_target_id.is_empty():
        return

    if npc_id == _forced_vote_target_id:
        btn.modulate = Color(1.2, 0.6, 0.6)
        btn.text = "▶ " + base_text + "（必投）"
    else:
        btn.disabled = true
        btn.text = base_text + "（已锁定）"


func _restore_candidate_button_states() -> void:
    for child in candidate_list.get_children():
        if child is Button:
            _apply_forced_vote_lock_to_button(child as Button)


func _clear_forced_vote_state() -> void:
    _forced_vote_target_id = ""
    if _forced_vote_warning_label != null and is_instance_valid(_forced_vote_warning_label):
        _forced_vote_warning_label.queue_free()
        _forced_vote_warning_label = null
