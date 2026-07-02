import asyncio
import random

from backend.enums import *
from backend.game_controller import GameController


async def main():
    gc = GameController()
    init = gc.new_game()
    assert init["phase"] == "task_selection"
    assert init["day"] == 1
    assert init["game_over"] is False
    print("✅ 新游戏创建成功")

    status = gc.get_game_status()
    assert status["day"] == 1
    assert len(status["alive_npcs"]) == 5
    assert status["player_gold"] == 50
    assert status["player_battery"] == 100
    print(f"✅ 游戏状态：第{status['day']}天，{len(status['alive_npcs'])}个NPC存活")

    print("\n" + "=" * 60)
    print("开始完整游戏模拟")
    print("=" * 60)

    gc2 = GameController()
    gc2.new_game()

    game_over = False
    for day in range(1, 6):
        print(f"\n--- 第{day}天 ---")

        task_data = gc2.start_task_selection()
        assert task_data["phase"] == "task_selection"
        assert task_data["day"] == day
        pool = task_data["task_pool"]
        print(f"  任务池：{len(pool)}个任务")

        pick_count = min(6, len(pool))
        picked_ids = [task["id"] for task in pool[:pick_count]]
        work_data = await gc2.submit_task_selection(picked_ids)
        assert "error" not in work_data, f"任务选择失败：{work_data.get('error')}"
        assert work_data["phase"] == "working"
        print(f"  选了{pick_count}个任务，开始工作")

        for hour in range(pick_count):
            event = work_data.get("event") if hour == 0 else hour_data.get("event")

            if event:
                emotion_id = event["emotion_cards"][0]["id"]
                action_id = event["action_cards"][0]["id"]
                card_result = gc2.play_cards(emotion_id, action_id)
                assert "error" not in card_result, f"出牌失败：{card_result.get('error')}"

                combination = card_result["combination_type"]
                hint = "📝" if event.get("has_evidence_hint") else ""
                print(
                    f"  第{hour + 1}小时：{event['event_name']} "
                    f"[{card_result['emotion_name']} + {card_result['action_name']}] "
                    f"→ {combination} {hint}"
                )

                if card_result.get("can_use_record_card") and random.random() < 0.3:
                    blank_card = None
                    for record_card in gc2.state.player.record_cards:
                        if record_card.status.value == "blank":
                            blank_card = record_card
                            break
                    if blank_card:
                        record_result = await gc2.use_record_card(blank_card.id)
                        if record_result["success"]:
                            print("    📼 使用了记录卡！")

            hour_data = await gc2.advance_to_next_hour()
            if hour < pick_count - 1:
                if hour_data.get("boss_alert"):
                    print(f"    ⚠️ {hour_data['boss_alert']}")
                if hour_data.get("pua_interruption"):
                    pua_info = hour_data["pua_interruption"]
                    print(f"    😱 {pua_info['target_name']}被经理拉去PUA了！")

        if hour_data.get("phase") != "voting":
            hour_data = gc2._enter_voting_phase()

        assert hour_data["phase"] == "voting"
        candidates = hour_data["candidates"]
        print(f"  投票候选人：{[candidate['name'] for candidate in candidates]}")

        if candidates:
            target = random.choice(candidates)["id"]
            vote_result = await gc2.submit_vote_v2(target)
            assert "error" not in vote_result, f"投票失败：{vote_result.get('error')}"

            print("  投票结果：", end="")
            for detail in vote_result["vote_details"]:
                print(f"{detail['voter_name']}→{detail['target_name']} ", end="")
            print()
            print(f"  得票：{vote_result['tally']}")
            if vote_result["is_tie"]:
                print("  结果：平票，无人被审问")
            else:
                print(f"  结果：{vote_result['target_name']}被审问")
            print(f"  {vote_result['outcome_text'][:60]}...")

            if vote_result.get("game_over"):
                print(f"\n💀 游戏结束：{gc2.state.game_result}")
                game_over = True
                break

        night_data = gc2.enter_night_phase()
        if night_data.get("phase") == "game_over":
            print(f"\n游戏结束：{night_data['game_result']}")
            print(f"  {night_data['message']}")
            game_over = True
            break

        print(f"  夜间：{night_data['message'][:50]}...")

        if night_data.get("can_proceed_to_next_day"):
            gc2.proceed_to_next_day()

    final_status = gc2.get_game_status()
    print("\n最终状态：")
    print(f"  存活天数：{final_status['day']}")
    print(f"  存活NPC：{final_status['alive_npcs']}")
    print(f"  收集证据：{final_status['evidence_count']}份")
    print(f"  剩余金币：{final_status['player_gold']}")
    print(f"  游戏结果：{final_status['game_result']}")
    print("✅ 完整游戏模拟结束")

    gc3 = GameController()
    gc3.new_game()

    t = gc3.start_task_selection()
    assert t["phase"] == "task_selection"

    pool = t["task_pool"]
    w = await gc3.submit_task_selection([pool[0]["id"], pool[1]["id"]])
    assert w["phase"] == "working"

    if w["event"]:
        emotion_id = w["event"]["emotion_cards"][0]["id"]
        action_id = w["event"]["action_cards"][0]["id"]
        gc3.play_cards(emotion_id, action_id)

    h = await gc3.advance_to_next_hour()
    if h.get("event"):
        emotion_id = h["event"]["emotion_cards"][0]["id"]
        action_id = h["event"]["action_cards"][0]["id"]
        gc3.play_cards(emotion_id, action_id)

    h2 = await gc3.advance_to_next_hour()
    assert h2["phase"] == "voting"

    candidates = h2["candidates"]
    v = await gc3.submit_vote_v2(candidates[0]["id"])
    assert "vote_record" in v

    if not v.get("game_over"):
        n = gc3.enter_night_phase()
        assert n["phase"] == "night"
        print("✅ 阶段切换顺序正确：任务选择→工作→投票→夜间")

    gc4 = GameController()
    gc4.new_game()
    gc4.start_task_selection()

    err1 = await gc4.submit_task_selection([])
    assert "error" in err1
    print(f"✅ 空任务被拒绝：{err1['error']}")

    err2 = await gc4.submit_task_selection(["fake_task_999"])
    assert "error" in err2
    print(f"✅ 无效任务被拒绝：{err2['error']}")

    print("\n🎉 模块7全部测试通过！MVP后端完成！")


if __name__ == "__main__":
    asyncio.run(main())
