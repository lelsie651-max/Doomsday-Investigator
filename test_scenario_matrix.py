import asyncio
from typing import Callable

from backend.game_controller import GameController


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _build_assignment(
    npc_ids: list[str],
    *,
    same_ids: list[str],
    same_task: str,
    diff_room_task: str,
    diff_same_room_tasks: list[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    diff_cursor = 0
    for npc_id in npc_ids:
        if npc_id in same_ids:
            result[npc_id] = same_task
            continue
        if diff_cursor < len(diff_same_room_tasks):
            result[npc_id] = diff_same_room_tasks[diff_cursor]
            diff_cursor += 1
        else:
            result[npc_id] = diff_room_task
    return result


def _run_case(
    gc: GameController,
    name: str,
    setup_payload_builder: Callable[[list[str]], dict],
    expected_scenario: str,
    expected_route: str,
    expected_choice_variant: str,
) -> None:
    npc_ids = [nid for nid, npc in gc.state.npcs.items() if npc.alive]
    payload = setup_payload_builder(npc_ids)
    seeded = gc.debug_seed_work_snapshot(payload)
    _assert(seeded.get("ok", False), f"{name}: debug_seed 失败: {seeded}")

    preview = seeded.get("route_preview", {})
    _assert(preview.get("debug_scenario_code", "") == expected_scenario, f"{name}: scenario 不符: {preview}")
    _assert(preview.get("event_route", "") == expected_route, f"{name}: route 不符: {preview}")
    _assert(preview.get("choice_variant", "") == expected_choice_variant, f"{name}: choice_variant 不符: {preview}")

    if expected_route == "choice_required":
        event = gc._build_work_mode_choice_event(
            candidates=payload.get("_candidates", []),
            choice_variant=expected_choice_variant,
            duo_candidate=payload.get("_duo_candidate", {}),
            blackmail_target=payload.get("_blackmail_target", {}),
            blackmail_cards=payload.get("_blackmail_cards", []),
            debug_scenario_code=expected_scenario,
            debug_choice_source=expected_choice_variant,
        )
        options = [x.get("id", "") for x in event.get("options", [])]
        if expected_choice_variant == "duo_or_blackmail_group":
            _assert("duo" in options, f"{name}: 缺少 duo 按钮")
        elif expected_choice_variant in {"solo_or_blackmail", "solo_or_blackmail_group"}:
            _assert("solo" in options, f"{name}: 缺少 solo 按钮")
        else:
            _assert("solo" in options, f"{name}: 缺少 solo 按钮")
            _assert(any(str(x).startswith("interaction") for x in options), f"{name}: 缺少 interaction 按钮")

    print(f"✅ {name} 通过 -> scenario={expected_scenario}, route={expected_route}, choice={expected_choice_variant}")


async def main():
    gc = GameController()
    gc.new_game()
    gc.start_task_selection()

    # 统一用 office 任务构造同房场景，meeting任务用于“不同房”。
    same_task = "task_office_001"
    diff_same_room_tasks = ["task_office_002", "task_office_003", "task_office_004", "task_office_005"]
    diff_room_task = "task_meeting_001"

    # S1: 玩家独处
    _run_case(
        gc,
        "S1_玩家独处",
        lambda npc_ids: {
            "player_task_id": same_task,
            "npc_task_ids": {nid: diff_room_task for nid in npc_ids},
            "social_energy_left": 1,
            "social_event_used": False,
            "strict": True,
            "_room": "office",
            "_candidates": [],
        },
        expected_scenario="S1",
        expected_route="solo",
        expected_choice_variant="",
    )

    # S2: 房间内有且仅有1名同任务NPC
    _run_case(
        gc,
        "S2_单同任务",
        lambda npc_ids: {
            "player_task_id": same_task,
            "npc_task_ids": _build_assignment(
                npc_ids,
                same_ids=[npc_ids[0]],
                same_task=same_task,
                diff_room_task=diff_room_task,
                diff_same_room_tasks=[],
            ),
            "social_energy_left": 1,
            "social_event_used": False,
            "strict": True,
            "_room": "office",
            "_candidates": [],
        },
        expected_scenario="S2",
        expected_route="duo",
        expected_choice_variant="",
    )

    # S3: 房间内有且仅有1名不同任务NPC
    _run_case(
        gc,
        "S3_单不同任务",
        lambda npc_ids: {
            "player_task_id": same_task,
            "npc_task_ids": _build_assignment(
                npc_ids,
                same_ids=[],
                same_task=same_task,
                diff_room_task=diff_room_task,
                diff_same_room_tasks=[diff_same_room_tasks[0]],
            ),
            "social_energy_left": 1,
            "social_event_used": False,
            "strict": True,
            "_room": "office",
            "_candidates": [{"id": npc_ids[0], "name": npc_ids[0]}],
        },
        expected_scenario="S3",
        expected_route="solo",
        expected_choice_variant="",
    )

    # S4: 房间内多人且都不同任务
    _run_case(
        gc,
        "S4_多不同任务",
        lambda npc_ids: {
            "player_task_id": same_task,
            "npc_task_ids": _build_assignment(
                npc_ids,
                same_ids=[],
                same_task=same_task,
                diff_room_task=diff_room_task,
                diff_same_room_tasks=diff_same_room_tasks[:3],
            ),
            "social_energy_left": 1,
            "social_event_used": False,
            "strict": True,
            "_room": "office",
            "_candidates": [{"id": npc_ids[i], "name": npc_ids[i]} for i in range(min(3, len(npc_ids)))],
        },
        expected_scenario="S4",
        expected_route="solo",
        expected_choice_variant="",
    )

    # S5: 有同任务NPC，且房间内还有其他不同任务NPC
    _run_case(
        gc,
        "S5_同任务加他人",
        lambda npc_ids: {
            "player_task_id": same_task,
            "npc_task_ids": _build_assignment(
                npc_ids,
                same_ids=[npc_ids[0]],
                same_task=same_task,
                diff_room_task=diff_room_task,
                diff_same_room_tasks=diff_same_room_tasks[:2],
            ),
            "social_energy_left": 1,
            "social_event_used": False,
            "strict": True,
            "_room": "office",
            "_duo_candidate": {"id": npc_ids[0], "name": npc_ids[0]},
            "_candidates": [{"id": npc_ids[i], "name": npc_ids[i]} for i in range(min(3, len(npc_ids)))],
        },
        expected_scenario="S5",
        expected_route="duo",
        expected_choice_variant="",
    )

    print("\n🎉 五种状况回归矩阵通过。")


if __name__ == "__main__":
    asyncio.run(main())
