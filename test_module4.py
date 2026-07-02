from backend.constants import *
from backend.enums import *
from backend.event_system import EventSystem
from backend.event_templates import EVIDENCE_HINT_TEXTS, EVENT_TEMPLATES, RESULT_TEMPLATES
from backend.game_state import GameState
from backend.state_manager import StateManager

assert len(EVENT_TEMPLATES) == 10, f"应有10个事件模板，实际{len(EVENT_TEMPLATES)}"
rooms_covered = set(event["room"] for event in EVENT_TEMPLATES)
assert rooms_covered == {"office", "meeting", "warehouse", "pantry", "reception"}
for room_val in rooms_covered:
    count = len([event for event in EVENT_TEMPLATES if event["room"] == room_val])
    assert count == 2, f"房间{room_val}应有2个事件，实际{count}"
print("✅ 10个事件模板，每房间2个")

assert "steady" in RESULT_TEMPLATES
assert "contrast" in RESULT_TEMPLATES
assert "crazy" in RESULT_TEMPLATES
for combo_type, templates in RESULT_TEMPLATES.items():
    assert len(templates) >= 3, f"{combo_type}类型应至少3个模板"
    for template in templates:
        assert "text" in template
        assert "affinity_delta" in template
        assert "suspicion_delta" in template
        assert "gold_delta" in template
print("✅ 结果模板3种类型，各至少3个")

for evidence_type in [
    "product_fake",
    "finance_fake",
    "employee_abuse",
    "safety_hazard",
    "corruption",
]:
    assert evidence_type in EVIDENCE_HINT_TEXTS, f"缺少{evidence_type}的线索文本"
    assert len(EVIDENCE_HINT_TEXTS[evidence_type]) >= 2
print("✅ 5种证据类型线索文本完整")

emotions, actions = EventSystem.draw_cards()
assert len(emotions) == 5
assert len(actions) == 5
emotion_ids = [card["id"] for card in emotions]
action_ids = [card["id"] for card in actions]
assert len(set(emotion_ids)) == 5
assert len(set(action_ids)) == 5
for card in emotions:
    assert "id" in card and "name" in card and "is_normal" in card
for card in actions:
    assert "id" in card and "name" in card and "is_normal" in card
print("✅ 抽卡正确：5情绪+5行动，无重复")

assert EventSystem.classify_combination("E01", "A01") == "steady"
assert EventSystem.classify_combination("E01", "A05") == "contrast"
assert EventSystem.classify_combination("E05", "A01") == "contrast"
assert EventSystem.classify_combination("E05", "A05") == "crazy"
print("✅ 组合分类正确：steady/contrast/crazy")

event1 = EventSystem.select_event(Room.OFFICE, [])
assert event1 is not None
assert event1["room"] == "office"

event2 = EventSystem.select_event(Room.OFFICE, [event1["id"]])
assert event2 is not None
assert event2["id"] != event1["id"]
print("✅ 事件选取正确，避免重复")

event3 = EventSystem.select_event(Room.OFFICE, [event1["id"], event2["id"]])
assert event3 is not None
print("✅ 所有事件耗尽后允许重复")

result = EventSystem.resolve_event("E05", "A08")
assert result["combination_type"] == "crazy"
assert "result_text" in result and len(result["result_text"]) > 0
assert "affinity_delta" in result
assert "suspicion_delta" in result
print(
    f"✅ 事件结算正确，类型={result['combination_type']}，"
    f"好感{result['affinity_delta']:+d}，怀疑{result['suspicion_delta']:+d}"
)

state = GameState.new_game()
sm = StateManager(state)
sm.setup_daily_tasks()
pool = state.daily.task_pool
sm.player_select_tasks([t.id for t in pool[:6]])

event_display = sm.trigger_event()
assert event_display is not None
assert "event_name" in event_display
assert len(event_display["emotion_cards"]) == 5
assert len(event_display["action_cards"]) == 5
print(f"✅ 事件触发：{event_display['event_name']}")
print(f"  情绪卡：{[c['name'] for c in event_display['emotion_cards']]}")
print(f"  行动卡：{[c['name'] for c in event_display['action_cards']]}")

e_id = event_display["emotion_cards"][0]["id"]
a_id = event_display["action_cards"][0]["id"]
result = sm.resolve_player_cards(e_id, a_id)
assert "error" not in result
assert "result_text" in result
assert "combination_type" in result
print(f"✅ 卡牌结算：{result['emotion_name']} + {result['action_name']}")
print(f"  类型：{result['combination_type']}")
print(f"  结果：{result['result_text'][:50]}...")

state2 = GameState.new_game()
sm2 = StateManager(state2)
sm2.setup_daily_tasks()
sm2.player_select_tasks([t.id for t in state2.daily.task_pool[:4]])
sm2.trigger_event()

bad_result = sm2.resolve_player_cards("E99", "A99")
assert "error" in bad_result
print(f"✅ 非法卡牌被拒绝：{bad_result['error']}")

state3 = GameState.new_game()
sm3 = StateManager(state3)
sm3.setup_daily_tasks()
sm3.player_select_tasks([t.id for t in state3.daily.task_pool[:4]])

evt = sm3.trigger_event()
e_id = evt["emotion_cards"][0]["id"]
a_id = evt["action_cards"][0]["id"]
sm3.resolve_player_cards(e_id, a_id)

rc_result = sm3.use_record_card_on_event("rc_001")
assert rc_result["success"] is True
assert len(rc_result["message"]) > 0
card = None
for c in state3.player.record_cards:
    if c.id == "rc_001":
        card = c
        break
assert card is not None
assert card.status == RecordCardStatus.RECORDED
print(f"✅ 记录卡使用成功：{rc_result['message'][:40]}...")

rc_result2 = sm3.use_record_card_on_event("rc_001")
assert rc_result2["success"] is False
print(f"✅ 重复使用被拒绝：{rc_result2['message']}")

evidence_task = None
for task in state3.daily.task_pool:
    if task.evidence_tag is not None:
        evidence_task = task
        break

if evidence_task:
    display = EventSystem.build_event_display(
        EVENT_TEMPLATES[0],
        [{"id": "E01", "name": "测试", "tone": "", "is_normal": True}] * 5,
        [{"id": "A01", "name": "测试", "effect": "", "is_normal": True}] * 5,
        is_evidence_task=True,
        evidence_type_value=evidence_task.evidence_type.value,
    )
    assert display["has_evidence_hint"] is True
    assert len(display["evidence_hint"]) > 0
    assert "evidence_" not in display["evidence_hint"]
    print(f"✅ 证据线索附加正确：{display['evidence_hint'][:40]}...")
else:
    print("⚠️ 本次任务池恰好无证据任务，跳过线索测试")

print("\n🎉 模块4全部测试通过！")
