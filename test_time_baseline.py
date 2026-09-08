import random

from backend.constants import DAILY_ACTION_POINTS, TOTAL_DAYS
from backend.game_state import GameState
from backend.movement_system import MovementSystem
from backend.state_manager import StateManager
from backend.task_system import TaskSystem


random.seed(12345)

assert TOTAL_DAYS == 5, f"TOTAL_DAYS 应为 5，实际 {TOTAL_DAYS}"
assert DAILY_ACTION_POINTS == 5, f"DAILY_ACTION_POINTS 应为 5，实际 {DAILY_ACTION_POINTS}"

state = GameState.new_game()
assert state.player.action_points == 5, f"新游戏玩家行动点应为 5，实际 {state.player.action_points}"

sample_npc = next(iter(state.npcs.values()))
npc_tasks = TaskSystem.assign_npc_tasks(sample_npc)
assert len(npc_tasks) == 5, f"NPC 每日任务应为 5 个，实际 {len(npc_tasks)}"

sm = StateManager(GameState.new_game())
sm.setup_daily_tasks()
task_pool = sm.state.daily.task_pool

valid_ids = [task.id for task in task_pool[:5]]
ok, msg, selected = TaskSystem.validate_player_selection(
    valid_ids,
    task_pool,
    DAILY_ACTION_POINTS,
)
assert ok, f"恰好 5 个任务应通过，错误：{msg}"
assert len(selected) == 5, f"合法选择应返回 5 个任务，实际 {len(selected)}"

for invalid_count in (4, 6):
    invalid_ids = [task.id for task in task_pool[:invalid_count]]
    ok, msg, selected = TaskSystem.validate_player_selection(
        invalid_ids,
        task_pool,
        DAILY_ACTION_POINTS,
    )
    assert not ok, f"{invalid_count} 个任务应失败"
    assert selected == [], f"{invalid_count} 个任务失败时不应返回已选任务"

plan = MovementSystem.generate_boss_hourly_plan(sm.state.boss, day=1)
assert len(plan) == 5, f"经理默认日计划应为 5 段，实际 {len(plan)}"

state2 = GameState.new_game()
sm2 = StateManager(state2)
sm2.setup_daily_tasks()
assert len(state2.daily.boss_hourly_plan) == 5, (
    f"setup_daily_tasks 后 boss_hourly_plan 应为 5 段，实际 {len(state2.daily.boss_hourly_plan)}"
)

print("✅ test_time_baseline passed")
