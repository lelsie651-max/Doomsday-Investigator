"""
末日调查员 - 命令行试玩版
在终端中运行即可体验完整游戏流程，无需Godot前端。

用法：在项目根目录运行
  python backend/play.py
"""

import os
import sys
import asyncio

# 确保能找到backend包
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.game_controller import GameController


class QuitGame(Exception):
    pass


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def press_enter():
    raw = input("\n按回车继续（输入 q 退出）...").strip().lower()
    if raw == "q":
        raise QuitGame()


def print_divider(char="─", width=50):
    print(char * width)


def print_header(text):
    print_divider("═")
    print(f"  {text}")
    print_divider("═")


def print_box(text):
    lines = text.split("\n")
    max_len = max(len(line) for line in lines)
    print("┌" + "─" * (max_len + 2) + "┐")
    for line in lines:
        print(f"│ {line.ljust(max_len)} │")
    print("└" + "─" * (max_len + 2) + "┘")


class CLIGame:
    def __init__(self):
        self.gc = GameController()
        self.current_work_data = None

    def read_input(self, prompt: str) -> str:
        raw = input(prompt).strip()
        if raw.lower() == "q":
            raise QuitGame()
        return raw

    def run(self):
        try:
            clear_screen()
            self.print_intro()
            self.gc.new_game()

            game_over = False
            for day in range(1, 6):
                if game_over:
                    break

                clear_screen()
                print_header(f"第 {day} 天")

                game_over = self.phase_task_selection()
                if game_over:
                    break

                game_over = self.phase_working()
                if game_over:
                    break

                game_over = self.phase_voting()
                if game_over:
                    break

                if day < 5:
                    game_over = self.phase_night()
                else:
                    self.show_ending()
                    game_over = True

            if not game_over:
                self.show_ending()

            print("\n感谢试玩《末日调查员》MVP版！")
        except QuitGame:
            print("\n已退出游戏，欢迎下次再来。")

    # ========================================
    # 开场
    # ========================================
    def print_intro(self):
        print_header("末日调查员 - 命令行试玩版")
        print()
        print("僵尸横行的末世。你是「末日调查局」的卧底调查员，")
        print("伪装成普通员工潜入黑心公司「救世主集团」。")
        print()
        print("你的任务：")
        print("  · 在5天内收集5种证据")
        print("  · 不被同事投票揭穿身份")
        print("  · 将证据带出，揭露公司罪行")
        print()
        boss_name = self.gc.state.boss.name if self.gc and self.gc.state and self.gc.state.boss else "经理"
        boss_species = self.gc.state.boss.species if self.gc and self.gc.state and self.gc.state.boss else "未知物种"
        print(f"经理（{boss_species}·{boss_name}）宣布：")
        print_box(
            "公司收到消息，有一名末日调查员卧底在销售小组。\n"
            "从今天开始，每天下班前匿名投票。\n"
            "票数最高者我会亲自谈话。\n"
            "投中卧底的人，直接晋升总部，薪水翻倍！"
        )
        press_enter()

    # ========================================
    # 阶段1：任务选择
    # ========================================
    def phase_task_selection(self) -> bool:
        task_data = self.gc.start_task_selection()
        pool = task_data["task_pool"]

        clear_screen()
        print_header(f"第 {task_data['day']} 天 - 任务选择")
        print(f"\n行动力：{task_data['action_points']} 小时")
        print(f"可选任务（共{len(pool)}个，每个1小时）：\n")

        for i, task in enumerate(pool):
            room_names = {
                "office": "主办公区", "meeting": "会议室",
                "warehouse": "仓库", "pantry": "茶水间",
                "reception": "接待区",
            }
            room = room_names.get(task["room"], task["room"])
            print(f"  [{i+1:2d}] {task['name']}  ({room})")

        print(f"\n请输入要做的任务编号（用空格分隔，最多选{task_data['action_points']}个）：")
        print("例如：1 3 5 7 9 11（输入 q 可退出）")

        while True:
            try:
                raw = self.read_input("\n> ")
                if not raw:
                    print("至少选1个任务！")
                    continue

                indices = [int(x) - 1 for x in raw.split()]

                # 校验范围
                if any(i < 0 or i >= len(pool) for i in indices):
                    print(f"编号必须在1-{len(pool)}之间！")
                    continue

                if len(indices) > task_data["action_points"]:
                    print(f"最多选{task_data['action_points']}个！")
                    continue

                # 检查重复
                if len(set(indices)) != len(indices):
                    print("不能重复选择！")
                    continue

                picked_ids = [pool[i]["id"] for i in indices]
                result = self.gc.submit_task_selection(picked_ids)

                if "error" in result:
                    print(f"选择失败：{result['error']}")
                    continue

                self.current_work_data = result
                print(f"\n已选择{len(picked_ids)}个任务。开始工作！")
                press_enter()
                return False

            except ValueError:
                print("请输入数字编号！")

    # ========================================
    # 阶段2：工作执行
    # ========================================
    def phase_working(self) -> bool:
        player = self.gc.state.player
        total_tasks = len(player.selected_tasks)

        for hour in range(total_tasks):
            clear_screen()
            status = self.gc.get_game_status()
            print_header(f"第 {status['day']} 天 - 第 {hour+1}/{total_tasks} 小时")

            self.print_status_bar(status)

            # 获取当前事件（第一小时已经在submit时触发了）
            if hour == 0:
                event = (self.current_work_data or {}).get("event")
            else:
                hour_data = self.gc.advance_to_next_hour()

                # 经理预警
                if hour_data.get("boss_alert"):
                    print(f"\n  ⚠️  {hour_data['boss_alert']}")
                    press_enter()

                # PUA打断
                if hour_data.get("pua_interruption"):
                    pua = hour_data["pua_interruption"]
                    print(f"\n  😱 经理把{pua['target_name']}拉去“赋能谈话”了！")
                    if pua["target_id"] == "player":
                        print("  你被强制拉进了会议室！这个小时什么都干不了！")
                    press_enter()

                if hour_data.get("phase") == "voting":
                    return False  # 一天结束，进入投票

                event = hour_data.get("event")

            if not event:
                continue

            # 显示事件
            self.show_event(event, hour + 1, total_tasks)

            # 玩家选卡
            game_over = self.handle_card_selection(event)
            if game_over:
                return True

        # 所有任务完成，推进触发投票
        self.gc.advance_to_next_hour()
        return False

    def show_event(self, event, current_hour, total_hours):
        print(f"\n{'─'*50}")
        print(f"  📌 {event['event_name']}")
        print(f"{'─'*50}")
        print(f"\n{event['description']}")

        if event.get("has_evidence_hint") and event.get("evidence_hint"):
            print(f"\n  💡 {event['evidence_hint']}")

        print(f"\n❓ {event['prompt']}")

    def handle_card_selection(self, event) -> bool:
        emotions = event["emotion_cards"]
        actions = event["action_cards"]

        print(f"\n{'─'*50}")
        print("  你的手牌")
        print(f"{'─'*50}")

        print("\n  情绪卡（选1张）：")
        for i, card in enumerate(emotions):
            tag = "⭐" if card["is_normal"] else "🤪"
            print(f"    [{i+1}] {tag} {card['name']}")

        print("\n  行动卡（选1张）：")
        for i, card in enumerate(actions):
            tag = "⭐" if card["is_normal"] else "🤪"
            print(f"    [{i+1}] {tag} {card['name']}")

        while True:
            try:
                raw = self.read_input("\n选择（格式：情绪编号 行动编号，如 2 3；回车默认 1 1；q 退出）> ")
                if not raw:
                    e_idx = 0
                    a_idx = 0
                else:
                    parts = raw.split()
                    if len(parts) != 2:
                        print("请输入两个数字！")
                        continue
                    e_idx = int(parts[0]) - 1
                    a_idx = int(parts[1]) - 1

                if e_idx < 0 or e_idx >= len(emotions) or a_idx < 0 or a_idx >= len(actions):
                    print(f"编号必须在1-{len(emotions)}之间！")
                    continue

                e_id = emotions[e_idx]["id"]
                a_id = actions[a_idx]["id"]

                result = self.gc.play_cards(e_id, a_id)
                if "error" in result:
                    print(f"出牌失败：{result['error']}")
                    continue

                # 显示结果
                print(f"\n{'─'*50}")
                combo_icons = {"steady": "😌 稳妥", "contrast": "😵 反差", "crazy": "🤯 癫狂"}
                combo_text = combo_icons.get(result["combination_type"], result["combination_type"])
                print(f"  {result['emotion_name']} × {result['action_name']} → {combo_text}")
                print(f"{'─'*50}")
                print(f"\n{result['result_text']}")

                # 记录卡提示
                if result.get("can_use_record_card") and result.get("blank_cards_count", 0) > 0:
                    print(f"\n  📼 你有{result['blank_cards_count']}张空白记录卡。要录下这段经历吗？")
                    use = self.read_input("  使用记录卡？(y/n，q退出) > ").lower()
                    if use == "y":
                        # 找空白卡
                        for rc in self.gc.state.player.record_cards:
                            if rc.status.value == "blank":
                                rc_result = asyncio.run(self.gc.use_record_card(rc.id))
                                print(f"\n  {rc_result['message']}")
                                break

                press_enter()
                return False

            except ValueError:
                print("请输入数字！")

    # ========================================
    # 阶段3：投票
    # ========================================
    def phase_voting(self) -> bool:
        voting_data = self.gc._enter_voting_phase()

        clear_screen()
        print_header(f"第 {voting_data['day']} 天 - 投票环节")
        print(f"\n{voting_data['message']}")

        candidates = voting_data["candidates"]
        print("\n  候选人：")
        for i, c in enumerate(candidates):
            print(f"    [{i+1}] {c['name']}（{c['species']}）")

        while True:
            try:
                raw = self.read_input("\n你要投谁？输入编号（回车默认1，q退出） > ")
                idx = 0 if not raw else int(raw) - 1
                if idx < 0 or idx >= len(candidates):
                    print(f"编号必须在1-{len(candidates)}之间！")
                    continue

                target_id = candidates[idx]["id"]
                result = self.gc.submit_vote(target_id)

                if "error" in result:
                    print(f"投票失败：{result['error']}")
                    continue

                # 唱票
                clear_screen()
                print_header("唱票结果")
                print()
                for d in result["vote_details"]:
                    print(f"  {d['voter_name']} → {d['target_name']}")

                print(f"\n  得票统计：{result['tally']}")
                print(f"\n{'─'*50}")
                print(f"\n{result['outcome_text']}")

                if result.get("game_over"):
                    press_enter()
                    self.show_ending()
                    return True

                press_enter()
                return False

            except ValueError:
                print("请输入数字！")

    # ========================================
    # 阶段4：夜间
    # ========================================
    def phase_night(self) -> bool:
        night_data = self.gc.enter_night_phase()

        if night_data.get("phase") == "game_over":
            self.show_ending()
            return True

        clear_screen()
        print_header("夜间")
        print(f"\n{night_data['message']}")

        press_enter()
        self.gc.proceed_to_next_day()
        return False

    # ========================================
    # 结局
    # ========================================
    def show_ending(self):
        if not self.gc.state.game_over:
            self.gc.manager._end_game()

        ending = self.gc._build_game_over_response()

        clear_screen()
        print_header("游戏结束")
        print(f"\n{ending['message']}")

        if ending["evidence_collected"]:
            print(f"\n  收集到的证据（{ending['evidence_types_count']}/5种）：")
            for e in ending["evidence_collected"]:
                print(f"    · [{e['type']}] {e['source']}（第{e['day']}天）")
        else:
            print("\n  你一份证据都没收集到。")

        print(f"\n  存活天数：{ending['total_days_survived']}")
        print_divider("═")

    # ========================================
    # UI工具
    # ========================================
    def print_status_bar(self, status):
        print(f"\n  💰 金币:{status['player_gold']}  "
              f"🔋 电量:{status['player_battery']}%  "
              f"📼 证据:{status['evidence_count']}  "
              f"🏠 位置:{status['player_room']}  "
              f"👥 存活:{len(status['alive_npcs'])}人")


if __name__ == "__main__":
    game = CLIGame()
    game.run()
