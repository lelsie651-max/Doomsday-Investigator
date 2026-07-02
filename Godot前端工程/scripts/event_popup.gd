extends Control
## 事件弹窗 + 卡牌选择界面
##
## 工作阶段每小时弹出一次。
## 玩家从5张情绪卡和5张行动卡中各选1张组合出牌。

signal request_next_task

@onready var event_panel: PanelContainer = $EventPanel
@onready var result_panel: PanelContainer = $ResultPanel
@onready var event_scroll: ScrollContainer = $EventPanel/Margin/VBox/EventScroll
@onready var result_scroll: ScrollContainer = $ResultPanel/Margin/VBox/ResultScroll

# 事件面板内部节点
@onready var event_name_label: Label = $EventPanel/Margin/VBox/EventNameLabel
@onready var event_desc_label: RichTextLabel = $EventPanel/Margin/VBox/EventScroll/Content/EventDescLabel
@onready var evidence_hint_label: Label = $EventPanel/Margin/VBox/EventScroll/Content/EvidenceHintLabel
@onready var prompt_label: Label = $EventPanel/Margin/VBox/EventScroll/Content/PromptLabel
@onready var emotion_container: HBoxContainer = $EventPanel/Margin/VBox/EventScroll/Content/CardSection/EmotionBox/EmotionCards
@onready var action_container: HBoxContainer = $EventPanel/Margin/VBox/EventScroll/Content/CardSection/ActionBox/ActionCards
@onready var emotion_title: Label = $EventPanel/Margin/VBox/EventScroll/Content/CardSection/EmotionBox/EmotionTitle
@onready var action_title: Label = $EventPanel/Margin/VBox/EventScroll/Content/CardSection/ActionBox/ActionTitle
@onready var play_btn: Button = $EventPanel/Margin/VBox/PlayBtn
@onready var hour_label: Label = $EventPanel/Margin/VBox/HourLabel

# 结果面板内部节点
@onready var result_combo_label: Label = $ResultPanel/Margin/VBox/ComboLabel
@onready var result_cards_label: Label = $ResultPanel/Margin/VBox/CardsLabel
@onready var result_text_label: RichTextLabel = $ResultPanel/Margin/VBox/ResultScroll/Content/ResultTextLabel
@onready var record_card_section: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/RecordCardSection
@onready var record_evidence_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/RecordCardSection/RecordEvidenceBtn
@onready var record_blackmail_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/RecordCardSection/RecordBlackmailBtn
@onready var skip_record_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/RecordCardSection/SkipRecordBtn
@onready var continue_btn: Button = $ResultPanel/Margin/VBox/ContinueBtn
@onready var blame_section: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/BlameSection
@onready var blame_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/BlameSection/BlameBtn
@onready var blame_target_list: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/BlameSection/BlameTargetList
@onready var scout_section: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/ScoutSection
@onready var scout_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/ScoutSection/ScoutBtn
@onready var scout_room_list: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/ScoutSection/ScoutRoomList
@onready var scout_result_label: RichTextLabel = $ResultPanel/Margin/VBox/ResultScroll/Content/ScoutSection/ScoutResultLabel
@onready var record_scout_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/ScoutSection/RecordScoutBtn
@onready var blackmail_section: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/BlackmailSection
@onready var blackmail_btn: Button = $ResultPanel/Margin/VBox/ResultScroll/Content/BlackmailSection/BlackmailBtn
@onready var blackmail_card_list: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/BlackmailSection/BlackmailCardList
@onready var blackmail_target_list: VBoxContainer = $ResultPanel/Margin/VBox/ResultScroll/Content/BlackmailSection/BlackmailTargetList
@onready var blackmail_result_label: RichTextLabel = $ResultPanel/Margin/VBox/ResultScroll/Content/BlackmailSection/BlackmailResultLabel

var _selected_emotion: String = ""
var _selected_action: String = ""
var _card_mode: String = "combo"
var _emotion_buttons: Array = []
var _action_buttons: Array = []
var _current_event: Dictionary = {}
var _current_result: Dictionary = {}
var _scout_evidence_tag: String = ""
var _scout_subject_npc_id: String = ""
var _record_scout_blackmail_btn: Button = null
var _skip_scout_btn: Button = null
var _selected_blackmail_card_id: String = ""
var _selected_work_mode: String = ""
var _selected_blackmail_choice_card_id: String = ""
var _work_mode_blackmail_card_pick: bool = false
var _work_mode_base_options: Array = []
var _work_mode_submit_mode: String = "blackmail_broadcast"
var _scout_pending_room_key: String = ""
var _scout_selecting_targets: bool = false
var _scout_target_rows: Array[Dictionary] = []
var _current_negotiation: Dictionary = {}

const SCOUT_ROOMS := {
    "office": "🏢 主办公区",
    "meeting": "📋 会议室",
    "warehouse": "📦 仓库",
    "pantry": "☕ 茶水间",
    "reception": "🚪 接待区",
}
const MODE_LABELS := {
    "report_boss": "向经理告密",
    "blackmail_broadcast": "传播黑料",
    "extortion": "勒索",
    "plea": "祈求保密",
    "negotiation": "协商",
}
const OPTION_LABEL_MAX_CHARS := 34


func _ready() -> void:
    visible = false
    event_panel.visible = false
    result_panel.visible = false

    play_btn.pressed.connect(_on_play_cards)
    play_btn.disabled = true

    continue_btn.pressed.connect(_on_continue)
    record_evidence_btn.pressed.connect(_on_record_as_evidence)
    record_blackmail_btn.pressed.connect(_on_record_as_blackmail)
    skip_record_btn.pressed.connect(_on_skip_record)
    blame_btn.pressed.connect(_on_blame_toggle)
    scout_btn.pressed.connect(_on_scout_toggle)
    # 旧 record_scout_btn 升级为"记录为证据"按钮，新流程统一走 v2。
    record_scout_btn.pressed.connect(_on_record_scout_as_evidence)
    _setup_scout_record_extra_buttons()
    blackmail_btn.pressed.connect(_on_blackmail_toggle)

    # 监听后端响应
    NetworkManager.card_result_received.connect(_on_card_result)
    NetworkManager.record_card_used.connect(_on_record_used)
    NetworkManager.blame_card_used_received.connect(_on_blame_result)
    NetworkManager.scout_result_received.connect(_on_scout_result)
    NetworkManager.scout_dispatched_received.connect(_on_scout_dispatched)
    NetworkManager.record_scout_result_received.connect(_on_record_scout_result)
    NetworkManager.blackmail_result_received.connect(_on_blackmail_result)
    NetworkManager.negotiation_result_received.connect(_on_negotiation_result)
    NetworkManager.error_received.connect(_on_network_error)
    NetworkManager.hour_advanced.connect(_on_hour_advanced)

    # === Batch UI Polish: 运行时视觉优化(不动 .tscn 结构) ===
    _apply_visual_polish()


func _apply_visual_polish() -> void:
    """运行时视觉优化:卡片化事件文本 + 居中卡牌 + 强化按钮。

    所有改动通过 add_theme_stylebox_override / 属性赋值实现,
    不修改 .tscn 节点层级。
    """
    _polish_event_panel_margin()
    _polish_event_desc_card()
    _polish_card_section_alignment()
    _polish_play_button()
    _polish_result_panel_visuals()


func _polish_event_panel_margin() -> void:
    """加大 EventPanel 整体边距,让内容不贴边。"""
    if event_panel == null:
        return
    var margin_node = event_panel.get_node_or_null("Margin")
    if margin_node and margin_node is MarginContainer:
        var mc := margin_node as MarginContainer
        mc.add_theme_constant_override("margin_left", 80)
        mc.add_theme_constant_override("margin_right", 80)
        mc.add_theme_constant_override("margin_top", 24)
        mc.add_theme_constant_override("margin_bottom", 32)


func _polish_event_desc_card() -> void:
    """事件文本卡片化:用 PanelContainer 包裹效果(运行时给 RichTextLabel 加内边距 + 背景)。"""
    if event_desc_label == null:
        return

    # 给 RichTextLabel 加深色背景 + 内边距(via theme override)
    # RichTextLabel 自身有 normal 样式槽
    var stylebox := StyleBoxFlat.new()
    stylebox.bg_color = Color(0.10, 0.11, 0.14, 0.85)
    stylebox.border_width_left = 2
    stylebox.border_width_right = 2
    stylebox.border_width_top = 2
    stylebox.border_width_bottom = 2
    stylebox.border_color = Color(0.35, 0.45, 0.55, 0.6)
    stylebox.corner_radius_top_left = 8
    stylebox.corner_radius_top_right = 8
    stylebox.corner_radius_bottom_left = 8
    stylebox.corner_radius_bottom_right = 8
    stylebox.content_margin_left = 24
    stylebox.content_margin_right = 24
    stylebox.content_margin_top = 18
    stylebox.content_margin_bottom = 18
    event_desc_label.add_theme_stylebox_override("normal", stylebox)

    # 字体加大 + 行间距
    event_desc_label.add_theme_font_size_override("normal_font_size", 17)
    event_desc_label.add_theme_color_override("default_color", Color(0.92, 0.92, 0.88))

    # 给 EventDescLabel 添加最小高度确保卡片感
    event_desc_label.custom_minimum_size = Vector2(0, 120)


func _polish_card_section_alignment() -> void:
    """卡牌区居中对齐 + 间距优化。"""
    if emotion_container:
        emotion_container.alignment = BoxContainer.ALIGNMENT_CENTER
        emotion_container.add_theme_constant_override("separation", 12)
    if action_container:
        action_container.alignment = BoxContainer.ALIGNMENT_CENTER
        action_container.add_theme_constant_override("separation", 12)

    # 卡牌标题居中+加粗
    if emotion_title:
        emotion_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        emotion_title.add_theme_font_size_override("font_size", 16)
        emotion_title.add_theme_color_override("font_color", Color(0.7, 0.85, 1.0))
    if action_title:
        action_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        action_title.add_theme_font_size_override("font_size", 16)
        action_title.add_theme_color_override("font_color", Color(1.0, 0.8, 0.6))

    # PromptLabel 居中
    if prompt_label:
        prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        prompt_label.add_theme_font_size_override("font_size", 14)
        prompt_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.7, 0.8))


func _polish_play_button() -> void:
    """PlayBtn 视觉强化:更醒目的样式。"""
    if play_btn == null:
        return

    play_btn.add_theme_font_size_override("font_size", 18)
    play_btn.custom_minimum_size = Vector2(0, 56)
    play_btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL

    # 默认样式(未选满)
    var stylebox_normal := StyleBoxFlat.new()
    stylebox_normal.bg_color = Color(0.15, 0.18, 0.22, 0.95)
    stylebox_normal.border_width_left = 2
    stylebox_normal.border_width_right = 2
    stylebox_normal.border_width_top = 2
    stylebox_normal.border_width_bottom = 2
    stylebox_normal.border_color = Color(0.3, 0.35, 0.4, 0.8)
    stylebox_normal.corner_radius_top_left = 8
    stylebox_normal.corner_radius_top_right = 8
    stylebox_normal.corner_radius_bottom_left = 8
    stylebox_normal.corner_radius_bottom_right = 8
    play_btn.add_theme_stylebox_override("normal", stylebox_normal)
    play_btn.add_theme_stylebox_override("disabled", stylebox_normal)

    # 悬停样式
    var stylebox_hover := StyleBoxFlat.new()
    stylebox_hover.bg_color = Color(0.22, 0.45, 0.55, 0.95)
    stylebox_hover.border_width_left = 2
    stylebox_hover.border_width_right = 2
    stylebox_hover.border_width_top = 2
    stylebox_hover.border_width_bottom = 2
    stylebox_hover.border_color = Color(0.4, 0.85, 0.95, 0.9)
    stylebox_hover.corner_radius_top_left = 8
    stylebox_hover.corner_radius_top_right = 8
    stylebox_hover.corner_radius_bottom_left = 8
    stylebox_hover.corner_radius_bottom_right = 8
    play_btn.add_theme_stylebox_override("hover", stylebox_hover)

    # 按下样式
    var stylebox_pressed := StyleBoxFlat.new()
    stylebox_pressed.bg_color = Color(0.18, 0.35, 0.45, 0.98)
    stylebox_pressed.border_width_left = 2
    stylebox_pressed.border_width_right = 2
    stylebox_pressed.border_width_top = 2
    stylebox_pressed.border_width_bottom = 2
    stylebox_pressed.border_color = Color(0.5, 0.9, 1.0, 1.0)
    stylebox_pressed.corner_radius_top_left = 8
    stylebox_pressed.corner_radius_top_right = 8
    stylebox_pressed.corner_radius_bottom_left = 8
    stylebox_pressed.corner_radius_bottom_right = 8
    play_btn.add_theme_stylebox_override("pressed", stylebox_pressed)

    play_btn.add_theme_color_override("font_color", Color(0.9, 0.92, 0.95))
    play_btn.add_theme_color_override("font_hover_color", Color(1.0, 1.0, 1.0))
    play_btn.add_theme_color_override("font_disabled_color", Color(0.5, 0.5, 0.55))


func _polish_result_panel_visuals() -> void:
    """Act2 样式统一：结果文本卡片化 + 按钮风格统一。"""
    # 文本区卡片化
    for label in [result_text_label, scout_result_label, blackmail_result_label]:
        if label == null:
            continue
        var text_box := StyleBoxFlat.new()
        text_box.bg_color = Color(0.10, 0.11, 0.14, 0.82)
        text_box.border_width_left = 2
        text_box.border_width_right = 2
        text_box.border_width_top = 2
        text_box.border_width_bottom = 2
        text_box.border_color = Color(0.32, 0.42, 0.52, 0.55)
        text_box.corner_radius_top_left = 8
        text_box.corner_radius_top_right = 8
        text_box.corner_radius_bottom_left = 8
        text_box.corner_radius_bottom_right = 8
        text_box.content_margin_left = 18
        text_box.content_margin_right = 18
        text_box.content_margin_top = 14
        text_box.content_margin_bottom = 14
        label.add_theme_stylebox_override("normal", text_box)
        label.add_theme_font_size_override("normal_font_size", 16)

    if result_combo_label:
        result_combo_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        result_combo_label.add_theme_font_size_override("font_size", 24)
    if result_cards_label:
        result_cards_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
        result_cards_label.add_theme_font_size_override("font_size", 16)
        result_cards_label.add_theme_color_override("font_color", Color(0.78, 0.82, 0.9))

    # Act2 固定按钮
    _style_action_button(continue_btn, Color(0.40, 0.82, 0.98), 50)
    _style_action_button(record_evidence_btn, Color(0.62, 0.90, 0.70), 40)
    _style_action_button(record_blackmail_btn, Color(0.98, 0.60, 0.72), 40)
    _style_action_button(skip_record_btn, Color(0.70, 0.75, 0.84), 34)
    _style_action_button(blame_btn, Color(0.95, 0.66, 0.50), 40)
    _style_action_button(scout_btn, Color(0.58, 0.86, 0.98), 40)
    _style_action_button(record_scout_btn, Color(0.62, 0.90, 0.70), 38)
    _style_action_button(blackmail_btn, Color(0.95, 0.58, 0.70), 40)
    _style_action_button(_record_scout_blackmail_btn, Color(0.95, 0.58, 0.70), 38)
    _style_action_button(_skip_scout_btn, Color(0.70, 0.75, 0.84), 34)


func _style_action_button(btn: Button, accent: Color, min_height: int = 38) -> void:
    if btn == null:
        return
    btn.add_theme_font_size_override("font_size", 16)
    btn.custom_minimum_size = Vector2(btn.custom_minimum_size.x, min_height)
    btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL

    var normal := StyleBoxFlat.new()
    normal.bg_color = Color(0.15, 0.18, 0.24, 0.95)
    normal.border_width_left = 2
    normal.border_width_right = 2
    normal.border_width_top = 2
    normal.border_width_bottom = 2
    normal.border_color = Color(accent.r * 0.7, accent.g * 0.7, accent.b * 0.7, 0.85)
    normal.corner_radius_top_left = 8
    normal.corner_radius_top_right = 8
    normal.corner_radius_bottom_left = 8
    normal.corner_radius_bottom_right = 8
    btn.add_theme_stylebox_override("normal", normal)
    btn.add_theme_stylebox_override("disabled", normal)

    var hover := StyleBoxFlat.new()
    hover.bg_color = Color(0.20, 0.24, 0.32, 0.98)
    hover.border_width_left = 2
    hover.border_width_right = 2
    hover.border_width_top = 2
    hover.border_width_bottom = 2
    hover.border_color = accent
    hover.corner_radius_top_left = 8
    hover.corner_radius_top_right = 8
    hover.corner_radius_bottom_left = 8
    hover.corner_radius_bottom_right = 8
    btn.add_theme_stylebox_override("hover", hover)

    var pressed := StyleBoxFlat.new()
    pressed.bg_color = Color(0.14, 0.17, 0.22, 1.0)
    pressed.border_width_left = 2
    pressed.border_width_right = 2
    pressed.border_width_top = 2
    pressed.border_width_bottom = 2
    pressed.border_color = Color(accent.r, accent.g, accent.b, 1.0)
    pressed.corner_radius_top_left = 8
    pressed.corner_radius_top_right = 8
    pressed.corner_radius_bottom_left = 8
    pressed.corner_radius_bottom_right = 8
    btn.add_theme_stylebox_override("pressed", pressed)

    btn.add_theme_color_override("font_color", Color(0.92, 0.94, 0.98))
    btn.add_theme_color_override("font_hover_color", Color(1.0, 1.0, 1.0))
    btn.add_theme_color_override("font_disabled_color", Color(0.50, 0.52, 0.58))


func show_event(event_data: Dictionary, hour: int, total_hours: int) -> void:
    """显示事件弹窗"""
    _current_event = event_data
    _selected_emotion = ""
    _selected_action = ""
    _selected_work_mode = ""
    _selected_blackmail_choice_card_id = ""
    _work_mode_blackmail_card_pick = false
    _work_mode_base_options = []
    _work_mode_submit_mode = "blackmail_broadcast"
    var raw_mode := str(event_data.get("card_mode", "")).strip_edges()
    var solo_actions: Array = event_data.get("solo_action_cards", [])
    var emotion_cards: Array = event_data.get("emotion_cards", [])
    var is_work_mode_choice := bool(event_data.get("choice_required", false)) and str(event_data.get("choice_mode", "")) == "work_mode"
    var inferred_solo := (
        raw_mode == "solo_action"
        or bool(event_data.get("is_solo_event", false))
        or bool(event_data.get("solo_action_mode", false))
        or (solo_actions.size() > 0 and emotion_cards.is_empty())
    )
    if is_work_mode_choice:
        _card_mode = "work_mode_choice"
        _work_mode_base_options = event_data.get("options", [])
    elif inferred_solo:
        _card_mode = "solo_action"
    else:
        _card_mode = "combo"

    visible = true
    event_panel.visible = true
    result_panel.visible = false
    _set_pua_visual_mode(bool(event_data.get("is_pua", false)))

    # 填充事件信息
    hour_label.text = "第 %d/%d 小时" % [hour + 1, total_hours]
    event_name_label.text = event_data.get("event_name", "???")
    event_desc_label.text = event_data.get("description", "")
    prompt_label.text = event_data.get("prompt", "")

    # 证据线索
    if event_data.get("has_evidence_hint", false):
        evidence_hint_label.visible = true
        evidence_hint_label.text = "💡 %s" % event_data.get("evidence_hint", "")
    else:
        evidence_hint_label.visible = false

    # 生成卡牌按钮
    if _card_mode == "work_mode_choice":
        _build_card_buttons([], event_data.get("options", []))
    else:
        _build_card_buttons(
            emotion_cards,
            solo_actions if _card_mode == "solo_action" else event_data.get("action_cards", [])
        )

    play_btn.disabled = true
    if _card_mode == "work_mode_choice":
        play_btn.text = "请选择 1个处理方式"
        emotion_container.visible = false
    elif _card_mode == "solo_action":
        play_btn.text = "请选择 1张单人行为牌"
        emotion_container.visible = false
    else:
        play_btn.text = "请选择 1张情绪卡 + 1张行动卡"
        emotion_container.visible = true
    action_container.visible = true
    if _card_mode == "solo_action":
        # 第一次出现单人事件时触发引导
        TutorialManager.maybe_show("first_solo_event")
    elif _card_mode == "combo":
        # 第一次出现双人事件时触发引导
        TutorialManager.maybe_show("first_duo_event")
    # 重置侦察区域
    if scout_section:
        scout_section.visible = false
        scout_btn.visible = false
        scout_result_label.visible = false
        _set_scout_record_buttons_visible(false)
        _scout_evidence_tag = ""
        _scout_subject_npc_id = ""
        _scout_pending_room_key = ""
        _scout_selecting_targets = false
        _scout_target_rows.clear()
    if blackmail_section:
        blackmail_section.visible = false
        blackmail_result_label.visible = false
        _selected_blackmail_card_id = ""

    call_deferred("_reset_event_scroll_to_top")


func _build_card_buttons(emotions: Array, actions: Array) -> void:
    """动态生成卡牌选择按钮"""
    # 清空旧按钮
    for child in emotion_container.get_children():
        child.queue_free()
    for child in action_container.get_children():
        child.queue_free()
    _emotion_buttons.clear()
    _action_buttons.clear()

    # 情绪卡（仅多人事件）
    if _card_mode == "combo":
        emotion_title.text = "情绪卡（选1张）："
        for card in emotions:
            var btn := Button.new()
            var is_normal: bool = card.get("is_normal", false)
            var icon := "⭐" if is_normal else "🤪"
            var evidence_marked: bool = bool(card.get("evidence_marked", false))
            var name_text := str(card.get("name", "?"))
            if evidence_marked:
                name_text = "%s 🔑" % name_text
            btn.text = "%s\n%s" % [icon, name_text]
            if evidence_marked:
                btn.tooltip_text = "🔑 选这张牌可在 Act 2 触发证据线索"
            btn.custom_minimum_size = Vector2(130, 70)
            btn.toggle_mode = true
            btn.set_meta("card_id", card.get("id", ""))
            btn.set_meta("card_type", "emotion")
            btn.set_meta("evidence_marked", evidence_marked)
            btn.toggled.connect(_on_card_toggled.bind(card.get("id", ""), "emotion", btn))
            emotion_container.add_child(btn)
            _emotion_buttons.append(btn)
    elif _card_mode == "solo_action":
        emotion_title.text = "情绪卡（单人事件不使用）"
    else:
        emotion_title.text = "情绪卡（该模式不使用）"

    # 行动卡 / 单人行为牌
    if _card_mode == "work_mode_choice":
        action_title.text = "处理方式（选1项）："
        # 传播黑料引导应在“选项出现时”触发，而不是点击后触发。
        if not _work_mode_blackmail_card_pick:
            for option in actions:
                if str(option.get("id", "")).strip_edges() == "blackmail_broadcast":
                    TutorialManager.maybe_show("first_blackmail_spread")
                    break
    elif _card_mode == "solo_action":
        action_title.text = "单人行为牌（选1张）："
    else:
        action_title.text = "行动卡（选1张）："
    for card in actions:
        var btn := Button.new()
        var card_evidence_marked := false
        if _card_mode == "work_mode_choice":
            var mode_code := str(card.get("id", "")).strip_edges()
            var display_label := str(MODE_LABELS.get(mode_code, mode_code))
            var full_label := str(card.get("full_label", card.get("label", display_label if display_label != "" else "选项")))
            btn.text = _truncate_ui_text(full_label, OPTION_LABEL_MAX_CHARS)
            btn.tooltip_text = full_label
            btn.clip_text = true
        else:
            var is_normal: bool = card.get("is_normal", false)
            var icon := "⭐" if is_normal else "🤪"
            card_evidence_marked = bool(card.get("evidence_marked", false))
            var name_text := str(card.get("name", "?"))
            if card_evidence_marked:
                name_text = "%s 🔑" % name_text
            btn.text = "%s\n%s" % [icon, name_text]
            if card_evidence_marked:
                btn.tooltip_text = "🔑 选这张牌可在 Act 2 触发证据线索"
        btn.custom_minimum_size = Vector2(130, 70)
        btn.toggle_mode = true
        btn.set_meta("card_id", card.get("id", ""))
        btn.set_meta("card_type", "action")
        btn.set_meta("evidence_marked", card_evidence_marked)
        btn.toggled.connect(_on_card_toggled.bind(card.get("id", ""), "action", btn))
        action_container.add_child(btn)
        _action_buttons.append(btn)


func _on_card_toggled(is_pressed: bool, card_id: String, card_type: String, btn: Button) -> void:
    """卡牌选择/取消"""
    if card_type == "emotion":
        if is_pressed:
            _selected_emotion = card_id
            # 取消其他情绪卡的选中
            for other in _emotion_buttons:
                if other != btn:
                    other.set_pressed_no_signal(false)
        else:
            if _selected_emotion == card_id:
                _selected_emotion = ""

    elif card_type == "action":
        if is_pressed:
            _selected_action = card_id
            if _card_mode == "work_mode_choice":
                _selected_work_mode = card_id
                if card_id.begins_with("blackmail_card:"):
                    _selected_blackmail_choice_card_id = card_id.replace("blackmail_card:", "")
                elif card_id != "blackmail_broadcast" and card_id != "report_boss":
                    _selected_blackmail_choice_card_id = ""
            for other in _action_buttons:
                if other != btn:
                    other.set_pressed_no_signal(false)
        else:
            if _selected_action == card_id:
                _selected_action = ""
            if _selected_work_mode == card_id:
                _selected_work_mode = ""
            if card_id.begins_with("blackmail_card:") and _selected_blackmail_choice_card_id == card_id.replace("blackmail_card:", ""):
                _selected_blackmail_choice_card_id = ""

    _update_play_button()


func _update_play_button() -> void:
    if _card_mode == "work_mode_choice":
        if _selected_work_mode != "":
            play_btn.disabled = false
            if _work_mode_blackmail_card_pick:
                if _selected_work_mode == "blackmail_back":
                    play_btn.text = "返回上一步"
                else:
                    play_btn.text = "确认传播黑料"
            else:
                play_btn.text = "确认处理方式"
        else:
            play_btn.disabled = true
            play_btn.text = "还需选择：黑料卡" if _work_mode_blackmail_card_pick else "还需选择：处理方式"
        return

    if _card_mode == "solo_action":
        if _selected_action != "":
            play_btn.disabled = false
            play_btn.text = "执行单人行为！"
        else:
            play_btn.disabled = true
            play_btn.text = "还需选择：单人行为牌"
        return

    if _selected_emotion != "" and _selected_action != "":
        play_btn.disabled = false
        play_btn.text = "出牌！"
    else:
        play_btn.disabled = true
        var missing := []
        if _selected_emotion == "":
            missing.append("情绪卡")
        if _selected_action == "":
            missing.append("行动卡")
        play_btn.text = "还需选择：%s" % "、".join(missing)


func _enter_blackmail_card_pick_mode(submit_mode: String = "blackmail_broadcast") -> void:
    var blackmail_cards: Array = _current_event.get("blackmail_cards", [])
    var options: Array = []
    for card in blackmail_cards:
        var cid := str(card.get("id", "")).strip_edges()
        if cid == "":
            continue
        var subject := str(card.get("subject_npc_name", "某同事")).strip_edges()
        if subject == "":
            subject = "某同事"
        options.append({
            "id": "blackmail_card:" + cid,
            "label": "关于" + subject + "的黑料",
            "full_label": "关于" + subject + "的黑料",
        })
    options.append({"id": "blackmail_back", "label": "返回处理方式选择"})
    _work_mode_blackmail_card_pick = true
    _work_mode_submit_mode = submit_mode
    _selected_work_mode = ""
    _selected_blackmail_choice_card_id = ""
    emotion_container.visible = false
    action_container.visible = true
    _build_card_buttons([], options)
    prompt_label.text = "请选择1条要提交的黑料。"
    _update_play_button()


func _exit_blackmail_card_pick_mode() -> void:
    _work_mode_blackmail_card_pick = false
    _work_mode_submit_mode = "blackmail_broadcast"
    _selected_work_mode = ""
    _selected_blackmail_choice_card_id = ""
    emotion_container.visible = false
    action_container.visible = true
    _build_card_buttons([], _work_mode_base_options)
    prompt_label.text = "你做出了处理选择，系统正在协调现场进展……"
    _update_play_button()


func _on_play_cards() -> void:
    var game_ui = _get_game_ui()
    if game_ui and game_ui.has_method("is_action_blocked_by_pause") and game_ui.is_action_blocked_by_pause():
        return

    # 社交精力兜底：传播黑料/打小报告在精力不足时直接前端拦截，避免卡住。
    if _card_mode == "work_mode_choice" and _needs_social_energy_for_current_work_mode():
        if _get_social_energy_left() <= 0:
            _show_social_energy_insufficient_popup()
            _update_play_button()
            return

    if game_ui and game_ui.has_method("set_work_phase"):
        game_ui.set_work_phase("waiting_ai")

    play_btn.disabled = true
    play_btn.text = "🤔 NPC正在思考..."
    # 隐藏卡牌区域，显示等待提示
    emotion_container.visible = false
    action_container.visible = false
    prompt_label.text = "你的话掷出去了，空气凝固了几秒钟……"
    if _card_mode == "solo_action":
        prompt_label.text = "你在空房间里做出了选择，四周开始出现变化……"
        if NetworkManager.has_method("play_solo_action"):
            NetworkManager.play_solo_action(_selected_action)
        else:
            # 兜底：即使autoload脚本未热更新，也直接走通用接口，避免前端报错中断。
            NetworkManager.send_message("play_cards", {"mode": "solo_action", "solo_action": _selected_action})
    elif _card_mode == "work_mode_choice":
        prompt_label.text = "你做出了处理选择，系统正在协调现场进展……"
        var selected_id := _selected_work_mode
        if _work_mode_blackmail_card_pick:
            if selected_id == "blackmail_back":
                _exit_blackmail_card_pick_mode()
                play_btn.disabled = false
                return
            if not selected_id.begins_with("blackmail_card:"):
                action_container.visible = true
                play_btn.disabled = false
                _update_play_button()
                return
            var chosen_card_id := selected_id.replace("blackmail_card:", "")
            _selected_blackmail_choice_card_id = chosen_card_id
            NetworkManager.choose_work_mode(_work_mode_submit_mode, "", chosen_card_id)
            return
        if selected_id == "blackmail_broadcast" or selected_id == "report_boss":
            _enter_blackmail_card_pick_mode(selected_id)
            play_btn.disabled = false
            return
        var mode_id := selected_id
        var target_npc := ""
        if selected_id.begins_with("interaction:"):
            mode_id = "interaction"
            target_npc = selected_id.replace("interaction:", "")
        NetworkManager.choose_work_mode(mode_id, target_npc, "")
    else:
        NetworkManager.play_cards(_selected_emotion, _selected_action)


func _on_card_result(data: Dictionary) -> void:
    """收到出牌结果（支持AI对话显示）"""
    visible = true
    # ===== Batch 8: PUA 事件优先识别 =====
    var is_pua := bool(data.get("is_pua_event", false))
    if is_pua:
        _show_pua_event(data)
        return

    _current_result = data
    var game_ui = _get_game_ui()
    if game_ui and game_ui.has_method("set_work_phase"):
        game_ui.set_work_phase("act2")

    var is_manager_event := bool(_current_event.get("is_pua", false))
    _set_pua_visual_mode(is_manager_event)
    event_panel.visible = false
    result_panel.visible = true
    _polish_result_panel_visuals()

    # 组合类型
    var combo_type: String = data.get("combination_type", "?")
    var combo_icons := {"steady": "😌 稳妥型", "contrast": "😵 反差型", "crazy": "🤯 癫狂型", "comply": "🤝 顺从型", "rebel": "⚡ 对抗型"}
    var is_solo_action: bool = data.get("solo_action_mode", false) or combo_type == "solo_action"
    if is_solo_action:
        result_combo_label.text = "🎯 单人行为结算"
    else:
        result_combo_label.text = combo_icons.get(combo_type, combo_type)

    # 使用的卡牌
    if is_solo_action:
        result_cards_label.text = "单人行为：%s" % data.get("action_name", "?")
    else:
        result_cards_label.text = "%s  x  %s" % [
            data.get("emotion_name", "?"),
            data.get("action_name", "?")
        ]

    # 构建结果文本（优先显示AI对话，降级显示硬编码文案）
    var dialogues = data.get("dialogues", {})
    var narrator = data.get("narrator", "")
    var old_result_text = data.get("result_text", "")

    if dialogues.size() > 0:
        # AI模式：显示每个NPC的对话 + 旁白
        var full_text := ""
        for npc_name in dialogues:
            var dialogue = str(dialogues[npc_name]).strip_edges()
            if dialogue != "":
                full_text += dialogue + "\n\n"
        if narrator:
            full_text += "[i]%s[/i]" % narrator
        result_text_label.bbcode_enabled = true
        result_text_label.text = full_text
    elif old_result_text:
        # 降级模式：显示硬编码文案
        result_text_label.bbcode_enabled = false
        result_text_label.text = old_result_text
    else:
        result_text_label.text = "（一阵诡异的沉默）"
    var settlement_append_text := str(data.get("settlement_append_text", "")).strip_edges()
    if settlement_append_text != "":
        if result_text_label.bbcode_enabled:
            result_text_label.text += "\n\n[i]%s[/i]" % settlement_append_text
        else:
            result_text_label.text += "\n\n" + settlement_append_text
    var ambient_message := str(data.get("ambient_message", "")).strip_edges()
    if ambient_message != "":
        if result_text_label.bbcode_enabled:
            result_text_label.text += "\n\n[i]%s[/i]" % ambient_message
        else:
            result_text_label.text += "\n\n" + ambient_message

    # 附加小助理异步侦察结果（如有）
    var has_inline_scout_record := false
    var scout = data.get("scout_result", null)
    if scout != null and scout is Dictionary:
        var is_accident: bool = bool(scout.get("accident", false))
        if scout.get("success", false):
            if is_accident:
                var accident_msg: String = str(scout.get("accident_text", scout.get("message", "小助理侦察发生意外"))).strip_edges()
                if accident_msg == "":
                    accident_msg = "小助理侦察发生意外"
                result_text_label.bbcode_enabled = false
                result_text_label.text += "\n\n💥 小助理侦察发生意外：" + accident_msg
                scout_section.visible = true
                scout_result_label.visible = true
                scout_result_label.bbcode_enabled = true
                scout_result_label.text = "[color=red]%s[/color]" % accident_msg
            else:
                var scout_text: String = str(scout.get("observation", scout.get("message", ""))).strip_edges()
                var inline_manager_related := bool(scout.get("is_manager_pua_related", data.get("is_manager_pua_related", false)))
                if scout_text != "":
                    result_text_label.bbcode_enabled = false
                    result_text_label.text += "\n\n🔍 小助理带回了消息：\n" + scout_text
                var blank_count_for_scout: int = int(data.get("blank_cards_count", 0))
                if (not inline_manager_related) and blank_count_for_scout > 0 and scout_text != "":
                    _scout_evidence_tag = str(scout.get("evidence_tag", ""))
                    _scout_subject_npc_id = str(scout.get("subject_npc_id", ""))
                    has_inline_scout_record = true
        else:
            var fail_msg: String = str(scout.get("accident_text", scout.get("message", "小助理回传失败"))).strip_edges()
            if fail_msg == "":
                fail_msg = "小助理回传失败"
            result_text_label.bbcode_enabled = false
            result_text_label.text += "\n\n⚠️ 小助理本次未成功回传：" + fail_msg
            scout_section.visible = true
            scout_result_label.visible = true
            scout_result_label.bbcode_enabled = true
            scout_result_label.text = "[color=orange]⚠️ %s[/color]" % fail_msg

    # 记录卡选项（逻辑不变）
    var can_record: bool = data.get("can_use_record_card", false)
    var blank_count: int = data.get("blank_cards_count", 0)
    _hide_negotiation_buttons()
    _current_negotiation = {}
    var negotiation = data.get("negotiation", null)
    if negotiation != null and negotiation is Dictionary:
        var offer = (negotiation as Dictionary).get("offer", {})
        var method := str((offer as Dictionary).get("method", "无")).strip_edges()
        if method != "" and method != "无":
            _current_negotiation = negotiation as Dictionary
            _show_negotiation_buttons(_current_negotiation)
        else:
            _show_record_buttons(can_record, blank_count)
    else:
        _show_record_buttons(can_record, blank_count)

    # 嫁祸卡选项
    var blame_count: int = data.get("blame_cards_count", 0)
    var blame_used_today: bool = data.get("blame_used_today", false)
    if blame_count > 0 and not blame_used_today:
        blame_section.visible = true
        blame_btn.text = "🎭 使用嫁祸卡（剩余%d张）" % blame_count
        blame_btn.disabled = false
        _clear_blame_targets()
    else:
        blame_section.visible = false

    # 侦察按钮
    var battery: int = data.get("battery", 0)
    if battery >= 33 or has_inline_scout_record:
        scout_section.visible = true
        scout_btn.visible = false
        scout_btn.disabled = true
        scout_room_list.visible = false
        scout_result_label.visible = false
        if has_inline_scout_record:
            _set_scout_record_buttons_visible(true)
            _refresh_scout_record_buttons(blank_count)
        else:
            _set_scout_record_buttons_visible(false)
            _scout_evidence_tag = ""
            _scout_subject_npc_id = ""
    else:
        scout_section.visible = false

    # 经理 PUA 事件不允许任何“记录”入口（普通记录 + 小助理记录）。
    if is_manager_event:
        _hide_all_record_buttons_for_pua()

    # 按需求仅前端隐藏“使用致命小黑历”入口（后端逻辑不变）
    blackmail_section.visible = false

    call_deferred("_reset_result_scroll_to_top")


func _show_pua_event(data: Dictionary) -> void:
    """显示 PUA 事件：全屏剧情 + [继续] 按钮。"""
    _current_result = data
    var game_ui = _get_game_ui()
    if game_ui and game_ui.has_method("set_work_phase"):
        game_ui.set_work_phase("act2")

    var full_text := str(data.get("act2_text", "")).strip_edges()
    if full_text == "":
        full_text = "（经理把你叫进办公室，关上了门。）"

    event_panel.visible = false
    result_panel.visible = true
    _set_pua_visual_mode(true)
    _polish_result_panel_visuals()

    result_combo_label.text = "⚠ 经理谈话"
    result_cards_label.text = ""
    result_text_label.bbcode_enabled = true
    result_text_label.text = "[color=#DC143C][b]%s[/b][/color]" % full_text

    # PUA 模式仅保留继续按钮，禁用记录/协商/其他交互入口
    _hide_negotiation_buttons()
    _disable_record_buttons()
    record_card_section.visible = false
    skip_record_btn.visible = false
    blame_section.visible = false
    scout_section.visible = false
    blackmail_section.visible = false

    continue_btn.visible = true
    continue_btn.disabled = false
    continue_btn.text = "  继 续  "

    call_deferred("_reset_result_scroll_to_top")


func _set_pua_visual_mode(enabled: bool) -> void:
    var panel_bg := Color(0.0, 0.0, 0.0, 1.0)
    var panel_border := Color(0.78, 0.08, 0.08, 1.0)
    var text_red := Color(0.86, 0.12, 0.22, 1.0)
    if enabled:
        var pua_panel := StyleBoxFlat.new()
        pua_panel.bg_color = panel_bg
        pua_panel.border_width_left = 2
        pua_panel.border_width_top = 2
        pua_panel.border_width_right = 2
        pua_panel.border_width_bottom = 2
        pua_panel.border_color = panel_border
        pua_panel.corner_radius_top_left = 8
        pua_panel.corner_radius_top_right = 8
        pua_panel.corner_radius_bottom_right = 8
        pua_panel.corner_radius_bottom_left = 8
        event_panel.add_theme_stylebox_override("panel", pua_panel)
        result_panel.add_theme_stylebox_override("panel", pua_panel)
        event_name_label.add_theme_color_override("font_color", text_red)
        hour_label.add_theme_color_override("font_color", text_red)
        prompt_label.add_theme_color_override("font_color", text_red)
        evidence_hint_label.add_theme_color_override("font_color", text_red)
        event_desc_label.add_theme_color_override("default_color", text_red)
        result_combo_label.add_theme_color_override("font_color", text_red)
        result_cards_label.add_theme_color_override("font_color", text_red)
        result_text_label.add_theme_color_override("default_color", text_red)
        scout_result_label.add_theme_color_override("default_color", text_red)
        return
    event_panel.remove_theme_stylebox_override("panel")
    result_panel.remove_theme_stylebox_override("panel")
    event_name_label.remove_theme_color_override("font_color")
    hour_label.remove_theme_color_override("font_color")
    prompt_label.remove_theme_color_override("font_color")
    evidence_hint_label.remove_theme_color_override("font_color")
    event_desc_label.remove_theme_color_override("default_color")
    result_combo_label.remove_theme_color_override("font_color")
    result_cards_label.remove_theme_color_override("font_color")
    result_text_label.remove_theme_color_override("default_color")
    scout_result_label.remove_theme_color_override("default_color")


func _reset_event_scroll_to_top() -> void:
    event_scroll.scroll_vertical = 0
    event_desc_label.scroll_to_line(0)


func _reset_result_scroll_to_top() -> void:
    result_scroll.scroll_vertical = 0
    result_text_label.scroll_to_line(0)
    scout_result_label.scroll_to_line(0)
    blackmail_result_label.scroll_to_line(0)


func _on_record_as_evidence() -> void:
    """记录为证据。"""
    record_evidence_btn.disabled = true
    record_blackmail_btn.disabled = true
    skip_record_btn.disabled = true
    record_evidence_btn.text = "记录中..."
    NetworkManager.use_record_card("auto", "evidence")


func _on_record_as_blackmail() -> void:
    """记录为黑料。"""
    record_evidence_btn.disabled = true
    record_blackmail_btn.disabled = true
    skip_record_btn.disabled = true
    record_blackmail_btn.text = "记录中..."
    NetworkManager.use_record_card("auto", "blackmail")


func _on_skip_record() -> void:
    """跳过记录卡"""
    request_next_task.emit()
    visible = false


func _show_record_buttons(can_record: bool, blank_count: int) -> void:
    if can_record and blank_count > 0:
        record_card_section.visible = true
        record_evidence_btn.text = "📋 记录为证据（剩余%d张）" % blank_count
        record_blackmail_btn.text = "🔪 记录为黑料（剩余%d张）" % blank_count
        record_evidence_btn.disabled = false
        record_blackmail_btn.disabled = false
        skip_record_btn.visible = true
        skip_record_btn.disabled = false
        skip_record_btn.text = "跳过"
        continue_btn.visible = false
    else:
        _disable_record_buttons()
        record_card_section.visible = false
        skip_record_btn.visible = false
        continue_btn.visible = false

    # 第一次看到记录按钮就触发引导
    # 协商两按钮走 _show_negotiation_buttons 不会触发,这里安全
    if blank_count > 0:
        TutorialManager.maybe_show("first_event_record")


func _hide_all_record_buttons_for_pua() -> void:
    _disable_record_buttons()
    record_card_section.visible = false
    skip_record_btn.visible = false
    _set_scout_record_buttons_visible(false)
    _scout_evidence_tag = ""
    _scout_subject_npc_id = ""


func _disable_record_buttons() -> void:
    record_evidence_btn.disabled = true
    record_blackmail_btn.disabled = true
    skip_record_btn.disabled = true


func _show_negotiation_buttons(negotiation: Dictionary) -> void:
    _disable_record_buttons()
    record_card_section.visible = false
    continue_btn.visible = false

    var nego_type := str(negotiation.get("type", "")).strip_edges()
    var offer = negotiation.get("offer", {})
    var method := str((offer as Dictionary).get("method", "")).strip_edges()
    var amount := int((offer as Dictionary).get("amount", 0))
    var npc_name := str(negotiation.get("npc_name", "对方")).strip_edges()

    var agree_label := "同意"
    var refuse_label := "拒绝"
    if nego_type == "plea":
        if method == "金钱":
            agree_label = "收下 %d 金币" % amount
        elif method == "黑料":
            var target := str((offer as Dictionary).get("blackmail_target_name", "")).strip_edges()
            if target == "":
                target = "某人"
            agree_label = "收下关于 %s 的黑料" % target
        else:
            agree_label = "答应 %s" % npc_name
    elif nego_type == "extortion":
        if method == "金钱":
            agree_label = "掏出 %d 金币" % amount
        elif method == "投票":
            var vote_target := str((offer as Dictionary).get("vote_target_name", "")).strip_edges()
            if vote_target == "":
                vote_target = "指定目标"
            agree_label = "答应今晚投 %s" % vote_target
        else:
            agree_label = "屈服"
    _create_negotiation_button_pair(agree_label, refuse_label)


func _create_negotiation_button_pair(agree_label: String, refuse_label: String) -> void:
    var button_container := _get_or_create_negotiation_button_container()
    for child in button_container.get_children():
        child.queue_free()

    var agree_btn := Button.new()
    agree_btn.text = "  " + agree_label + "  "
    agree_btn.custom_minimum_size = Vector2(220, 50)
    _style_action_button(agree_btn, Color(0.56, 0.90, 0.70), 50)
    agree_btn.pressed.connect(_on_negotiation_agree)
    button_container.add_child(agree_btn)

    var refuse_btn := Button.new()
    refuse_btn.text = "  " + refuse_label + "  "
    refuse_btn.custom_minimum_size = Vector2(160, 50)
    _style_action_button(refuse_btn, Color(0.96, 0.66, 0.64), 50)
    refuse_btn.pressed.connect(_on_negotiation_refuse)
    button_container.add_child(refuse_btn)

    button_container.visible = true


func _get_or_create_negotiation_button_container() -> HBoxContainer:
    var parent_node := record_card_section.get_parent()
    var existing = parent_node.get_node_or_null("NegotiationButtons")
    if existing != null and existing is HBoxContainer:
        return existing as HBoxContainer

    var hbox := HBoxContainer.new()
    hbox.name = "NegotiationButtons"
    hbox.alignment = BoxContainer.ALIGNMENT_CENTER
    hbox.add_theme_constant_override("separation", 20)
    parent_node.add_child(hbox)
    parent_node.move_child(hbox, record_card_section.get_index() + 1)
    return hbox


func _hide_negotiation_buttons() -> void:
    var parent_node := record_card_section.get_parent()
    var node = parent_node.get_node_or_null("NegotiationButtons")
    if node != null:
        node.visible = false


func _on_negotiation_agree() -> void:
    _hide_negotiation_buttons()
    if not _current_negotiation.is_empty():
        NetworkManager.send_message("respond_negotiation", {"agree": true})
    _current_negotiation = {}


func _on_negotiation_refuse() -> void:
    _hide_negotiation_buttons()
    if not _current_negotiation.is_empty():
        NetworkManager.send_message("respond_negotiation", {"agree": false})
    _current_negotiation = {}


func _on_negotiation_result(data: Dictionary) -> void:
    var agree := bool(data.get("agree", false))
    var summary := str(data.get("summary_text", "")).strip_edges()
    var validation_failed := bool(data.get("validation_failed", false))
    var can_record := bool(data.get("can_use_record_card", true))
    var blank_count := int(_current_result.get("blank_cards_count", 0))

    if summary != "":
        if result_text_label.text.strip_edges() == "":
            result_text_label.text = summary
        else:
            result_text_label.text += "\n\n" + summary

    if agree and not validation_failed:
        _hide_negotiation_buttons()
        _disable_record_buttons()
        record_card_section.visible = false
        skip_record_btn.visible = false
        continue_btn.visible = false
        request_next_task.emit()
        visible = false
        return

    _hide_negotiation_buttons()
    _show_record_buttons(can_record, blank_count)


func _on_blame_toggle() -> void:
    """展开/收起替罪羊选择列表"""
    if blame_target_list.visible:
        blame_target_list.visible = false
        return

    blame_target_list.visible = true
    _clear_blame_targets()

    # 从当前结果数据中获取在场NPC
    var reactions = _current_result.get("reactions", {})
    for npc_name in reactions:
        var npc_id := _name_to_id(npc_name)
        if npc_id == "boss":
            continue  # 不能甩锅给经理
        var btn := Button.new()
        btn.text = "甩给 %s" % npc_name
        btn.custom_minimum_size = Vector2(0, 35)
        _style_action_button(btn, Color(0.95, 0.66, 0.50), 36)
        btn.pressed.connect(_on_blame_target_selected.bind(npc_id, npc_name))
        blame_target_list.add_child(btn)


func _on_blame_target_selected(npc_id: String, npc_name: String) -> void:
    """选择替罪羊"""
    blame_btn.disabled = true
    blame_btn.text = "正在甩锅给%s..." % npc_name
    # 禁用所有目标按钮
    for child in blame_target_list.get_children():
        if child is Button:
            child.disabled = true
    NetworkManager.use_blame_card(npc_id)


func _on_blame_result(data: Dictionary) -> void:
    """嫁祸卡使用结果"""
    if data.get("success", false):
        blame_btn.text = "✅ %s" % data.get("message", "甩锅成功")
        blame_btn.disabled = true
        blame_target_list.visible = false
    else:
        blame_btn.text = "❌ %s" % data.get("message", "甩锅失败")


func _on_scout_toggle() -> void:
    if scout_room_list.visible:
        scout_room_list.visible = false
        _scout_selecting_targets = false
        _scout_pending_room_key = ""
        return

    # 清空并生成房间按钮
    _scout_selecting_targets = false
    _scout_pending_room_key = ""
    _scout_target_rows.clear()
    _show_scout_room_options()


func _show_scout_room_options() -> void:
    for child in scout_room_list.get_children():
        child.queue_free()
    scout_room_list.visible = true

    # 过滤掉玩家当前所在房间，避免误点后触发后端拒绝
    var current_room: String = _current_result.get("coworkers", {}).get("room", "")
    var available_rooms: Array = _current_result.get("scout_available_rooms", [])
    var added_count := 0
    var target_rooms: Array = available_rooms if available_rooms.size() > 0 else SCOUT_ROOMS.keys()
    for room_key in target_rooms:
        if room_key == current_room:
            continue
        if not SCOUT_ROOMS.has(room_key):
            continue
        var btn := Button.new()
        btn.text = "侦察 %s" % SCOUT_ROOMS[room_key]
        btn.custom_minimum_size = Vector2(0, 35)
        _style_action_button(btn, Color(0.58, 0.86, 0.98), 36)
        btn.pressed.connect(_on_scout_room_selected.bind(room_key))
        scout_room_list.add_child(btn)
        added_count += 1

    if added_count == 0:
        var hint := Label.new()
        hint.text = "（当前没有可侦察房间）"
        hint.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
        scout_room_list.add_child(hint)


func _on_scout_room_selected(room_key: String) -> void:
    var targets := _get_scout_targets_for_room(room_key)
    if targets.is_empty():
        scout_room_list.visible = false
        scout_result_label.visible = true
        scout_result_label.bbcode_enabled = true
        scout_result_label.text = "[color=yellow]房间里没有人，不值得侦察[/color]"
        return
    if targets.size() == 1:
        var only_target_id := str(targets[0].get("id", "")).strip_edges()
        if only_target_id == "":
            scout_result_label.visible = true
            scout_result_label.bbcode_enabled = true
            scout_result_label.text = "[color=orange]侦察目标异常，请重试[/color]"
            return
        if scout_btn:
            scout_btn.disabled = true
            scout_btn.text = "🔍 正在侦察..."
        scout_room_list.visible = false
        var sent := NetworkManager.dispatch_scout(room_key, only_target_id)
        if not sent:
            if scout_btn:
                scout_btn.disabled = false
                scout_btn.text = "🔍 侦察其他房间"
            scout_result_label.visible = true
            scout_result_label.bbcode_enabled = true
            scout_result_label.text = "[color=red]小助理派遣失败，请检查连接后重试[/color]"
            scout_room_list.visible = true
        return

    # 第二步：选择要盯的NPC
    _scout_pending_room_key = room_key
    _scout_selecting_targets = true
    _scout_target_rows.clear()
    for child in scout_room_list.get_children():
        child.queue_free()
    for row in targets:
        var npc_id := str(row.get("id", "")).strip_edges()
        if npc_id == "":
            continue
        var npc_name := str(row.get("name", npc_id))
        _scout_target_rows.append({"id": npc_id, "name": npc_name})
        var btn := Button.new()
        btn.text = "盯 %s" % npc_name
        btn.custom_minimum_size = Vector2(0, 35)
        _style_action_button(btn, Color(0.58, 0.86, 0.98), 36)
        btn.pressed.connect(_on_scout_target_selected.bind(npc_id, npc_name))
        scout_room_list.add_child(btn)
    var back_btn := Button.new()
    back_btn.text = "↩ 返回房间列表"
    back_btn.custom_minimum_size = Vector2(0, 30)
    _style_action_button(back_btn, Color(0.70, 0.75, 0.84), 32)
    back_btn.pressed.connect(_show_scout_room_options)
    scout_room_list.add_child(back_btn)


func _on_scout_target_selected(npc_id: String, npc_name: String) -> void:
    var target_id := npc_id.strip_edges()
    if target_id == "" or _scout_pending_room_key.strip_edges() == "":
        scout_result_label.visible = true
        scout_result_label.bbcode_enabled = true
        scout_result_label.text = "[color=orange]侦察目标异常，请重新选择[/color]"
        return
    if scout_btn:
        scout_btn.disabled = true
        scout_btn.text = "🔍 正在盯%s..." % npc_name
    scout_room_list.visible = false
    var sent := NetworkManager.dispatch_scout(_scout_pending_room_key, target_id)
    if not sent:
        if scout_btn:
            scout_btn.disabled = false
            scout_btn.text = "🔍 侦察其他房间"
        scout_result_label.visible = true
        scout_result_label.bbcode_enabled = true
        scout_result_label.text = "[color=red]小助理派遣失败，请检查连接后重试[/color]"
        scout_room_list.visible = true
        return
    _scout_pending_room_key = ""
    _scout_selecting_targets = false
    _scout_target_rows.clear()


func _on_scout_dispatched(data: Dictionary) -> void:
    scout_result_label.visible = true
    scout_result_label.bbcode_enabled = true
    _scout_pending_room_key = ""
    _scout_selecting_targets = false
    _scout_target_rows.clear()
    if scout_btn:
        scout_btn.disabled = false
        scout_btn.text = "🚀 已派出"
    scout_result_label.text = "[color=yellow]%s[/color]\n剩余电量：%d%%" % [
        data.get("message", "小助理已出发"),
        data.get("battery_remaining", 0),
    ]
    _set_scout_record_buttons_visible(false)


func _on_scout_result(data: Dictionary) -> void:
    scout_section.visible = true
    scout_result_label.visible = true
    scout_result_label.bbcode_enabled = true

    var manager_related := bool(data.get("is_manager_pua_related", false))
    if manager_related:
        _hide_all_record_buttons_for_pua()
    if data.get("accident", false):
        # 意外
        if scout_btn:
            scout_btn.text = "❌ 侦察失败！"
        var accident_color := "#DC143C" if manager_related else "red"
        scout_result_label.text = "[color=%s]%s[/color]\n\n剩余电量：%d%%" % [
            accident_color,
            data.get("accident_text", "出事了！"),
            data.get("battery_remaining", 0),
        ]
        if manager_related:
            result_text_label.bbcode_enabled = true
            result_text_label.text += "\n\n[color=#DC143C][b]💥 小助理侦察发生意外：%s[/b][/color]" % data.get("accident_text", "侦察失败")
        else:
            result_text_label.bbcode_enabled = false
            result_text_label.text += "\n\n💥 小助理侦察发生意外：%s" % data.get("accident_text", "侦察失败")
        _set_scout_record_buttons_visible(false)
    else:
        # 成功
        var room_name = data.get("room_name", "?")
        var npcs = data.get("npcs_in_room", [])
        var observation = data.get("observation", "")
        var boss_here = data.get("boss_in_room", false)

        if scout_btn:
            scout_btn.text = "✅ 侦察成功"

        var text := "[b]%s[/b]\n" % room_name
        text += "在场人员：%s\n" % ("、".join(npcs) if npcs.size() > 0 else "无人")
        if boss_here:
            text += "[color=#DC143C]🐙 经理在这里！[/color]\n"
        text += "\n%s\n" % observation
        text += "\n剩余电量：%d%%" % data.get("battery_remaining", 0)
        if manager_related:
            text = "[color=#DC143C][b]%s[/b][/color]" % text
        scout_result_label.text = text
        if manager_related:
            result_text_label.bbcode_enabled = true
            result_text_label.text += "\n\n[color=#DC143C][b]🔍 小助理侦察结果：[/b]\n%s[/color]" % observation
        else:
            result_text_label.bbcode_enabled = false
            result_text_label.text += "\n\n🔍 小助理侦察结果：\n%s" % observation

        # 小助理消息记录（证据/黑料二选一 + 跳过）
        var blank_now: int = int(_current_result.get("blank_cards_count", 0))
        if manager_related:
            _set_scout_record_buttons_visible(false)
            _scout_evidence_tag = ""
            _scout_subject_npc_id = ""
        elif str(observation).strip_edges() != "":
            _scout_evidence_tag = str(data.get("evidence_tag", ""))
            _scout_subject_npc_id = str(data.get("subject_npc_id", ""))
            _set_scout_record_buttons_visible(true)
            _refresh_scout_record_buttons(blank_now)
        else:
            _set_scout_record_buttons_visible(false)
            _scout_evidence_tag = ""
            _scout_subject_npc_id = ""


func _on_network_error(data: Dictionary) -> void:
    # 侦察请求被后端拒绝时，恢复UI状态，避免看起来“卡死”
    if not visible:
        return
    var error_type: String = data.get("error_type", "")
    if error_type != "scout_error":
        var msg_text := str(data.get("message", "")).strip_edges()
        if msg_text.find("社交精力不足") >= 0:
            _show_social_energy_insufficient_popup()
            # 恢复可操作状态，避免前端停留在“等待中”。
            action_container.visible = true
            play_btn.disabled = false
            _update_play_button()
        return

    var msg: String = data.get("message", "侦察失败")
    _scout_pending_room_key = ""
    _scout_selecting_targets = false
    _scout_target_rows.clear()
    scout_btn.disabled = false
    if scout_btn:
        scout_btn.text = "🔍 侦察其他房间"
    scout_result_label.visible = true
    scout_result_label.bbcode_enabled = true
    scout_result_label.text = "[color=red]%s[/color]" % msg
    _set_scout_record_buttons_visible(false)


func _get_scout_targets_for_room(room_key: String) -> Array:
    var game_ui = _get_game_ui()
    if game_ui and game_ui.has_method("get_scout_targets_for_room"):
        return game_ui.get_scout_targets_for_room(room_key)
    return []


func _on_record_scout() -> void:
    # 旧入口，保留可回滚。新流程走 _on_record_scout_as_evidence。
    _on_record_scout_as_evidence()


func _setup_scout_record_extra_buttons() -> void:
    # 把"记录为黑料 / 跳过"两个按钮动态加到 ScoutSection，紧随 RecordScoutBtn。
    if _record_scout_blackmail_btn != null and _skip_scout_btn != null:
        return
    if scout_section == null or record_scout_btn == null:
        return
    if _record_scout_blackmail_btn == null:
        _record_scout_blackmail_btn = Button.new()
        _record_scout_blackmail_btn.name = "RecordScoutBlackmailBtn"
        _record_scout_blackmail_btn.text = "🔪 记录为黑料"
        _record_scout_blackmail_btn.visible = false
        _record_scout_blackmail_btn.custom_minimum_size = Vector2(0, 32)
        _style_action_button(_record_scout_blackmail_btn, Color(0.95, 0.58, 0.70), 38)
        _record_scout_blackmail_btn.pressed.connect(_on_record_scout_as_blackmail)
        scout_section.add_child(_record_scout_blackmail_btn)
        scout_section.move_child(_record_scout_blackmail_btn, record_scout_btn.get_index() + 1)
    if _skip_scout_btn == null:
        _skip_scout_btn = Button.new()
        _skip_scout_btn.name = "SkipScoutBtn"
        _skip_scout_btn.text = "跳过"
        _skip_scout_btn.visible = false
        _skip_scout_btn.custom_minimum_size = Vector2(0, 28)
        _style_action_button(_skip_scout_btn, Color(0.70, 0.75, 0.84), 34)
        _skip_scout_btn.pressed.connect(_on_skip_scout)
        scout_section.add_child(_skip_scout_btn)
        scout_section.move_child(_skip_scout_btn, _record_scout_blackmail_btn.get_index() + 1)

func _set_scout_record_buttons_visible(flag: bool) -> void:
    if record_scout_btn:
        record_scout_btn.visible = flag
    if _record_scout_blackmail_btn:
        _record_scout_blackmail_btn.visible = flag
    if _skip_scout_btn:
        _skip_scout_btn.visible = flag


func _refresh_scout_record_buttons(blank_count: int) -> void:
    # 根据空白卡数量与是否有黑料目标，更新三按钮文案/启用状态。
    if record_scout_btn == null:
        return
    var has_blank := blank_count > 0
    record_scout_btn.text = "📋 记录为证据（剩余%d张）" % blank_count
    record_scout_btn.disabled = not has_blank
    record_scout_btn.tooltip_text = "" if has_blank else "没有空白记录卡"
    if _record_scout_blackmail_btn:
        var has_subject := _scout_subject_npc_id.strip_edges() != ""
        _record_scout_blackmail_btn.text = "🔪 记录为黑料（剩余%d张）" % blank_count
        _record_scout_blackmail_btn.disabled = (not has_blank) or (not has_subject)
        if not has_blank:
            _record_scout_blackmail_btn.tooltip_text = "没有空白记录卡"
        elif not has_subject:
            _record_scout_blackmail_btn.tooltip_text = "这条侦察没有明确的当事人，无法记为黑料"
        else:
            _record_scout_blackmail_btn.tooltip_text = ""
    if _skip_scout_btn:
        _skip_scout_btn.disabled = false
        _skip_scout_btn.text = "跳过"


func _on_record_scout_as_evidence() -> void:
    if record_scout_btn == null:
        return
    record_scout_btn.disabled = true
    record_scout_btn.text = "记录中..."
    if _record_scout_blackmail_btn:
        _record_scout_blackmail_btn.disabled = true
    if _skip_scout_btn:
        _skip_scout_btn.disabled = true
    NetworkManager.record_scout_evidence_v2("evidence", _scout_evidence_tag)


func _on_record_scout_as_blackmail() -> void:
    if _record_scout_blackmail_btn == null:
        return
    _record_scout_blackmail_btn.disabled = true
    _record_scout_blackmail_btn.text = "记录中..."
    if record_scout_btn:
        record_scout_btn.disabled = true
    if _skip_scout_btn:
        _skip_scout_btn.disabled = true
    NetworkManager.record_scout_evidence_v2("blackmail", _scout_evidence_tag)


func _on_skip_scout() -> void:
    # 跳过记录：本地直接隐藏小助理记录按钮组，不发后端消息。
    _set_scout_record_buttons_visible(false)
    _scout_evidence_tag = ""
    _scout_subject_npc_id = ""


func _on_record_scout_result(data: Dictionary) -> void:
    var success: bool = data.get("success", false)
    var remaining: int = int(data.get("remaining_blank", 0))
    var record_type: String = str(data.get("record_type", "evidence")).strip_edges().to_lower()
    var can_record_event_base: bool = bool(_current_result.get("can_use_record_card", false))
    _current_result["blank_cards_count"] = remaining
    _current_result["can_use_record_card"] = can_record_event_base and remaining > 0
    if success:
        if record_type == "blackmail":
            if _record_scout_blackmail_btn:
                _record_scout_blackmail_btn.text = "✅ 已记录为黑料（剩余%d张）" % remaining
            if record_scout_btn:
                record_scout_btn.disabled = true
            if _skip_scout_btn:
                _skip_scout_btn.disabled = true
        else:
            if record_scout_btn:
                record_scout_btn.text = "✅ 已记录为证据（剩余%d张）" % remaining
            if _record_scout_blackmail_btn:
                _record_scout_blackmail_btn.disabled = true
            if _skip_scout_btn:
                _skip_scout_btn.disabled = true
        _refresh_scout_record_buttons(remaining)
        if _current_result.get("can_use_record_card", false) and remaining > 0:
            record_card_section.visible = true
            record_evidence_btn.text = "📋 记录为证据（剩余%d张）" % remaining
            record_blackmail_btn.text = "🔪 记录为黑料（剩余%d张）" % remaining
            record_evidence_btn.disabled = false
            record_blackmail_btn.disabled = false
            skip_record_btn.visible = true
            skip_record_btn.disabled = false
            skip_record_btn.text = "跳过"
        else:
            record_card_section.visible = false
            record_evidence_btn.disabled = true
            record_blackmail_btn.disabled = true
            skip_record_btn.visible = false
            skip_record_btn.disabled = true
        # 空白卡耗尽时，强制关闭本小时所有“可记录”入口，避免前端残留可点状态。
        if remaining <= 0:
            _current_result["can_use_record_card"] = false
            record_card_section.visible = false
            record_evidence_btn.disabled = true
            record_blackmail_btn.disabled = true
            skip_record_btn.visible = false
            skip_record_btn.disabled = true
            _set_scout_record_buttons_visible(false)
            _scout_evidence_tag = ""
            _scout_subject_npc_id = ""
    else:
        var msg: String = str(data.get("message", "记录失败"))
        if record_type == "blackmail" and _record_scout_blackmail_btn:
            _record_scout_blackmail_btn.text = "❌ %s" % msg
            _record_scout_blackmail_btn.disabled = true
        else:
            if record_scout_btn:
                record_scout_btn.text = "❌ %s" % msg
                record_scout_btn.disabled = true
    _sync_evidence_count(data)


func _on_blackmail_toggle() -> void:
    if blackmail_card_list.visible:
        blackmail_card_list.visible = false
        blackmail_target_list.visible = false
        return

    # 显示可用的已记录卡片
    for child in blackmail_card_list.get_children():
        child.queue_free()
    blackmail_card_list.visible = true
    blackmail_target_list.visible = false

    var recorded = _current_result.get("recorded_cards", [])
    for card in recorded:
        if str(card.get("record_type", "")).strip_edges().to_lower() != "blackmail":
            continue
        var btn := Button.new()
        var subject := str(card.get("subject_npc_name", "某同事")).strip_edges()
        if subject == "":
            subject = "某同事"
        btn.text = "关于%s的黑料" % subject
        btn.custom_minimum_size = Vector2(0, 32)
        _style_action_button(btn, Color(0.95, 0.58, 0.70), 34)
        btn.pressed.connect(_on_blackmail_card_selected.bind(card.get("id", "")))
        blackmail_card_list.add_child(btn)


func _on_blackmail_card_selected(card_id: String) -> void:
    _selected_blackmail_card_id = card_id
    blackmail_card_list.visible = false

    # 显示目标NPC列表
    for child in blackmail_target_list.get_children():
        child.queue_free()
    blackmail_target_list.visible = true

    var reactions = _current_result.get("reactions", {})
    for npc_name in reactions:
        var npc_id := _name_to_id(npc_name)
        if npc_id == "boss":
            continue
        var btn := Button.new()
        btn.text = "威胁 %s" % npc_name
        btn.custom_minimum_size = Vector2(0, 35)
        _style_action_button(btn, Color(0.95, 0.58, 0.70), 36)
        btn.pressed.connect(_on_blackmail_target.bind(npc_id, npc_name))
        blackmail_target_list.add_child(btn)


func _on_blackmail_target(npc_id: String, npc_name: String) -> void:
    blackmail_btn.disabled = true
    blackmail_btn.text = "正在威胁%s..." % npc_name
    for child in blackmail_target_list.get_children():
        if child is Button:
            child.disabled = true
    NetworkManager.use_blackmail(_selected_blackmail_card_id, npc_id)


func _on_blackmail_result(data: Dictionary) -> void:
    blackmail_target_list.visible = false
    blackmail_result_label.visible = true
    blackmail_result_label.bbcode_enabled = true

    var effect_text = data.get("effect_text", "")
    var dialogue = data.get("dialogue", "")
    var msg = data.get("message", "")

    blackmail_btn.text = "✅ 已使用"
    blackmail_btn.disabled = true
    blackmail_result_label.text = "%s\n\n[b]%s[/b]\n%s" % [msg, effect_text, dialogue]


func _clear_blame_targets() -> void:
    for child in blame_target_list.get_children():
        child.queue_free()
    blame_target_list.visible = false


func _name_to_id(npc_name: String) -> String:
    """NPC名字反查ID（来自后端返回的动态映射）"""
    var mapping: Dictionary = _current_result.get("npc_name_id_map", {})
    var key := npc_name.strip_edges()
    if mapping.has(key):
        return str(mapping.get(key, key))
    return key


func _on_record_used(data: Dictionary) -> void:
    """记录卡使用结果"""
    var record_result = data.get("record_result", {})
    var remaining: int = int(data.get("remaining_blank", _current_result.get("blank_cards_count", 0)))
    _current_result["blank_cards_count"] = remaining
    if remaining <= 0:
        _current_result["can_use_record_card"] = false
    _refresh_scout_record_buttons(remaining)
    if remaining <= 0 and record_scout_btn:
        record_scout_btn.disabled = true
    if remaining <= 0 and _record_scout_blackmail_btn:
        _record_scout_blackmail_btn.disabled = true

    if record_result.get("success", false):
        record_evidence_btn.text = "✅ 已记录！"
        record_blackmail_btn.text = "✅ 已记录！"
        record_evidence_btn.disabled = true
        record_blackmail_btn.disabled = true
        skip_record_btn.disabled = true
    else:
        var fail_msg := "❌ %s" % record_result.get("message", "记录失败")
        record_evidence_btn.text = fail_msg
        record_blackmail_btn.text = fail_msg
        record_evidence_btn.disabled = true
        record_blackmail_btn.disabled = true
        skip_record_btn.disabled = true

    _sync_evidence_count(data)


func _on_hour_advanced(_data: Dictionary) -> void:
    """小时推进后隐藏自己（由GameUI处理下一步）"""
    visible = false






func _on_continue() -> void:
    """继续（跳过记录卡的等价操作）"""
    request_next_task.emit()
    visible = false


func _sync_evidence_count(data: Dictionary) -> void:
    var valid_count := -1
    var recorded_count := -1
    if data.has("valid_evidence_count"):
        valid_count = int(data.get("valid_evidence_count", 0))
    elif data.has("evidence_count"):
        valid_count = int(data.get("evidence_count", 0))
    elif data.get("record_result", {}).has("valid_evidence_count"):
        valid_count = int(data.get("record_result", {}).get("valid_evidence_count", 0))
    elif data.get("record_result", {}).has("evidence_count"):
        valid_count = int(data.get("record_result", {}).get("evidence_count", 0))

    if data.has("recorded_cards_count"):
        recorded_count = int(data.get("recorded_cards_count", -1))
    elif data.get("record_result", {}).has("recorded_cards_count"):
        recorded_count = int(data.get("record_result", {}).get("recorded_cards_count", -1))

    if valid_count >= 0:
        var game_ui = _get_game_ui()
        if game_ui and game_ui.has_method("update_evidence_metrics"):
            game_ui.update_evidence_metrics(valid_count, recorded_count)
        elif game_ui and game_ui.has_method("update_evidence_count"):
            game_ui.update_evidence_count(valid_count)


func _truncate_ui_text(text: String, max_chars: int) -> String:
    var trimmed := text.strip_edges()
    if max_chars <= 0:
        return trimmed
    if trimmed.length() <= max_chars:
        return trimmed
    return trimmed.substr(0, max_chars) + "..."


func _get_game_ui() -> Node:
    var node: Node = self
    while node:
        if (node.has_method("update_evidence_metrics") or node.has_method("update_evidence_count")) and node.has_method("is_action_blocked_by_pause"):
            return node
        node = node.get_parent()
    return null


func _get_social_energy_left() -> int:
    return int(_current_event.get("social_energy_left", 1))


func _needs_social_energy_for_current_work_mode() -> bool:
    if _card_mode != "work_mode_choice":
        return false
    if _work_mode_blackmail_card_pick:
        return _work_mode_submit_mode == "blackmail_broadcast" or _work_mode_submit_mode == "report_boss"
    return _selected_work_mode == "blackmail_broadcast" or _selected_work_mode == "report_boss"


func _show_social_energy_insufficient_popup() -> void:
    var script = load("res://scripts/helper_popup.gd")
    if script == null:
        return
    var popup = script.new()
    get_tree().root.add_child(popup)
    popup.setup(["社交精力值不足，无法传播黑料。"])


func open_scout_from_bottom() -> void:
    if not visible:
        return
    if not result_panel.visible:
        var game_ui = _get_game_ui()
        if game_ui and game_ui.has_node("WorkingUI/Margin/VBox/MainContent/EventContentPanel/NotificationArea"):
            var notice = game_ui.get_node("WorkingUI/Margin/VBox/MainContent/EventContentPanel/NotificationArea")
            notice.text = "[color=yellow]请先出牌进入结算后再使用侦察。[/color]"
        return
    if scout_section.visible:
        _on_scout_toggle()
    else:
        _on_scout_toggle()


func quick_continue_from_bottom() -> void:
    if not visible or not result_panel.visible:
        return
    if record_card_section.visible:
        _on_skip_record()
        return
    if continue_btn.visible:
        _on_continue()
    else:
        _on_continue()
