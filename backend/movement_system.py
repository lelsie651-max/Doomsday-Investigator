import random

from .constants import (
    BOSS_DEFAULT_ROOM,
    BOSS_PATROL_ROOMS,
    BOSS_PUA_ROOM,
    BOSS_SHADY_ROOM,
    DAILY_ACTION_POINTS,
)
from .data_loader import DataLoader
from .enums import BossBehavior, Room
from .models import BossState, NPCState, PlayerState, Task

BOSS_PATROL_HINTS = [
    "走廊里传来八条触手拍地板的声音……",
    "经理的咖啡杯不在工位上了。",
    "有人看到一团黑影从经理办公室飘了出去。",
    "空气中弥漫着一股廉价古龙水和墨汁混合的气味。",
    "你听到远处传来经理哼小曲的声音，越来越近了……",
    "茶水间的鱼缸里，金鱼突然集体转向了同一个方向。",
    "天花板上的监控摄像头似乎动了一下。",
    '有同事小声说："经理出来了，各回各位！"',
    "你感觉背后有一股来自深渊的注视……大概是错觉吧。",
    "走廊尽头传来皮鞋——不对，是吸盘——踩在地板上的声音。",
]


class MovementSystem:
    """
    移动系统：管理所有角色的自动移动逻辑。

    - 玩家和NPC：按任务队列自动移动到对应房间
    - 经理：独立的索伦之眼状态机，每小时随机行为
    """

    @staticmethod
    def generate_boss_hourly_plan(
        boss: BossState,
        day: int,
        total_hours: int = DAILY_ACTION_POINTS,
    ) -> list[BossBehavior]:
        weights = boss.patrol_weights.get(day, boss.patrol_weights[1])
        plan: list[BossBehavior] = []

        for _ in range(total_hours):
            w_patrol = weights["patrol"]
            w_shady = weights["shady"]

            # 预排PUA已废弃：PUA由每小时实时分发器判定触发。
            options = [BossBehavior.PATROL, BossBehavior.SHADY_BUSINESS]
            option_weights = [w_patrol, w_shady]

            behavior = random.choices(options, weights=option_weights, k=1)[0]
            plan.append(behavior)

        return plan

    @staticmethod
    def execute_boss_hour(
        boss: BossState,
        behavior: BossBehavior,
        alive_npc_ids: list[str],
    ) -> dict:
        result = {
            "behavior": behavior.value,
            "room": None,
            "target_npc": None,
            "alert_hint": None,
            "generates_evidence": False,
        }

        if behavior == BossBehavior.PATROL:
            target_room = random.choice(BOSS_PATROL_ROOMS)
            boss.current_room = target_room
            boss.current_behavior = BossBehavior.PATROL
            boss.target_npc = None
            result["room"] = target_room.value
            result["alert_hint"] = random.choice(BOSS_PATROL_HINTS)
            return result

        if behavior == BossBehavior.PUA:
            target = random.choice(alive_npc_ids) if alive_npc_ids else None
            boss.current_room = BOSS_PUA_ROOM
            boss.current_behavior = BossBehavior.PUA
            boss.target_npc = target
            result["room"] = BOSS_PUA_ROOM.value
            result["target_npc"] = target
            return result

        if behavior == BossBehavior.SHADY_BUSINESS:
            boss.current_room = BOSS_SHADY_ROOM
            boss.current_behavior = BossBehavior.SHADY_BUSINESS
            boss.target_npc = None
            result["room"] = BOSS_SHADY_ROOM.value
            result["generates_evidence"] = True
            return result

        boss.current_room = BOSS_DEFAULT_ROOM
        result["room"] = BOSS_DEFAULT_ROOM.value
        return result

    @staticmethod
    def move_player_to_current_task(player: PlayerState):
        if player.current_task_index < len(player.selected_tasks):
            task = player.selected_tasks[player.current_task_index]
            player.current_room = task.room

    @staticmethod
    def move_npc_to_current_task(npc: NPCState):
        if not npc.alive:
            return
        if npc.current_task_index < len(npc.selected_tasks):
            task = npc.selected_tasks[npc.current_task_index]
            npc.current_room = task.room

    @staticmethod
    def move_all_to_current_tasks(
        player: PlayerState,
        npcs: dict[str, NPCState],
    ):
        MovementSystem.move_player_to_current_task(player)
        for _, npc in npcs.items():
            MovementSystem.move_npc_to_current_task(npc)

    @staticmethod
    def handle_pua_interruption(
        target_id: str,
        player: PlayerState,
        npcs: dict[str, NPCState],
    ) -> dict:
        result = {
            "target_id": target_id,
            "target_name": "",
            "original_room": "",
            "interrupted_task": "",
        }

        if target_id == "player":
            result["target_name"] = "你"
            result["original_room"] = player.current_room.value
            if player.current_task_index < len(player.selected_tasks):
                result["interrupted_task"] = player.selected_tasks[player.current_task_index].name
            player.current_room = BOSS_PUA_ROOM
            return result

        if target_id in npcs and npcs[target_id].alive:
            npc = npcs[target_id]
            result["target_name"] = npc.name
            result["original_room"] = npc.current_room.value
            if npc.current_task_index < len(npc.selected_tasks):
                result["interrupted_task"] = npc.selected_tasks[npc.current_task_index].name
            npc.current_room = BOSS_PUA_ROOM

        return result

    @staticmethod
    def calculate_movement_phase(
        player_current_room: str,
        player_target_room: str,
        npcs: dict[str, NPCState],
        boss_patrol_rooms: list,
        task_index: int,
        boss_current_room: str = "boss_office",
    ) -> dict:
        """
        计算本轮所有角色的移动信息。

        返回:
            {
                "max_duration": float,
                "movements": [
                    {"id": "player", "name": "玩家", "from": "...", "to": "...", "duration": 2.0},
                    ...
                ]
            }
        """
        from .data_loader import DataLoader

        dl = DataLoader()
        movements = []
        max_duration = 0.0

        # 玩家移动
        p_dur = dl.get_move_time(player_current_room, player_target_room)
        movements.append({
            "id": "player",
            "name": "玩家",
            "from": player_current_room,
            "to": player_target_room,
            "duration": p_dur,
        })
        max_duration = max(max_duration, p_dur)

        # NPC移动
        for npc_id, npc in npcs.items():
            if not npc.alive:
                continue
            if task_index < len(npc.selected_tasks):
                npc_target = npc.selected_tasks[task_index].room.value
            else:
                npc_target = npc.current_room.value if npc.current_room else "office"
            npc_from = npc.current_room.value if npc.current_room else "office"
            n_dur = dl.get_move_time(npc_from, npc_target)
            movements.append({
                "id": npc_id,
                "name": npc.name,
                "from": npc_from,
                "to": npc_target,
                "duration": n_dur,
            })
            max_duration = max(max_duration, n_dur)

        # 经理移动（优先使用巡视路线，缺失时原地）
        boss_target = boss_current_room
        if boss_patrol_rooms and task_index < len(boss_patrol_rooms):
            boss_target = boss_patrol_rooms[task_index]
            if hasattr(boss_target, "value"):
                boss_target = boss_target.value
        b_dur = dl.get_move_time(boss_current_room, boss_target)
        movements.append({
            "id": "boss",
            "name": str(DataLoader().get_npc_field("boss", "name", "经理")).strip() or "经理",
            "from": boss_current_room,
            "to": boss_target,
            "duration": b_dur,
        })
        max_duration = max(max_duration, b_dur)

        return {
            "max_duration": max_duration,
            "movements": movements,
        }
