import copy
import logging
import random

from .constants import *
from .evidence_converter import EvidenceConverter
from .event_system import EventSystem
from .enums import *
from .game_state import GameState
from .data_loader import DataLoader
from .models import DailyState, RecordCard, Relationship, Task
from .movement_system import MovementSystem
from .room_system import RoomSystem
from .task_system import TaskSystem
from .vote_system import VoteSystem


class StateManager:
    """GameState 的统一操作入口"""

    def __init__(self, state: GameState):
        self.state = state
        self._change_log: list[dict] = []
        self._route_logger = logging.getLogger("DoomsdayRoute")

    @staticmethod
    def _classify_work_scenario(
        matched_npcs: list[dict],
        non_matched_npcs: list[dict],
    ) -> str:
        """
        五种状况编码：
        S1=玩家独处
        S2=仅同任务NPC
        S3=仅1名不同任务NPC
        S4=多人同房且都不同任务
        S5=同任务NPC + 其他不同任务NPC并存
        """
        matched_count = len(matched_npcs)
        non_matched_count = len(non_matched_npcs)
        total_npcs = matched_count + non_matched_count

        if total_npcs == 0:
            return "S1"
        if matched_count > 0 and non_matched_count == 0:
            return "S2"
        if matched_count == 0 and non_matched_count == 1:
            return "S3"
        if matched_count == 0 and non_matched_count >= 2:
            return "S4"
        if matched_count > 0 and non_matched_count >= 1:
            return "S5"
        return "S_UNKNOWN"

    def _emit_work_route_log(
        self,
        *,
        scenario_code: str,
        room_value: str,
        player_task_id: str,
        event_route: str,
        choice_variant: str = "",
        participant_ids: list[str] | None = None,
        observer_ids: list[str] | None = None,
    ) -> None:
        payload = {
            "scenario_code": scenario_code,
            "room": room_value,
            "player_task_id": player_task_id,
            "event_route": event_route,
            "choice_variant": choice_variant,
            "participant_npc_ids": participant_ids or [],
            "observer_npc_ids": observer_ids or [],
            "social_energy_left": int(self.state.daily.social_energy_left),
        }
        self._route_logger.info("[WORK_ROUTE] %s", payload)

    def _get_blackmail_broadcast_cards_for_target(self, target_npc_id: str) -> list[dict]:
        """
        返回在给定传播对象下可用于“传播黑料”的记录卡。
        约束：必须是已记录卡，且黑料主人存在且不等于传播对象。
        """
        cards: list[dict] = []
        for rc in self.state.player.record_cards:
            if rc.status.value != "recorded":
                continue
            if str(getattr(rc, "record_type", "")).strip().lower() != "blackmail":
                continue
            subject_id = str(getattr(rc, "subject_npc_id", "") or "").strip()
            if not subject_id or subject_id == target_npc_id:
                continue
            subject_npc = self.state.npcs.get(subject_id)
            if subject_npc is None or not getattr(subject_npc, "alive", False):
                continue
            cards.append(
                {
                    "id": rc.id,
                    "subject_npc_id": subject_id,
                    "subject_npc_name": str(getattr(rc, "subject_npc_name", "") or "").strip(),
                    "summary_text": str(getattr(rc, "summary_text", "") or "").strip(),
                }
            )
        return cards

    def _get_blackmail_broadcast_cards_for_room(self, room_npc_ids: list[str]) -> list[dict]:
        """
        返回在群体传播场景下可用的记录卡。
        约束：必须是已记录卡，且黑料主人不在当前同房NPC集合中。
        """
        room_set = {str(x).strip() for x in room_npc_ids if str(x).strip()}
        cards: list[dict] = []
        for rc in self.state.player.record_cards:
            if rc.status.value != "recorded":
                continue
            if str(getattr(rc, "record_type", "")).strip().lower() != "blackmail":
                continue
            subject_id = str(getattr(rc, "subject_npc_id", "") or "").strip()
            if not subject_id or subject_id in room_set:
                continue
            subject_npc = self.state.npcs.get(subject_id)
            if subject_npc is None or not getattr(subject_npc, "alive", False):
                continue
            cards.append(
                {
                    "id": rc.id,
                    "subject_npc_id": subject_id,
                    "subject_npc_name": str(getattr(rc, "subject_npc_name", "") or "").strip(),
                    "summary_text": str(getattr(rc, "summary_text", "") or "").strip(),
                }
            )
        return cards

    def modify_affinity(self, from_id: str, to_id: str, delta: int, reason: str = ""):
        rel = self.state.relationships[from_id][to_id]
        old_val = rel.affinity
        rel.affinity = max(-100, min(100, rel.affinity + delta))
        self._append_relationship_reason(rel, reason)
        self._log("affinity", from_id, to_id, old_val, rel.affinity)

    def modify_suspicion(self, from_id: str, to_id: str, delta: int, reason: str = ""):
        rel = self.state.relationships[from_id][to_id]
        old_val = rel.suspicion
        rel.suspicion = max(0, min(100, rel.suspicion + delta))
        self._append_relationship_reason(rel, reason)
        self._log("suspicion", from_id, to_id, old_val, rel.suspicion)

    def append_relationship_reason(self, from_id: str, to_id: str, reason: str = ""):
        rel = self.state.relationships[from_id][to_id]
        self._append_relationship_reason(rel, reason)

    @staticmethod
    def _append_relationship_reason(rel: Relationship, reason: str) -> None:
        reason_text = str(reason).strip()
        if not reason_text:
            return
        reason_text = reason_text.replace(";", "，")
        history = [item.strip() for item in rel.reason.split(";") if item.strip()]
        history.append(reason_text)
        rel.reason = ";".join(history[-3:])

    def get_affinity(self, from_id: str, to_id: str) -> int:
        return self.state.relationships[from_id][to_id].affinity

    def get_suspicion(self, from_id: str, to_id: str) -> int:
        return self.state.relationships[from_id][to_id].suspicion

    def modify_gold(self, delta: int):
        self.state.player.gold = max(0, self.state.player.gold + delta)

    def modify_battery(self, delta: int):
        self.state.player.battery = max(0, min(100, self.state.player.battery + delta))

    def add_record_card(self) -> RecordCard:
        new_id = f"rc_{len(self.state.player.record_cards) + len(self.state.evidence_collected) + 1:03d}"
        card = RecordCard(id=new_id)
        self.state.player.record_cards.append(card)
        return card

    def record_evidence(
        self,
        card_id: str,
        evidence_tag: str,
        source_desc: str,
        *,
        record_type: str = "evidence",
        subject_npc_id: str = "",
        subject_npc_name: str = "",
        summary_text: str = "",
        is_evidence: bool = False,
    ):
        normalized_type = str(record_type or "").strip().lower()
        if normalized_type not in {"evidence", "blackmail"}:
            normalized_type = "evidence"
        for card in self.state.player.record_cards:
            if card.id == card_id and card.status == RecordCardStatus.BLANK:
                card.status = RecordCardStatus.RECORDED
                card.record_type = normalized_type
                card.linked_evidence_tag = evidence_tag if normalized_type == "evidence" else ""
                card.source_description = source_desc
                card.day_recorded = self.state.current_day
                card.subject_npc_id = subject_npc_id
                card.subject_npc_name = subject_npc_name
                card.summary_text = summary_text
                card.is_evidence = bool(is_evidence) if normalized_type == "evidence" else False
                if normalized_type == "evidence":
                    self.state.evidence_collected.append(card)
                return card
        return None

    def advance_phase(self):
        phase_order = [
            GamePhase.TASK_SELECTION,
            GamePhase.WORKING,
            GamePhase.VOTING,
            GamePhase.NIGHT,
        ]
        current_index = phase_order.index(self.state.current_phase)
        if current_index < len(phase_order) - 1:
            self.state.current_phase = phase_order[current_index + 1]
        else:
            self._start_new_day()

    def _start_new_day(self):
        self.state.current_day += 1
        if self.state.current_day > TOTAL_DAYS:
            self._end_game()
            return
        self.state.current_phase = GamePhase.TASK_SELECTION
        self.state.current_hour = 0
        self.state.player.action_points = DAILY_ACTION_POINTS
        self.state.daily = DailyState()
        self.state.boss.target_npc = None
        self.state.boss.shady_evidence_tag = None

    def _end_game(self, forced_result: str = ""):
        self.state.game_over = True
        forced = str(forced_result or "").strip()
        if forced:
            self.state.game_result = forced
            return
        evidence_types = set()
        for card in self.state.evidence_collected:
            if card.linked_evidence_tag and card.linked_evidence_tag.startswith("evidence_"):
                parts = card.linked_evidence_tag.split("_", 3)
                if len(parts) >= 4:
                    evidence_types.add(parts[3])
        if len(evidence_types) >= WINNING_EVIDENCE_COUNT:
            self.state.game_result = "win"
        else:
            self.state.game_result = "fail_no_evidence"

    def eliminate_player(self):
        self.state.game_over = True
        self.state.game_result = "fail_voted_out"

    def eliminate_npc(self, npc_id: str):
        if npc_id in self.state.npcs:
            self.state.npcs[npc_id].alive = False

    def setup_daily_tasks(self):
        day = self.state.current_day
        task_pool, evidence_task_ids = TaskSystem.generate_daily_task_pool(day)
        self.state.daily.task_pool = task_pool
        self.state.daily.evidence_task_ids = evidence_task_ids
        # 新增：每日社交精力（用于“与NPC交流”互动）
        self.state.daily.social_energy_left = 1
        self.state.daily.social_event_used = False
        TaskSystem.assign_all_npcs_tasks(self.state.npcs)
        self.setup_daily_movement()

    def setup_daily_movement(self):
        self.state.daily.boss_hourly_plan = MovementSystem.generate_boss_hourly_plan(
            self.state.boss,
            self.state.current_day,
        )
        MovementSystem.move_all_to_current_tasks(
            self.state.player,
            self.state.npcs,
        )
        if self.state.daily.boss_hourly_plan:
            self._execute_boss_current_hour()

    def _execute_boss_current_hour(self) -> dict:
        hour = self.state.current_hour
        plan = self.state.daily.boss_hourly_plan
        if hour >= len(plan):
            return {}

        behavior = plan[hour]
        alive_ids = ["player"]
        for npc_id, npc in self.state.npcs.items():
            if npc.alive:
                alive_ids.append(npc_id)

        boss_result = MovementSystem.execute_boss_hour(
            self.state.boss,
            behavior,
            alive_ids,
        )

        if behavior == BossBehavior.SHADY_BUSINESS:
            day = self.state.current_day
            tag = f"evidence_day{day}_boss_{hour:03d}_corruption"
            self.state.boss.shady_evidence_tag = tag

        return {
            "boss_action": boss_result,
            "pua_interruption": None,
        }

    def player_select_tasks(self, task_ids: list[str]) -> tuple[bool, str]:
        """
        处理玩家的任务选择。

        参数:
            task_ids: 玩家选择的任务ID列表（按执行顺序）

        返回:
            (success, message)
        """
        is_valid, error_msg, selected_tasks = TaskSystem.validate_player_selection(
            task_ids,
            self.state.daily.task_pool,
            self.state.player.action_points,
        )
        if not is_valid:
            return False, error_msg

        self.state.player.selected_tasks = selected_tasks
        self.state.player.current_task_index = 0
        if selected_tasks:
            self.state.player.current_room = selected_tasks[0].room

        return True, "任务选择成功"

    def get_current_task_prompt_context(self) -> dict:
        """
        获取玩家当前任务的AI prompt上下文。

        如果当前任务是证据任务，返回包含证据信息的上下文；
        否则返回普通事件上下文。

        返回的上下文中不包含任何系统标签，AI安全。
        """
        player = self.state.player
        if player.current_task_index >= len(player.selected_tasks):
            return None

        current_task = player.selected_tasks[player.current_task_index]

        npc_names = []
        npc_personalities = []
        for npc_id, npc in self.state.npcs.items():
            if npc.alive and npc.current_room == current_task.room:
                npc_names.append(npc.name)
                npc_personalities.append(npc.personality)

        if self.state.boss.current_room == current_task.room:
            npc_names.append(self.state.boss.name)
            boss_personality = str(DataLoader().get_npc_field("boss", "personality", "")).strip()
            npc_personalities.append(boss_personality or "未知性格")

        if current_task.evidence_tag is not None and current_task.evidence_type is not None:
            return EvidenceConverter.to_ai_prompt_context(
                evidence_type=current_task.evidence_type,
                room=current_task.room,
                task_name=current_task.name,
                npc_names=npc_names,
                npc_personalities=npc_personalities,
            )

        return EvidenceConverter.make_ai_safe_context(
            {
                "is_evidence_event": False,
                "scene_location": EvidenceConverter.ROOM_NAMES[current_task.room],
                "task_description": current_task.name,
                "npcs_present": npc_names,
                "npcs_personalities": npc_personalities,
            }
        )

    def trigger_event(self) -> dict | None:
        player = self.state.player
        if player.current_task_index >= len(player.selected_tasks):
            return None

        current_task = player.selected_tasks[player.current_task_index]
        event = EventSystem.select_event(
            current_task.room,
            self.state.daily.events_triggered,
        )
        if event is None:
            return None

        self.state.daily.events_triggered.append(event["id"])
        emotions, actions = EventSystem.draw_cards()
        self.state.player.hand_emotions = [card["id"] for card in emotions]
        self.state.player.hand_actions = [card["id"] for card in actions]

        is_evidence = current_task.evidence_tag is not None
        evidence_type_val = (
            current_task.evidence_type.value if current_task.evidence_type else None
        )

        return EventSystem.build_event_display(
            event,
            emotions,
            actions,
            is_evidence_task=is_evidence,
            evidence_type_value=evidence_type_val,
        )

    def trigger_skeleton_event(
        self,
        force_mode: str = "auto",
        interaction_target_npc_id: str = "",
    ) -> dict | None:
        """
        新版事件触发：基于骨架+元素池动态拼装。

        返回拼装好的骨架事件数据，供game_controller调用AI生成Act 1。
        如果没有可用骨架，返回None（会fallback到旧版trigger_event）。
        """
        from .event_system import EventSystem
        from .room_system import RoomSystem

        player = self.state.player
        if player.current_task_index >= len(player.selected_tasks):
            return None

        current_task = player.selected_tasks[player.current_task_index]
        current_room = current_task.room

        # 获取当前房间的NPC信息
        room_info = RoomSystem.get_room_occupants(
            player, self.state.npcs, self.state.boss, current_room
        )

        npcs_in_room = room_info["npc_details"]  # [{"id", "name", "personality"}]

        # 新规则：仅“同房间 + 同工作内容”的NPC可与玩家触发双人事件。
        # 若同房间NPC的当前任务与玩家不同，则视为不参与当前事件。
        player_task_id = getattr(current_task, "id", "")
        matched_npcs = []
        for npc_info in npcs_in_room:
            npc_id = npc_info.get("id", "")
            npc_state = self.state.npcs.get(npc_id)
            if not npc_state or not npc_state.alive:
                continue
            idx = npc_state.current_task_index
            if idx < 0 or idx >= len(npc_state.selected_tasks):
                continue
            npc_task = npc_state.selected_tasks[idx]
            if getattr(npc_task, "id", "") == player_task_id:
                matched_npcs.append(npc_info)

        # 非同任务NPC（可作为互动候选）
        non_matched_npcs = []
        for npc_info in npcs_in_room:
            if npc_info not in matched_npcs:
                non_matched_npcs.append(npc_info)
        scenario_code = self._classify_work_scenario(matched_npcs, non_matched_npcs)
        room_value = current_room.value if hasattr(current_room, "value") else str(current_room)

        event_route = "solo"
        npcs_for_event = []
        observer_npcs: list[dict] = []
        social_event_consumed = False
        social_event_locked = bool(self.state.daily.social_event_used)

        # 判定规范：
        # 1) 先看同房间+同任务，命中则直接双人
        # 2) 若无同任务但有NPC，且有社交精力，返回“需选择”
        # 3) 若无精力或无人，走单人
        if force_mode == "duo_any_roommate":
            # 强制双人（不看任务是否一致）：只要同房有NPC就走duo主线。
            if interaction_target_npc_id:
                for npc in npcs_in_room:
                    if npc.get("id") == interaction_target_npc_id:
                        npcs_for_event = [npc]
                        break
            if not npcs_for_event and npcs_in_room:
                npcs_for_event = [random.choice(npcs_in_room)]
            if npcs_for_event:
                event_route = "duo"
                observer_npcs = [
                    x for x in npcs_in_room if x.get("id") != npcs_for_event[0].get("id")
                ]
                social_event_consumed = False
            else:
                event_route = "solo"
                observer_npcs = []
        elif force_mode == "interaction":
            if interaction_target_npc_id:
                for npc in non_matched_npcs:
                    if npc.get("id") == interaction_target_npc_id:
                        npcs_for_event = [npc]
                        break
            if npcs_for_event:
                event_route = "interaction"
                social_event_consumed = True
                observer_npcs = [
                    x for x in npcs_in_room if x.get("id") != npcs_for_event[0].get("id")
                ]
            else:
                event_route = "solo"
                observer_npcs = []
        elif force_mode == "duo":
            if interaction_target_npc_id:
                for npc in matched_npcs:
                    if npc.get("id") == interaction_target_npc_id:
                        npcs_for_event = [npc]
                        break
            if not npcs_for_event and matched_npcs:
                npcs_for_event = [random.choice(matched_npcs)]
            if npcs_for_event:
                event_route = "duo"
                observer_npcs = [
                    x for x in npcs_in_room if x.get("id") != npcs_for_event[0].get("id")
                ]
                # 状况5专用“duo主线”不消耗社交预算，避免玩家选择“继续双人”也被计次。
                social_event_consumed = False
            else:
                event_route = "solo"
                observer_npcs = []
        elif force_mode == "solo":
            npcs_for_event = []
            event_route = "solo"
            if non_matched_npcs and not matched_npcs and not social_event_locked:
                # 状况3/4：玩家选择“自己干自己的”，仍属于社交态势事件（计入每日限制）
                social_event_consumed = True
                observer_npcs = list(non_matched_npcs)
            else:
                observer_npcs = []
        else:
            if matched_npcs:
                npcs_for_event = [random.choice(matched_npcs)]
                event_route = "duo"
                extra_npcs = [
                    x for x in npcs_in_room if x.get("id") != npcs_for_event[0].get("id")
                ]
                # 状况5改造：若可传播黑料，则给“继续双人/群体传播黑料”选择。
                if (
                    extra_npcs
                    and self.state.daily.social_energy_left > 0
                    and not social_event_locked
                ):
                    room_npc_ids = [str(x.get("id", "")).strip() for x in npcs_in_room if str(x.get("id", "")).strip()]
                    available_cards = self._get_blackmail_broadcast_cards_for_room(room_npc_ids)
                    if available_cards:
                        self._emit_work_route_log(
                            scenario_code=scenario_code,
                            room_value=room_value,
                            player_task_id=player_task_id,
                            event_route="choice_required",
                            choice_variant="duo_or_blackmail_group",
                            participant_ids=[npcs_for_event[0].get("id", "")],
                            observer_ids=room_npc_ids,
                        )
                        return {
                            "event_route": "choice_required",
                            "choice_variant": "duo_or_blackmail_group",
                            "room": room_value,
                            "duo_candidate": npcs_for_event[0],
                            "blackmail_targets": npcs_in_room,
                            "blackmail_room_npc_ids": room_npc_ids,
                            "social_energy_left": self.state.daily.social_energy_left,
                            "debug_scenario_code": scenario_code,
                            "debug_choice_source": "duo_or_blackmail_group",
                        }
                observer_npcs = extra_npcs
            elif non_matched_npcs and self.state.daily.social_energy_left > 0:
                # 状况3/4：若当天尚未发生社交态势事件，则给玩家“单干/交流”选择
                if not social_event_locked:
                    # 状况3改造：仅在“可传播黑料”存在时提供“自己干活/传播黑料”。
                    if len(non_matched_npcs) == 1:
                        target = non_matched_npcs[0]
                        target_id = str(target.get("id", "")).strip()
                        available_cards = self._get_blackmail_broadcast_cards_for_target(target_id)
                        if available_cards:
                            self._emit_work_route_log(
                                scenario_code=scenario_code,
                                room_value=room_value,
                                player_task_id=player_task_id,
                                event_route="choice_required",
                                choice_variant="solo_or_blackmail",
                                participant_ids=[],
                                observer_ids=[target_id] if target_id else [],
                            )
                            return {
                                "event_route": "choice_required",
                                "choice_variant": "solo_or_blackmail",
                                "room": room_value,
                                "blackmail_target": target,
                                "social_energy_left": self.state.daily.social_energy_left,
                                "debug_scenario_code": scenario_code,
                                "debug_choice_source": "solo_or_blackmail",
                            }
                        # 没有可传播黑料时，直接单人，不再展示“交流/传播”选择。
                        npcs_for_event = []
                        event_route = "solo"
                        observer_npcs = []
                        social_event_consumed = False
                        # 直接走后续骨架拼装，不return
                    else:
                        room_npc_ids = [str(x.get("id", "")).strip() for x in non_matched_npcs if str(x.get("id", "")).strip()]
                        available_cards = self._get_blackmail_broadcast_cards_for_room(room_npc_ids)
                        if available_cards:
                            self._emit_work_route_log(
                                scenario_code=scenario_code,
                                room_value=room_value,
                                player_task_id=player_task_id,
                                event_route="choice_required",
                                choice_variant="solo_or_blackmail_group",
                                participant_ids=[],
                                observer_ids=room_npc_ids,
                            )
                            return {
                                "event_route": "choice_required",
                                "choice_variant": "solo_or_blackmail_group",
                                "room": room_value,
                                "blackmail_targets": non_matched_npcs,
                                "blackmail_room_npc_ids": room_npc_ids,
                                "social_energy_left": self.state.daily.social_energy_left,
                                "debug_scenario_code": scenario_code,
                                "debug_choice_source": "solo_or_blackmail_group",
                            }
                        # 没有可传播黑料时，直接单人，不再展示“交流/传播”选择。
                        npcs_for_event = []
                        event_route = "solo"
                        observer_npcs = []
                        social_event_consumed = False
                # 每日限制已触发：降级为纯单人，不再触发交流/旁观扩展
                npcs_for_event = []
                event_route = "solo"
                observer_npcs = []
            else:
                npcs_for_event = []
                event_route = "solo"
                observer_npcs = []

        boss_in_room = False

        # 尝试骨架拼装
        selected_task_id = player_task_id
        skeleton_event = EventSystem.select_skeleton_event(
            current_room,
            selected_task_id,
            event_route,
            npcs_for_event,
            boss_in_room,
            self.state.daily.events_triggered,
        )

        if skeleton_event is None:
            self._emit_work_route_log(
                scenario_code=scenario_code,
                room_value=room_value,
                player_task_id=player_task_id,
                event_route=f"{event_route}_no_skeleton",
                choice_variant="",
                participant_ids=[x.get("id", "") for x in npcs_for_event if x.get("id")],
                observer_ids=[x.get("id", "") for x in observer_npcs if x.get("id")],
            )
            return None  # 没有可用骨架，caller会fallback

        # 记录已触发
        self.state.daily.events_triggered.append(skeleton_event["skeleton_id"])

        # 证据信息（先于抽牌标记计算 is_evidence）
        is_evidence = current_task.evidence_tag is not None

        # 抽牌（复用现有逻辑）
        emotions, actions = EventSystem.draw_cards()
        # 证据任务：在 5 情绪 / 5 行动 中各标记 2 张为"证据触发牌"。
        EventSystem.apply_evidence_marks_v2(emotions, is_evidence_task=is_evidence)
        EventSystem.apply_evidence_marks_v2(actions, is_evidence_task=is_evidence)
        self.state.player.hand_emotions = [card["id"] for card in emotions]
        self.state.player.hand_actions = [card["id"] for card in actions]

        # 把抽到的牌信息附加到事件数据上
        skeleton_event["drawn_emotions"] = emotions
        skeleton_event["drawn_actions"] = actions

        skeleton_event["is_evidence_task"] = is_evidence
        skeleton_event["current_evidence_tag"] = current_task.evidence_tag
        if is_evidence and current_task.evidence_type:
            skeleton_event["evidence_type_value"] = current_task.evidence_type.value
        else:
            skeleton_event["evidence_type_value"] = None
        skeleton_event["event_route"] = event_route
        skeleton_event["debug_scenario_code"] = scenario_code
        skeleton_event["debug_choice_source"] = event_route
        skeleton_event["participant_npc_ids"] = [
            x.get("id", "") for x in npcs_for_event if x.get("id")
        ]
        skeleton_event["observer_npc_ids"] = [
            x.get("id", "") for x in observer_npcs if x.get("id")
        ]
        skeleton_event["social_event_consumed"] = social_event_consumed
        if social_event_consumed:
            self.state.daily.social_event_used = True

        self._emit_work_route_log(
            scenario_code=scenario_code,
            room_value=room_value,
            player_task_id=player_task_id,
            event_route=event_route,
            choice_variant="",
            participant_ids=skeleton_event["participant_npc_ids"],
            observer_ids=skeleton_event["observer_npc_ids"],
        )

        return skeleton_event

    def resolve_player_cards(self, emotion_id: str, action_id: str) -> dict:
        if emotion_id not in self.state.player.hand_emotions:
            return {"error": f"情绪卡{emotion_id}不在手牌中"}
        if action_id not in self.state.player.hand_actions:
            return {"error": f"行动卡{action_id}不在手牌中"}

        result = EventSystem.resolve_event(emotion_id, action_id)
        coworkers = self.get_player_coworkers()
        for npc_id in coworkers["npc_ids"]:
            self.modify_affinity(npc_id, "player", result["affinity_delta"])
            self.modify_suspicion(npc_id, "player", result["suspicion_delta"])

        if coworkers["boss_present"]:
            self.modify_suspicion("boss", "player", result["suspicion_delta"])

        if result["gold_delta"] != 0:
            self.modify_gold(result["gold_delta"])

        self.state.player.hand_emotions = []
        self.state.player.hand_actions = []

        current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
        result["is_evidence_task"] = current_task.evidence_tag is not None
        result["current_evidence_tag"] = current_task.evidence_tag
        return result

    def use_record_card_on_event(
        self,
        card_id: str,
        *,
        record_type: str = "evidence",
        subject_npc_id: str = "",
        subject_npc_name: str = "",
        summary_text: str = "",
        is_evidence: bool = False,
        evidence_triggered: bool = True,
    ) -> dict:
        """
        evidence_triggered: 本次事件是否触发了证据线索（玩家是否选中了证据标记牌）。
            - True（默认，向后兼容）：按照 current_task 绑定 evidence_tag。
            - False：即便 record_type=="evidence" 也不绑 tag，相当于"记了个寂寞"，
              卡牌进证据列表但 linked_evidence_tag 为空，不计入有效证据。
        """
        normalized_type = str(record_type or "").strip().lower()
        if normalized_type not in {"evidence", "blackmail"}:
            return {
                "success": False,
                "message": "record_type 仅支持 evidence 或 blackmail",
            }
        current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
        if normalized_type == "evidence" and evidence_triggered:
            evidence_tag = current_task.evidence_tag or ""
        else:
            evidence_tag = ""
        source_desc = f"{current_task.room.value}-{current_task.name}"

        # 未触发证据时，card.is_evidence 也强制 False，以免被算作有效证据。
        is_evidence_final = (
            bool(is_evidence) and evidence_triggered
            if normalized_type == "evidence"
            else False
        )
        card = self.record_evidence(
            card_id,
            evidence_tag,
            source_desc,
            record_type=normalized_type,
            subject_npc_id=subject_npc_id,
            subject_npc_name=subject_npc_name,
            summary_text=summary_text,
            is_evidence=is_evidence_final,
        )
        if card is None:
            return {
                "success": False,
                "message": "没有找到可用的空白记录卡",
            }

        if normalized_type == "blackmail":
            return {
                "success": True,
                "message": "你把这段内容记成了黑料，先收好，关键时刻再放出去。",
                "evidence_count": len(self.state.evidence_collected),
            }
        return {
            "success": True,
            "message": "录音笔发出“嘀”的一声，红灯亮了。不知道录下了什么，但听起来像是某种能让人坐牢的东西。",
            "evidence_count": len(self.state.evidence_collected),
        }

    def validate_player_vote(self, target_npc_id: str) -> tuple[bool, str]:
        if target_npc_id == "player":
            return False, "不能投自己"

        if target_npc_id == "boss":
            return False, "不能投经理（他是裁判）"

        if target_npc_id not in self.state.npcs:
            return False, f"目标 {target_npc_id} 不存在"
        if not self.state.npcs[target_npc_id].alive:
            return False, f"{self.state.npcs[target_npc_id].name} 已经出局了"

        return True, ""

    def execute_vote(self, player_vote_target: str) -> dict:
        is_valid, error = self.validate_player_vote(player_vote_target)
        if not is_valid:
            return {"error": error}

        result = VoteSystem.execute_full_vote(
            player_vote_target,
            self.state.npcs,
            self.state.boss,
            self.state.relationships,
            current_day=self.state.current_day,
        )

        self.state.daily.vote_record = result["vote_record"]
        self.state.daily.vote_result = result["target"]

        if result["is_tie"]:
            result["outcome_text"] = (
                "票数持平！经理不耐烦地挥了挥触手：“今天算你们走运，滚回去睡觉！明天给我投出个结果来！”"
            )
        elif result["player_eliminated"]:
            self.eliminate_player()
            result["outcome_text"] = (
                "所有人的目光都聚焦在你身上。经理缓缓站起来，八条触手在空中舞动：“看来大家的眼睛是雪亮的。来吧，我们去会议室好好聊聊……”你的调查员生涯到此结束了。"
            )
        else:
            target_id = result["target"]
            target_name = result["target_name"]
            self.eliminate_npc(target_id)
            result["outcome_text"] = (
                f"所有人的手指都指向了{target_name}。"
                f"经理露出了满意的微笑：“很好，{target_name}，跟我来办公室坐坐。”"
                f"在{target_name}被拖走的时候，你看到他/她的眼神里写满了不甘……"
                f"但你现在没空同情，因为明天还得继续活下去。"
            )

        return result

    def get_vote_candidates_for_frontend(self) -> list[dict]:
        candidates = []
        for npc_id, npc in self.state.npcs.items():
            if npc.alive:
                candidates.append(
                    {
                        "id": npc_id,
                        "name": npc.name,
                        "species": npc.species,
                    }
                )
        return candidates

    def advance_task(self):
        self.advance_hour()

    def advance_hour(self) -> dict:
        state = self.state
        player = state.player
        player.current_task_index += 1
        for npc_id, npc in state.npcs.items():
            if npc.alive:
                npc.current_task_index += 1

        state.current_hour += 1
        day_ended = (
            state.current_hour >= len(player.selected_tasks)
            or player.current_task_index >= len(player.selected_tasks)
        )
        if day_ended:
            return {
                "hour": state.current_hour,
                "day_ended": True,
                "player_room": player.current_room.value,
                "room_snapshot": {},
                "boss_action": {},
                "pua_interruption": None,
                "player_coworkers": {},
            }

        MovementSystem.move_all_to_current_tasks(player, state.npcs)
        boss_result = self._execute_boss_current_hour()
        room_snapshot = RoomSystem.get_all_room_occupants(
            player,
            state.npcs,
            state.boss,
        )
        player_coworkers = RoomSystem.get_player_coworkers(
            player,
            state.npcs,
            state.boss,
        )

        return {
            "hour": state.current_hour,
            "day_ended": False,
            "player_room": player.current_room.value,
            "room_snapshot": room_snapshot,
            "boss_action": boss_result.get("boss_action", {}),
            "pua_interruption": boss_result.get("pua_interruption"),
            "player_coworkers": player_coworkers,
        }

    def get_task_pool_for_frontend(self) -> list[dict]:
        """
        将当日任务池转换为前端可展示的格式。
        注意：不暴露evidence_tag和evidence_type给前端。
        """
        result = []
        for task in self.state.daily.task_pool:
            result.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "room": task.room.value,
                    "duration": task.duration,
                    "reward_type": task.reward_type.value,
                    "risk_tag": task.risk_tag,
                }
            )
        return result

    def get_room_snapshot(self) -> dict[str, dict]:
        return RoomSystem.get_all_room_occupants(
            self.state.player,
            self.state.npcs,
            self.state.boss,
        )

    def get_player_coworkers(self) -> dict:
        return RoomSystem.get_player_coworkers(
            self.state.player,
            self.state.npcs,
            self.state.boss,
        )

    def get_all_positions(self) -> dict[str, str]:
        return RoomSystem.get_positions_for_frontend(
            self.state.player,
            self.state.npcs,
            self.state.boss,
        )

    def _log(self, field: str, from_id: str, to_id: str, old_val, new_val):
        self._change_log.append(
            {
                "field": field,
                "from": from_id,
                "to": to_id,
                "old": old_val,
                "new": new_val,
            }
        )

    def flush_changes(self) -> list[dict]:
        changes = self._change_log.copy()
        self._change_log.clear()
        return changes

    def to_frontend_state(self) -> dict:
        return {
            "current_day": self.state.current_day,
            "current_phase": self.state.current_phase.value,
            "current_hour": self.state.current_hour,
            "game_over": self.state.game_over,
            "game_result": self.state.game_result,
            "player": {
                "gold": self.state.player.gold,
                "action_points": self.state.player.action_points,
                "current_room": self.state.player.current_room.value,
                "battery": self.state.player.battery,
                "record_cards_count": len(self.state.player.record_cards),
                "items": self.state.player.items,
            },
            "positions": self._get_all_positions(),
            "boss": {
                "current_room": self.state.boss.current_room.value,
            },
        }

    def _get_all_positions(self) -> dict[str, str]:
        return self.get_all_positions()
