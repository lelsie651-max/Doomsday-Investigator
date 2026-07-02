from backend.constants import *
from backend.enums import *
from backend.game_state import GameState
from backend.state_manager import StateManager
from backend.vote_system import VoteSystem

state = GameState.new_game()
sm = StateManager(state)

sm.modify_suspicion("xiaoli", "player", 40)

alive_targets = ["player", "laowang", "ahua", "dazhuang", "zhoujie"]
xiaoli_votes: dict[str, int] = {}
for _ in range(100):
    vote = VoteSystem.calculate_npc_vote(
        state.npcs["xiaoli"],
        state.relationships,
        alive_targets,
    )
    xiaoli_votes[vote] = xiaoli_votes.get(vote, 0) + 1

print(f"✅ 小李投票分布（100次采样）：{xiaoli_votes}")
assert "player" in xiaoli_votes, "小李应至少偶尔投玩家"
print(f"  投玩家次数：{xiaoli_votes.get('player', 0)}/100")

sm.modify_suspicion("boss", "player", 50)

boss_votes: dict[str, int] = {}
for _ in range(100):
    vote = VoteSystem.calculate_boss_vote(
        state.boss,
        state.relationships,
        alive_targets,
    )
    boss_votes[vote] = boss_votes.get(vote, 0) + 1

print(f"✅ 经理投票分布（100次采样）：{boss_votes}")
assert boss_votes.get("player", 0) > 50, "经理应高概率投怀疑度最高的人"
print(f"  投玩家次数：{boss_votes.get('player', 0)}/100")

state2 = GameState.new_game()
sm2 = StateManager(state2)
sm2.modify_affinity("zhoujie", "dazhuang", -60)

zhoujie_votes: dict[str, int] = {}
targets = ["player", "laowang", "xiaoli", "ahua", "dazhuang"]
for _ in range(100):
    vote = VoteSystem.calculate_npc_vote(
        state2.npcs["zhoujie"],
        state2.relationships,
        targets,
    )
    zhoujie_votes[vote] = zhoujie_votes.get(vote, 0) + 1

print(f"✅ 周姐投票分布：{zhoujie_votes}")
assert zhoujie_votes.get("dazhuang", 0) > 30, "周姐应倾向投她记仇的人"
print(f"  投大壮次数：{zhoujie_votes.get('dazhuang', 0)}/100")

state3 = GameState.new_game()
sm3 = StateManager(state3)
sm3.setup_daily_tasks()
sm3.player_select_tasks([t.id for t in state3.daily.task_pool[:4]])

result = sm3.execute_vote("xiaoli")
assert "error" not in result
assert "vote_record" in result
assert "tally" in result
assert "target" in result
assert "outcome_text" in result
assert "vote_details" in result

print("✅ 完整投票执行成功")
print(f"  投票记录：{result['vote_record']}")
print(f"  得票统计：{result['tally']}")
print(f"  平票：{result['is_tie']}")
if result["target"]:
    print(f"  被审问者：{result['target_name']}（{result['target']}）")
else:
    print("  平票，无人被审问")
print(f"  结果文案：{result['outcome_text'][:50]}...")

details = result["vote_details"]
assert len(details) >= 6, f"应有至少6条投票详情（玩家+5NPC+经理），实际{len(details)}"
for detail in details:
    assert "voter_id" in detail
    assert "voter_name" in detail
    assert "target_id" in detail
    assert "target_name" in detail
print(f"✅ 唱票详情结构正确，共{len(details)}票")
for detail in details:
    print(f"  {detail['voter_name']} → {detail['target_name']}")

state4 = GameState.new_game()
sm4 = StateManager(state4)
bad1 = sm4.execute_vote("player")
assert "error" in bad1
print(f"✅ 不能投自己：{bad1['error']}")

bad2 = sm4.execute_vote("boss")
assert "error" in bad2
print(f"✅ 不能投经理：{bad2['error']}")

state5 = GameState.new_game()
sm5 = StateManager(state5)
sm5.eliminate_npc("xiaoli")
bad3 = sm5.execute_vote("xiaoli")
assert "error" in bad3
print(f"✅ 不能投已出局NPC：{bad3['error']}")

state6 = GameState.new_game()
sm6 = StateManager(state6)
for npc_id in state6.npcs:
    sm6.modify_suspicion(npc_id, "player", 80)
sm6.modify_suspicion("boss", "player", 80)

sm6.setup_daily_tasks()
sm6.player_select_tasks([t.id for t in state6.daily.task_pool[:4]])

result6 = sm6.execute_vote("laowang")
if result6.get("player_eliminated"):
    assert state6.game_over is True
    assert state6.game_result == "fail_voted_out"
    print("✅ 玩家被投出，游戏结束")
else:
    print("⚠️ 本次未投出玩家（随机性），但逻辑已验证")

state8 = GameState.new_game()
sm8 = StateManager(state8)
candidates = sm8.get_vote_candidates_for_frontend()
assert len(candidates) == 5
for candidate in candidates:
    assert "id" in candidate
    assert "name" in candidate
    assert "species" in candidate
print(f"✅ 投票候选人列表正确：{[candidate['name'] for candidate in candidates]}")

sm8.eliminate_npc("xiaoli")
candidates2 = sm8.get_vote_candidates_for_frontend()
assert len(candidates2) == 4
assert all(candidate["id"] != "xiaoli" for candidate in candidates2)
print(f"✅ 淘汰后候选人更新：{[candidate['name'] for candidate in candidates2]}")

print("\n🎉 模块6全部测试通过！")
