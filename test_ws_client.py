"""
末日调查员 - WebSocket 测试客户端

模拟 Godot 前端，通过 WebSocket 走完一整局游戏。

使用方法：
  1. 先启动服务器：python server.py
  2. 再运行此脚本：python test_ws_client.py
"""

import asyncio
import json
import random
import sys

import websockets

URI = "ws://localhost:8765"


async def send_and_receive(ws, msg_type: str, data: dict = None) -> dict:
    message = {"type": msg_type, "data": data or {}}
    await ws.send(json.dumps(message, ensure_ascii=False))
    response = await ws.recv()
    return json.loads(response)


async def test_full_game():
    print("连接服务器...")
    async with websockets.connect(URI) as ws:
        print("✅ 已连接\n")

        resp = await send_and_receive(ws, "new_game")
        assert resp["type"] == "game_started", f"期望 game_started，实际 {resp['type']}"
        task_pool = resp["data"]["task_pool"]
        print(f"✅ 新游戏创建，第{resp['data']['day']}天，{len(task_pool)}个任务可选")

        game_over = False
        day = 1

        while not game_over and day <= 5:
            print(f"\n{'='*50}")
            print(f"第 {day} 天")
            print(f"{'='*50}")

            if day > 1:
                task_pool = resp["data"]["task_pool"]

            pick_count = min(6, len(task_pool))
            picked_ids = [t["id"] for t in task_pool[:pick_count]]
            resp = await send_and_receive(ws, "select_tasks", {"task_ids": picked_ids})

            if resp["type"] == "error":
                print(f"❌ 任务选择失败：{resp['data']['message']}")
                return
            assert resp["type"] == "work_started"
            print(f"  选了{pick_count}个任务，开始工作")

            event = resp["data"].get("event")

            for hour in range(pick_count):
                if event:
                    e_id = event["emotion_cards"][0]["id"]
                    a_id = event["action_cards"][0]["id"]
                    e_name = event["emotion_cards"][0]["name"]
                    a_name = event["action_cards"][0]["name"]

                    resp = await send_and_receive(ws, "play_cards", {
                        "emotion": e_id, "action": a_id
                    })
                    assert resp["type"] == "card_result", f"期望 card_result，实际 {resp['type']}"
                    combo = resp["data"]["combination_type"]
                    hint = "📝" if event.get("has_evidence_hint") else ""
                    print(f"  第{hour+1}小时：{event['event_name']} [{e_name} + {a_name}] → {combo} {hint}")

                    if resp["data"].get("can_use_record_card") and random.random() < 0.3:
                        card_resp = await send_and_receive(ws, "get_status")
                        blank_count = card_resp["data"].get("blank_cards", 0)
                        if blank_count > 0:
                            for i in range(1, 10):
                                card_id = f"rc_{i:03d}"
                                rc_resp = await send_and_receive(ws, "use_record_card", {"card_id": card_id})
                                if rc_resp["type"] == "record_card_used":
                                    print("    📼 使用了记录卡")
                                    next_data = rc_resp["data"]["next_hour"]
                                    break
                            else:
                                next_resp = await send_and_receive(ws, "skip_record")
                                next_data = next_resp["data"]
                        else:
                            next_resp = await send_and_receive(ws, "skip_record")
                            next_data = next_resp["data"]
                    else:
                        next_resp = await send_and_receive(ws, "skip_record")
                        next_data = next_resp["data"]

                    if next_data.get("phase") == "voting":
                        event = None
                        break
                    event = next_data.get("event")

                    if next_data.get("boss_alert"):
                        print(f"    ⚠️ {next_data['boss_alert']}")
                else:
                    next_resp = await send_and_receive(ws, "skip_record")
                    next_data = next_resp["data"]
                    if next_data.get("phase") == "voting":
                        break
                    event = next_data.get("event")

            print("  投票阶段")
            candidates = next_data.get("candidates", [])
            if not candidates:
                status = await send_and_receive(ws, "get_status")
                alive = status["data"].get("alive_npcs", [])
                npc_ids = ["laowang", "xiaoli", "ahua", "dazhuang", "zhoujie"]
                candidates = [{"id": nid} for nid in npc_ids if nid.replace("_", "") in str(alive) or True]

            if candidates:
                target = random.choice(candidates)
                target_id = target["id"] if isinstance(target, dict) else target
                resp = await send_and_receive(ws, "cast_vote", {"target_npc": target_id})

                if resp["type"] == "error":
                    for try_id in ["laowang", "xiaoli", "ahua", "dazhuang", "zhoujie"]:
                        resp = await send_and_receive(ws, "cast_vote", {"target_npc": try_id})
                        if resp["type"] == "vote_result":
                            break

                if resp["type"] == "vote_result":
                    vote_data = resp["data"]
                    tally = vote_data.get("tally", {})
                    print(f"  得票：{tally}")
                    if vote_data.get("is_tie"):
                        print("  结果：平票")
                    elif vote_data.get("target"):
                        print(f"  结果：{vote_data['target_name']}被审问")

                    if vote_data.get("game_over"):
                        print(f"\n💀 游戏结束：{vote_data.get('game_result')}")
                        game_over = True
                        break

            if not game_over:
                resp = await send_and_receive(ws, "enter_night")
                night_data = resp["data"]

                if night_data.get("phase") == "game_over":
                    print(f"\n游戏结束：{night_data.get('game_result')}")
                    print(f"  {night_data.get('message', '')[:80]}...")
                    game_over = True
                    break

                print(f"  夜间：{night_data.get('message', '')[:50]}...")

                resp = await send_and_receive(ws, "next_day")
                if resp["type"] == "new_day":
                    task_pool = resp["data"].get("task_pool", [])
                    day += 1
                elif resp["data"].get("phase") == "game_over":
                    game_over = True

        final = await send_and_receive(ws, "get_status")
        status = final["data"]
        print(f"\n{'='*50}")
        print("最终状态：")
        print(f"  存活天数：{status.get('day')}")
        print(f"  存活NPC：{status.get('alive_npcs')}")
        print(f"  收集证据：{status.get('evidence_count')}份")
        print(f"  游戏结果：{status.get('game_result')}")

        print("\n--- 错误处理测试 ---")
        err1 = await send_and_receive(ws, "unknown_command")
        assert err1["type"] == "error"
        print(f"✅ 未知命令被拒绝：{err1['data']['message']}")

        print("\n🎉 WebSocket 全部测试通过！")


if __name__ == "__main__":
    try:
        asyncio.run(test_full_game())
    except ConnectionRefusedError:
        print("❌ 连接失败！请先启动服务器：python server.py")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 测试出错：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
