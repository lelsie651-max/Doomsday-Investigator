from .constants import ACCESSIBLE_ROOMS
from .enums import Room
from .models import BossState, NPCState, PlayerState


class RoomSystem:
    """
    房间管理系统：追踪所有角色的位置，提供房间人员查询。
    """

    @staticmethod
    def get_room_occupants(
        player: PlayerState,
        npcs: dict[str, NPCState],
        boss: BossState,
        room: Room,
    ) -> dict:
        result = {
            "player_present": False,
            "npcs": [],
            "npc_details": [],
            "boss_present": False,
            "total_count": 0,
        }

        if player.current_room == room:
            result["player_present"] = True
            result["total_count"] += 1

        for npc_id, npc in npcs.items():
            if npc.alive and npc.current_room == room:
                result["npcs"].append(npc_id)
                result["npc_details"].append(
                    {
                        "id": npc_id,
                        "name": npc.name,
                        "personality": npc.personality,
                    }
                )
                result["total_count"] += 1

        if boss.current_room == room:
            result["boss_present"] = True
            result["total_count"] += 1

        return result

    @staticmethod
    def get_all_room_occupants(
        player: PlayerState,
        npcs: dict[str, NPCState],
        boss: BossState,
    ) -> dict[str, dict]:
        snapshot = {}
        all_rooms = list(ACCESSIBLE_ROOMS) + [Room.BOSS_OFFICE]
        for room in all_rooms:
            snapshot[room.value] = RoomSystem.get_room_occupants(player, npcs, boss, room)
        return snapshot

    @staticmethod
    def get_player_coworkers(
        player: PlayerState,
        npcs: dict[str, NPCState],
        boss: BossState,
    ) -> dict:
        room = player.current_room
        occupants = RoomSystem.get_room_occupants(player, npcs, boss, room)

        npc_names = [detail["name"] for detail in occupants["npc_details"]]
        npc_personalities = [detail["personality"] for detail in occupants["npc_details"]]

        return {
            "room": room.value,
            "alone": occupants["total_count"] == 1,
            "npc_ids": occupants["npcs"],
            "npc_names": npc_names,
            "npc_personalities": npc_personalities,
            "boss_present": occupants["boss_present"],
            "headcount": occupants["total_count"],
        }

    @staticmethod
    def get_positions_for_frontend(
        player: PlayerState,
        npcs: dict[str, NPCState],
        boss: BossState,
    ) -> dict[str, str]:
        positions = {"player": player.current_room.value}
        for npc_id, npc in npcs.items():
            if npc.alive:
                positions[npc_id] = npc.current_room.value
        positions["boss"] = boss.current_room.value
        return positions
