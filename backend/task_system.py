import copy
import random

from .constants import EVIDENCE_TASKS_PER_DAY_MAX, EVIDENCE_TASKS_PER_DAY_MIN, TASK_DEFINITIONS
from .enums import EvidenceType, Room
from .models import NPCState, Task


class TaskSystem:
    """
    任务系统：负责每日任务池生成、证据分配、NPC任务分配、玩家选择校验。
    """

    ROOM_MAX_COUNT = 4

    @staticmethod
    def generate_daily_task_pool(day: int) -> tuple[list[Task], list[str]]:
        """
        生成当日任务池（12个任务）。

        返回:
            task_pool: 当日12个任务的列表（深拷贝，evidence_tag已分配）
            evidence_task_ids: 本日证据任务的task_id列表

        算法：
        1. 从14个证据任务中随机抽2-3个
        2. 从剩余任务中补齐到12个，同时保证房间分布均匀
        3. 为证据任务分配动态标签
        """
        all_tasks = copy.deepcopy(TASK_DEFINITIONS)

        evidence_tasks = [t for t in all_tasks if t.evidence_type is not None]
        normal_tasks = [t for t in all_tasks if t.evidence_type is None]

        evidence_count = random.randint(
            EVIDENCE_TASKS_PER_DAY_MIN,
            EVIDENCE_TASKS_PER_DAY_MAX,
        )
        selected_evidence = random.sample(evidence_tasks, evidence_count)

        required_rooms = [
            Room.OFFICE,
            Room.MEETING,
            Room.WAREHOUSE,
            Room.PANTRY,
            Room.RECEPTION,
        ]
        room_count: dict[str, int] = {}
        for task in selected_evidence:
            room_key = task.room.value
            room_count[room_key] = room_count.get(room_key, 0) + 1

        random.shuffle(normal_tasks)

        selected_normal: list[Task] = []
        selected_normal_ids: set[str] = set()

        # 硬性规则：每天5个房间都至少出现1个任务
        for room in required_rooms:
            room_key = room.value
            if room_count.get(room_key, 0) > 0:
                continue
            room_candidates = [t for t in normal_tasks if t.room == room and t.id not in selected_normal_ids]
            if not room_candidates:
                continue
            picked = random.choice(room_candidates)
            selected_normal.append(picked)
            selected_normal_ids.add(picked.id)
            room_count[room_key] = room_count.get(room_key, 0) + 1

        target_normal_count = 12 - evidence_count
        for task in normal_tasks:
            if len(selected_normal) >= target_normal_count:
                break
            if task.id in selected_normal_ids:
                continue
            room_key = task.room.value
            current_count = room_count.get(room_key, 0)
            if current_count >= TaskSystem.ROOM_MAX_COUNT:
                continue
            selected_normal.append(task)
            selected_normal_ids.add(task.id)
            room_count[room_key] = current_count + 1

        if len(selected_normal) < target_normal_count:
            remaining = [t for t in normal_tasks if t.id not in selected_normal_ids]
            for task in remaining:
                if len(selected_normal) >= target_normal_count:
                    break
                selected_normal.append(task)
                selected_normal_ids.add(task.id)

        evidence_task_ids: list[str] = []
        for idx, task in enumerate(selected_evidence):
            tag = f"evidence_day{day}_{idx+1:03d}_{task.evidence_type.value}"
            task.evidence_tag = tag
            evidence_task_ids.append(task.id)

        task_pool = selected_evidence + selected_normal
        random.shuffle(task_pool)

        return task_pool, evidence_task_ids

    @staticmethod
    def assign_npc_tasks(npc: NPCState) -> list[Task]:
        """
        为单个NPC分配5小时任务。

        NPC独立从完整的29个任务中按偏好权重选择。
        NPC可以和玩家做相同的任务，这不冲突。

        算法：
        1. 根据NPC的task_preferences确定每个房间的权重
        2. 按权重随机选择5个房间（允许重复）
        3. 从每个选中的房间里随机选一个任务

        参数:
            npc: NPC状态对象，包含task_preferences

        返回:
            5个任务的列表（深拷贝）
        """
        all_tasks = copy.deepcopy(TASK_DEFINITIONS)

        tasks_by_room: dict[str, list[Task]] = {}
        for task in all_tasks:
            room_key = task.room.value
            if room_key not in tasks_by_room:
                tasks_by_room[room_key] = []
            tasks_by_room[room_key].append(task)

        rooms = list(npc.task_preferences.keys())
        weights = [npc.task_preferences[r] for r in rooms]

        selected_rooms = random.choices(rooms, weights=weights, k=5)

        selected_tasks: list[Task] = []
        for room_key in selected_rooms:
            task = random.choice(tasks_by_room[room_key])
            selected_tasks.append(copy.deepcopy(task))

        return selected_tasks

    @staticmethod
    def assign_all_npcs_tasks(npcs: dict[str, "NPCState"]) -> None:
        """
        为所有存活NPC分配任务，直接修改NPC状态。

        参数:
            npcs: NPC字典 {id: NPCState}
        """
        for npc_id, npc in npcs.items():
            if npc.alive:
                npc.selected_tasks = TaskSystem.assign_npc_tasks(npc)
                npc.current_task_index = 0
                if npc.selected_tasks:
                    npc.current_room = npc.selected_tasks[0].room

    @staticmethod
    def validate_player_selection(
        selected_task_ids: list[str],
        task_pool: list[Task],
        max_hours: int = 5,
    ) -> tuple[bool, str, list[Task]]:
        """
        校验玩家的任务选择是否合法。

        参数:
            selected_task_ids: 玩家选择的任务ID列表
            task_pool: 当日任务池
            max_hours: 最大行动力（默认5小时）

        返回:
            (is_valid, error_message, selected_tasks)
            - is_valid: 是否合法
            - error_message: 错误信息（合法时为空字符串）
            - selected_tasks: 合法时返回任务对象列表，非法时为空列表
        """
        pool_dict = {task.id: task for task in task_pool}

        for task_id in selected_task_ids:
            if task_id not in pool_dict:
                return False, f"任务 {task_id} 不在今日任务池中", []

        if len(set(selected_task_ids)) != len(selected_task_ids):
            return False, "不能重复选择同一个任务", []

        # 规则：必须恰好选择 max_hours 个任务（当前为5个）
        if len(selected_task_ids) != max_hours:
            return False, f"必须恰好选择{max_hours}个任务，当前选择{len(selected_task_ids)}个", []

        total_hours = sum(pool_dict[tid].duration for tid in selected_task_ids)
        if total_hours > max_hours:
            return False, f"总耗时{total_hours}小时，超过行动力上限{max_hours}小时", []

        selected_tasks = [pool_dict[tid] for tid in selected_task_ids]
        return True, "", selected_tasks
