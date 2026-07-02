from backend.constants import *
from backend.enums import *
from backend.game_state import GameState
from backend.movement_system import MovementSystem
from backend.room_system import RoomSystem
from backend.state_manager import StateManager


assert Room.BOSS_OFFICE.value == "boss_office"
assert Room.BOSS_OFFICE not in ACCESSIBLE_ROOMS
assert BOSS_SHADY_ROOM == Room.BOSS_OFFICE
print("✅ 经理办公室枚举和常量正确")

state = GameState.new_game()
assert state.boss.current_room == Room.BOSS_OFFICE
print("✅ 经理初始位置为经理办公室")

plan = MovementSystem.generate_boss_hourly_plan(state.boss, day=1)
assert len(plan) == 8, f"行为计划应有8小时，实际{len(plan)}"
for b in plan:
    assert isinstance(b, BossBehavior)
pua_count = plan.count(BossBehavior.PUA)
assert pua_count <= 1, f"PUA应最多1次，实际{pua_count}次"
print(f"✅ 经理行为计划正确：{[b.value for b in plan]}，PUA次数：{pua_count}")

from backend.models import BossState

boss = BossState()
alive_ids = ["player", "laowang", "xiaoli"]
result = MovementSystem.execute_boss_hour(boss, BossBehavior.PATROL, alive_ids)
assert result["behavior"] == "patrol"
assert result["room"] in [r.value for r in BOSS_PATROL_ROOMS]
assert result["alert_hint"] is not None
assert boss.current_behavior == BossBehavior.PATROL
print(f"✅ 巡视执行正确，去了{result['room']}，提示：{result['alert_hint']}")

boss2 = BossState()
result2 = MovementSystem.execute_boss_hour(boss2, BossBehavior.PUA, alive_ids)
assert result2["behavior"] == "pua"
assert result2["room"] == "meeting"
assert result2["target_npc"] in alive_ids
print(f"✅ PUA执行正确，目标：{result2['target_npc']}")

boss3 = BossState()
result3 = MovementSystem.execute_boss_hour(boss3, BossBehavior.SHADY_BUSINESS, alive_ids)
assert result3["behavior"] == "shady"
assert result3["room"] == "boss_office"
assert result3["generates_evidence"] is True
assert boss3.current_room == Room.BOSS_OFFICE
print("✅ 关门干坏事执行正确，在经理办公室")

state2 = GameState.new_game()
sm = StateManager(state2)
sm.setup_daily_tasks()

pool = state2.daily.task_pool
player_picks = [t.id for t in pool[:6]]
sm.player_select_tasks(player_picks)

coworkers = sm.get_player_coworkers()
assert "room" in coworkers
assert "alone" in coworkers
assert "npc_ids" in coworkers
assert "boss_present" in coworkers
assert "headcount" in coworkers
print(
    f"✅ 玩家在{coworkers['room']}，同房间人数{coworkers['headcount']}，"
    f"{'独处' if coworkers['alone'] else '有同事'}，"
    f"经理{'在' if coworkers['boss_present'] else '不在'}"
)

snapshot = sm.get_room_snapshot()
assert "office" in snapshot
assert "meeting" in snapshot
assert "boss_office" in snapshot
for room_key, info in snapshot.items():
    assert "player_present" in info
    assert "npcs" in info
    assert "boss_present" in info
    assert "total_count" in info
print(f"✅ 房间快照结构正确，共{len(snapshot)}个房间")

for room_key, info in snapshot.items():
    if info["total_count"] > 0:
        occupants = []
        if info["player_present"]:
            occupants.append("玩家")
        for detail in info["npc_details"]:
            occupants.append(detail["name"])
        if info["boss_present"]:
            occupants.append("鲍斯")
        print(f"  {room_key}: {', '.join(occupants)}")

result = sm.advance_hour()
assert result["hour"] == 1
assert result["day_ended"] is False
assert "player_room" in result
assert "boss_action" in result
assert "player_coworkers" in result
print(f"✅ 小时推进正确，当前第{result['hour']}小时")

for _ in range(10):
    hour_result = sm.advance_hour()
    if hour_result["day_ended"]:
        print(f"✅ 第{hour_result['hour']}小时，一天结束")
        break

state3 = GameState.new_game()
sm3 = StateManager(state3)
sm3.setup_daily_tasks()
pool3 = state3.daily.task_pool
sm3.player_select_tasks([t.id for t in pool3[:6]])

original_room = state3.npcs["laowang"].current_room.value
pua_result = MovementSystem.handle_pua_interruption("laowang", state3.player, state3.npcs)
assert pua_result["target_id"] == "laowang"
assert pua_result["target_name"] == "老王"
assert pua_result["original_room"] == original_room
assert state3.npcs["laowang"].current_room == Room.MEETING
print(f"✅ PUA打断正确：老王从{original_room}被拉到meeting")

original_player_room = state3.player.current_room.value
pua_player = MovementSystem.handle_pua_interruption("player", state3.player, state3.npcs)
assert pua_player["target_name"] == "你"
assert state3.player.current_room == Room.MEETING
print(f"✅ 玩家被PUA：从{original_player_room}被拉到meeting")

state4 = GameState.new_game()
sm4 = StateManager(state4)
sm4.setup_daily_tasks()
sm4.player_select_tasks([t.id for t in state4.daily.task_pool[:4]])

positions = sm4.get_all_positions()
assert "player" in positions
assert "boss" in positions
assert "laowang" in positions
valid_rooms = [r.value for r in Room]
for char_id, room_val in positions.items():
    assert room_val in valid_rooms, f"{char_id}的位置{room_val}不是有效房间"
print(f"✅ 位置数据正确：{positions}")

plans_by_day = {}
for day in range(1, 6):
    patrol_count = 0
    sample_size = 100
    for _ in range(sample_size):
        temp_boss = BossState()
        day_plan = MovementSystem.generate_boss_hourly_plan(temp_boss, day)
        patrol_count += day_plan.count(BossBehavior.PATROL)
    avg_patrol = patrol_count / sample_size
    plans_by_day[day] = avg_patrol
    print(f"  第{day}天 平均巡视次数：{avg_patrol:.1f}/8小时")

assert plans_by_day[5] > plans_by_day[1], "第5天巡视应多于第1天"
print("✅ 经理行为权重随天数递增正确")

print("\n🎉 模块3全部测试通过！")
