from backend.constants import *
from backend.enums import *
from backend.evidence_converter import EvidenceConverter
from backend.game_state import GameState
from backend.state_manager import StateManager
from backend.task_system import TaskSystem

pool, evidence_ids = TaskSystem.generate_daily_task_pool(day=1)
assert len(pool) == 12, f"任务池应有12个任务，实际{len(pool)}"
print("✅ 任务池数量正确：12个")

assert 2 <= len(evidence_ids) <= 3, f"证据任务应2-3个，实际{len(evidence_ids)}"
print(f"✅ 证据任务数量正确：{len(evidence_ids)}个")

evidence_tasks_in_pool = [t for t in pool if t.evidence_tag is not None]
assert len(evidence_tasks_in_pool) == len(evidence_ids)
for t in evidence_tasks_in_pool:
    assert t.evidence_tag.startswith("evidence_day1_")
    assert t.evidence_type is not None
print("✅ 证据标签分配正确")

room_counts: dict[str, int] = {}
for task in pool:
    r = task.room.value
    room_counts[r] = room_counts.get(r, 0) + 1
for room, count in room_counts.items():
    assert count <= 4, f"房间{room}有{count}个任务，超过上限4个"
print(f"✅ 房间分布均匀：{room_counts}")

pool2, _ = TaskSystem.generate_daily_task_pool(day=1)
pool_ids_1 = set(t.id for t in pool)
pool_ids_2 = set(t.id for t in pool2)
print(f"✅ 随机性检查：两次生成{'不同' if pool_ids_1 != pool_ids_2 else '相同（极小概率）'}")

state = GameState.new_game()
sm = StateManager(state)

TaskSystem.assign_all_npcs_tasks(state.npcs)
for npc_id, npc in state.npcs.items():
    assert len(npc.selected_tasks) == 5, f"{npc.name}应有5个任务"
    assert npc.current_task_index == 0
    assert npc.current_room == npc.selected_tasks[0].room
print("✅ NPC任务分配正确：每人5个任务")

dazhuang_rooms = [t.room.value for t in state.npcs["dazhuang"].selected_tasks]
print(f"  大壮房间分布：{dazhuang_rooms}（应偏向warehouse）")

state2 = GameState.new_game()
sm2 = StateManager(state2)
sm2.setup_daily_tasks()

pool = state2.daily.task_pool
task_ids = [t.id for t in pool[:5]]

ok, msg = sm2.player_select_tasks(task_ids)
assert ok, f"合法选择应通过，但报错：{msg}"
assert len(state2.player.selected_tasks) == 5
print("✅ 玩家选择5个任务：通过")

state3 = GameState.new_game()
sm3 = StateManager(state3)
sm3.setup_daily_tasks()
pool3 = state3.daily.task_pool
task_ids_over = [t.id for t in pool3[:6]]
ok3, msg3 = sm3.player_select_tasks(task_ids_over)
assert not ok3, "超过当前5任务上限应失败"
print(f"✅ 超时选择被拒绝：{msg3}")

task_ids_dup = [pool3[0].id, pool3[0].id, pool3[1].id]
ok4, msg4 = sm3.player_select_tasks(task_ids_dup)
assert not ok4, "重复选择应失败"
print(f"✅ 重复选择被拒绝：{msg4}")

ok5, msg5 = sm3.player_select_tasks([])
assert not ok5, "空选择应失败"
print(f"✅ 空选择被拒绝：{msg5}")

ctx = EvidenceConverter.to_ai_prompt_context(
    evidence_type=EvidenceType.PRODUCT_FAKE,
    room=Room.WAREHOUSE,
    task_name="查看罐头库存",
    npc_names=["老王", "大壮"],
    npc_personalities=["摸鱼大师", "干饭王"],
)
assert ctx["is_evidence_event"] is True
assert ctx["evidence_category"] == "产品造假"
assert ctx["scene_location"] == "仓库"
assert len(ctx["evidence_keywords"]) >= 2
assert "evidence_" not in str(ctx)
print("✅ 证据转换上下文正确，不含标签")

prompt = EvidenceConverter.build_evidence_prompt_block(
    evidence_type=EvidenceType.CORRUPTION,
    room=Room.MEETING,
    task_name="参加经理会议",
    npc_names=["小李"],
    npc_personalities=["狗腿子"],
)
assert "高层腐败" in prompt
assert "evidence_" not in prompt
assert "小李" in prompt
print("✅ 证据prompt文本块正确")

normal_prompt = EvidenceConverter.build_normal_event_prompt_block(
    room=Room.PANTRY,
    task_name="加热午餐",
)
assert "茶水间" in normal_prompt
assert "evidence" not in normal_prompt.lower()
print("✅ 普通事件prompt正确")

state_full = GameState.new_game()
sm_full = StateManager(state_full)

sm_full.setup_daily_tasks()
assert len(state_full.daily.task_pool) == 12
assert len(state_full.daily.evidence_task_ids) >= 2
print("✅ 每日任务设置完成")

player_picks = [t.id for t in state_full.daily.task_pool[:5]]
ok, msg = sm_full.player_select_tasks(player_picks)
assert ok
print("✅ 玩家选择5个任务")

ctx = sm_full.get_current_task_prompt_context()
assert ctx is not None
assert "scene_location" in ctx
assert "evidence_" not in str(ctx)
print(f"✅ 当前任务prompt上下文：{ctx['scene_location']} - {ctx['task_description']}")

sm_full.advance_task()
assert state_full.player.current_task_index == 1
assert state_full.current_hour == 1
print("✅ 任务推进正确")

frontend_pool = sm_full.get_task_pool_for_frontend()
assert len(frontend_pool) == 12
for item in frontend_pool:
    assert "evidence_tag" not in item
    assert "evidence_type" not in item
print("✅ 前端任务池数据安全")

print("\n🎉 模块2全部测试通过！")
