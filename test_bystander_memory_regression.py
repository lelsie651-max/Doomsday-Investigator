import logging
import sys
from dataclasses import dataclass
from typing import Callable
from unittest.mock import patch

from backend.data_loader import DataLoader
from backend.enums import Room
from backend.evidence_converter import EvidenceConverter
from backend.game_controller import GameController
from backend.models import Task


@dataclass
class CheckResult:
    index: int
    title: str
    ok: bool
    detail: str


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


def make_task(task_id: str, name: str, room: Room = Room.OFFICE) -> Task:
    return Task(id=task_id, name=name, room=room)


def prepare_gc() -> GameController:
    gc = GameController()
    gc.new_game()
    return gc


def reset_room_assignments(gc: GameController, room: Room, keep_ids: set[str]) -> None:
    gc.state.player.current_room = room
    for npc_id, npc in gc.state.npcs.items():
        npc.selected_tasks = []
        npc.current_task_index = 0
        if npc_id in keep_ids:
            npc.current_room = room
        else:
            npc.current_room = Room.MEETING if room != Room.MEETING else Room.OFFICE


def day_impressions(gc: GameController, observer_id: str, target_id: str) -> list[str]:
    return list(
        gc.memory.memories.get(observer_id, {}).get(target_id, {}).get(gc.state.current_day, [])
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(index: int, title: str, fn: Callable[[], str]) -> CheckResult:
    try:
        detail = fn()
        return CheckResult(index=index, title=title, ok=True, detail=detail)
    except Exception as exc:
        return CheckResult(index=index, title=title, ok=False, detail=str(exc))


def check_1_2_3_npc_pair_log_memory_relation() -> str:
    gc = prepare_gc()
    npc_ids = list(gc.state.npcs.keys())
    npc_a, npc_b = npc_ids[0], npc_ids[1]
    same_task = make_task("task_same", "整理库存", Room.OFFICE)

    reset_room_assignments(gc, Room.OFFICE, {npc_a, npc_b})
    gc.state.npcs[npc_a].selected_tasks = [same_task]
    gc.state.npcs[npc_b].selected_tasks = [same_task]
    gc.state.npcs[npc_a].current_task_index = 0
    gc.state.npcs[npc_b].current_task_index = 0
    gc.state.player.selected_tasks = [make_task("task_player_other", "回复邮件", Room.OFFICE)]
    gc.state.player.current_task_index = 0

    rel_a_before = gc.state.relationships[npc_a][npc_b]
    rel_b_before = gc.state.relationships[npc_b][npc_a]
    aff_a_before, sus_a_before = rel_a_before.affinity, rel_a_before.suspicion
    aff_b_before, sus_b_before = rel_b_before.affinity, rel_b_before.suspicion

    logger = logging.getLogger("DoomsdayRoute")
    cap = LogCapture()
    old_level = logger.level
    logger.setLevel(logging.INFO)
    cap.setLevel(logging.INFO)
    logger.addHandler(cap)
    try:
        with patch.object(
            DataLoader,
            "get_npc_npc_interaction_template",
            return_value={
                "tone": "friendly",
                "template": "{a}和{b}在{task}配合顺畅。",
                "affinity_delta": 3,
                "suspicion_delta": -1,
            },
        ):
            gc._set_hour_settlement_context(is_blackmail=False, participant_npc_ids=[])
            gc._resolve_hour_bystander_and_npc_pairs()
    finally:
        logger.removeHandler(cap)
        logger.setLevel(old_level)

    joined_logs = "\n".join(cap.messages)
    assert_true("[NPC_NPC_TEMPLATE]" in joined_logs, "验收点1失败：未捕获NPC_NPC_TEMPLATE日志")

    mem_a_to_b = day_impressions(gc, npc_a, npc_b)
    mem_b_to_a = day_impressions(gc, npc_b, npc_a)
    expected_memory = f"{gc.state.npcs[npc_a].name}和{gc.state.npcs[npc_b].name}在整理库存配合顺畅。"
    assert_true(any(expected_memory in m for m in mem_a_to_b), "验收点2失败：A->B记忆未写入")
    assert_true(any(expected_memory in m for m in mem_b_to_a), "验收点2失败：B->A记忆未写入")

    rel_a_after = gc.state.relationships[npc_a][npc_b]
    rel_b_after = gc.state.relationships[npc_b][npc_a]
    assert_true(rel_a_after.affinity != aff_a_before or rel_a_after.suspicion != sus_a_before, "验收点3失败：A->B关系未变化")
    assert_true(rel_b_after.affinity != aff_b_before or rel_b_after.suspicion != sus_b_before, "验收点3失败：B->A关系未变化")
    return "验收点1/2/3通过：有模板日志、双向记忆、双向关系变化。"


def check_4_blackmail_skips_pairing() -> str:
    gc = prepare_gc()
    npc_ids = list(gc.state.npcs.keys())
    npc_a, npc_b = npc_ids[0], npc_ids[1]
    same_task = make_task("task_same", "盘点样品", Room.OFFICE)

    reset_room_assignments(gc, Room.OFFICE, {npc_a, npc_b})
    gc.state.npcs[npc_a].selected_tasks = [same_task]
    gc.state.npcs[npc_b].selected_tasks = [same_task]
    gc.state.npcs[npc_a].current_task_index = 0
    gc.state.npcs[npc_b].current_task_index = 0
    gc.state.player.selected_tasks = [make_task("task_player", "写周报", Room.OFFICE)]
    gc.state.player.current_task_index = 0

    before_count = len(day_impressions(gc, npc_a, npc_b))
    logger = logging.getLogger("DoomsdayRoute")
    cap = LogCapture()
    old_level = logger.level
    logger.setLevel(logging.INFO)
    cap.setLevel(logging.INFO)
    logger.addHandler(cap)
    try:
        gc._set_hour_settlement_context(
            is_blackmail=True,
            participant_npc_ids=[],
            blackmail_listener_ids=[npc_a, npc_b],
        )
        gc._resolve_hour_bystander_and_npc_pairs()
    finally:
        logger.removeHandler(cap)
        logger.setLevel(old_level)

    after_count = len(day_impressions(gc, npc_a, npc_b))
    joined_logs = "\n".join(cap.messages)
    assert_true(after_count == before_count, "验收点4失败：黑料模式下仍发生NPC-NPC互动记忆")
    assert_true("skip pairing due to blackmail" in joined_logs, "验收点4失败：未记录黑料跳过配对日志")
    return "验收点4通过：黑料传播时已跳过NPC-NPC配对。"


def check_5_blackmail_two_memories() -> str:
    gc = prepare_gc()
    npc_ids = list(gc.state.npcs.keys())
    listener_a, listener_b, subject_id = npc_ids[0], npc_ids[1], npc_ids[2]
    subject_name = gc.state.npcs[subject_id].name
    room_name = EvidenceConverter.ROOM_NAMES.get(gc.state.player.current_room, "未知")

    gc.state.player.selected_tasks = [make_task("task_player", "整理单据", Room.OFFICE)]
    gc.state.player.current_task_index = 0

    skeleton_event = {
        "participant_npc_ids": [],
        "blackmail_broadcast_meta": {
            "listeners": [
                {"npc_id": listener_a, "subject_judgement": "这人果然有问题。"},
                {"npc_id": listener_b, "subject_judgement": "得重新评估他。"},
            ]
        },
    }
    selected_card = {
        "subject_npc_id": subject_id,
        "subject_npc_name": subject_name,
        "summary_text": "曾经私下篡改报表",
    }
    gc._build_blackmail_broadcast_group_result(
        skeleton_event=skeleton_event,
        listener_ids=[listener_a, listener_b],
        selected_card=selected_card,
        dialogues={},
        memory_summary="你进行了一次黑料传播。",
    )

    player_name = gc.state.player.name
    for listener_id, expected_judge in (
        (listener_a, "这人果然有问题。"),
        (listener_b, "得重新评估他。"),
    ):
        to_player = day_impressions(gc, listener_id, "player")
        to_subject = day_impressions(gc, listener_id, subject_id)
        expected_player_text = f"{player_name}在{room_name}分享了{subject_name}的黑料，说曾经私下篡改报表"
        assert_true(any(expected_player_text in x for x in to_player), f"验收点5失败：{listener_id}缺少对玩家的黑料记忆")
        assert_true(any(expected_judge in x for x in to_subject), f"验收点5失败：{listener_id}缺少对黑料对象的判断记忆")
    return "验收点5通过：每个听众都有“对玩家+对黑料对象”两条记忆。"


def check_6_witness_memory_uses_default() -> str:
    gc = prepare_gc()
    npc_ids = list(gc.state.npcs.keys())
    witness_id = npc_ids[0]

    reset_room_assignments(gc, Room.OFFICE, {witness_id})
    gc.state.player.selected_tasks = [make_task("task_player", "核对发票", Room.OFFICE)]
    gc.state.player.current_task_index = 0
    gc.state.npcs[witness_id].selected_tasks = [make_task("task_other", "接待访客", Room.OFFICE)]
    gc.state.npcs[witness_id].current_task_index = 0

    gc._set_hour_settlement_context(is_blackmail=False, participant_npc_ids=[])
    gc._resolve_hour_bystander_and_npc_pairs()

    witness_default = str(DataLoader().get_npc_field(witness_id, "witness_default", "")).strip() or "没怎么打过交道，先保持距离。"
    memories = day_impressions(gc, witness_id, "player")
    assert_true(any("注意到" in x and "核对发票" in x and witness_default in x for x in memories), "验收点6失败：旁观者记忆格式或witness_default不匹配")
    return "验收点6通过：旁观者记忆使用witness_default模板。"


def check_7_situation_five_only_one_participant() -> str:
    gc = prepare_gc()
    npc_ids = list(gc.state.npcs.keys())
    participant = npc_ids[0]
    other_1 = npc_ids[1]
    other_2 = npc_ids[2]

    reset_room_assignments(gc, Room.OFFICE, {participant, other_1, other_2})
    same_task = make_task("task_same", "巡检产线", Room.OFFICE)
    gc.state.player.selected_tasks = [same_task]
    gc.state.player.current_task_index = 0
    for nid in (participant, other_1, other_2):
        gc.state.npcs[nid].selected_tasks = [same_task]
        gc.state.npcs[nid].current_task_index = 0

    logger = logging.getLogger("DoomsdayRoute")
    cap = LogCapture()
    old_level = logger.level
    logger.setLevel(logging.INFO)
    cap.setLevel(logging.INFO)
    logger.addHandler(cap)
    try:
        with patch.object(
            DataLoader,
            "get_npc_npc_interaction_template",
            return_value={
                "tone": "neutral",
                "template": "{a}和{b}在{task}只做了必要沟通。",
                "affinity_delta": 1,
                "suspicion_delta": 0,
            },
        ):
            gc._set_hour_settlement_context(
                is_blackmail=False,
                participant_npc_ids=[participant],
            )
            gc._resolve_hour_bystander_and_npc_pairs()
    finally:
        logger.removeHandler(cap)
        logger.setLevel(old_level)

    template_lines = [m for m in cap.messages if "[NPC_NPC_TEMPLATE]" in m and "<->" in m]
    assert_true(all(participant not in line for line in template_lines), "验收点7失败：被选中的双人对象仍进入NPC-NPC配对")

    other_1_to_player = day_impressions(gc, other_1, "player")
    other_2_to_player = day_impressions(gc, other_2, "player")
    participant_to_player = day_impressions(gc, participant, "player")
    assert_true(any("注意到" in x for x in other_1_to_player), "验收点7失败：其余同工作NPC未写旁观记忆(other_1)")
    assert_true(any("注意到" in x for x in other_2_to_player), "验收点7失败：其余同工作NPC未写旁观记忆(other_2)")
    assert_true(not any("注意到" in x for x in participant_to_player), "验收点7失败：参与玩家双人事件的NPC不应同时被记为旁观者")
    return "验收点7通过：仅1名同工作NPC视为参与者，其余转为旁观者。"


def check_8_templates_come_from_csv() -> str:
    dl = DataLoader()
    rows = dl._fallbacks.get("f13_npc_npc_interaction", [])
    assert_true(bool(rows), "验收点8失败：未加载f13_npc_npc_interaction.csv")

    csv_templates = {str(row.get("template", "")).strip() for row in rows if str(row.get("template", "")).strip()}
    assert_true(bool(csv_templates), "验收点8失败：CSV中没有可用template")

    for _ in range(20):
        row = dl.get_npc_npc_interaction_template()
        tpl = str(row.get("template", "")).strip()
        assert_true(tpl in csv_templates, "验收点8失败：抽取模板不在CSV来源集合中")
    return "验收点8通过：模板抽取来源为CSV数据。"


def main() -> int:
    checks: list[tuple[int, str, Callable[[], str]]] = [
        (1, "房间内同工作NPC触发模板互动日志", check_1_2_3_npc_pair_log_memory_relation),
        (2, "NPC双方写入互相印象记忆", check_1_2_3_npc_pair_log_memory_relation),
        (3, "NPC双方好感/怀疑数值变化", check_1_2_3_npc_pair_log_memory_relation),
        (4, "传播黑料时跳过NPC-NPC配对", check_4_blackmail_skips_pairing),
        (5, "黑料传播后每名听众写入两条记忆", check_5_blackmail_two_memories),
        (6, "旁观者记忆使用witness_default模板", check_6_witness_memory_uses_default),
        (7, "状况五仅1名参与者，其余为旁观者", check_7_situation_five_only_one_participant),
        (8, "NPC-NPC模板来自CSV而非硬编码", check_8_templates_come_from_csv),
    ]

    results: list[CheckResult] = []
    # 1/2/3共用一次重场景，避免重复初始化噪音
    shared_123 = run_check(
        0,
        "验收点1/2/3联合检查",
        check_1_2_3_npc_pair_log_memory_relation,
    )
    for idx in (1, 2, 3):
        results.append(
            CheckResult(
                index=idx,
                title=checks[idx - 1][1],
                ok=shared_123.ok,
                detail=shared_123.detail,
            )
        )
    for idx, title, fn in checks[3:]:
        results.append(run_check(idx, title, fn))

    print("=" * 72)
    print("旁观者记忆系统 - 最小回归检查")
    print("=" * 72)
    failed = 0
    for res in results:
        flag = "PASS" if res.ok else "FAIL"
        print(f"[{flag}] 验收点{res.index} - {res.title}")
        print(f"       {res.detail}")
        if not res.ok:
            failed += 1
    print("-" * 72)
    print(f"总计: {len(results)}，通过: {len(results) - failed}，失败: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
