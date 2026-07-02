"""
事件系统 v2 - 骨架拼装 + 5档Combo判定

核心变化（相对v1）：
1. 事件不再从固定模板中选取，而是从骨架+元素池动态拼装
2. Combo从3档(steady/contrast/crazy)升级为5档
3. NPC反应由NPC反应档案驱动，不由AI判断
4. 卡牌抽取逻辑保持不变
"""

import math
import random

from .constants import ACTION_CARDS, EMOTION_CARDS, SOLO_ACTION_CARDS
from .data_loader import DataLoader
from .enums import Room
# DEPRECATED: 兼容用 fallback,新功能勿用,详见 event_templates.py 文件头
from .event_templates import EVIDENCE_HINT_TEXTS, EVENT_TEMPLATES, RESULT_TEMPLATES
from .models import BossState, NPCState, PlayerState, RecordCard


class EventSystem:
    """事件系统v2"""

    # ==========================================
    # 卡牌抽取（保持不变）
    # ==========================================

    @staticmethod
    def draw_cards() -> tuple[list[dict], list[dict]]:
        """抽取5张情绪卡+5张行动卡"""
        emotion_pool = [
            {
                "id": c.id,
                "name": c.name,
                "tone": c.tone,
                "is_normal": c.is_normal,
                "style": c.style,
            }
            for c in EMOTION_CARDS
        ]
        action_pool = [
            {
                "id": c.id,
                "name": c.name,
                "effect": c.effect,
                "is_normal": c.is_normal,
                "style": c.style,
            }
            for c in ACTION_CARDS
        ]

        drawn_emotions = random.sample(emotion_pool, 5)
        drawn_actions = random.sample(action_pool, 5)
        return drawn_emotions, drawn_actions

    @staticmethod
    def draw_solo_action_cards(count: int = 5, is_evidence_task: bool = False) -> list[dict]:
        """单人事件抽取行为牌（默认5选1）。

        当 is_evidence_task=True 时，自动调用 apply_evidence_marks_v2 标记
        2 张作为"能拿到证据线索"的关键牌（优先非 normal 风格）。
        """
        pool = [
            {
                "id": c.id,
                "name": c.name,
                "effect": c.effect,
                "tone": c.tone,
                "is_normal": c.is_normal,
                "style": c.style,
                "peek_risk": c.peek_risk,
                "peek_affinity_bias": c.peek_affinity_bias,
                "peek_suspicion_bias": c.peek_suspicion_bias,
            }
            for c in SOLO_ACTION_CARDS
        ]
        draw_count = min(max(count, 1), len(pool))
        cards = random.sample(pool, draw_count)
        EventSystem.apply_evidence_marks_v2(cards, is_evidence_task=is_evidence_task)
        return cards

    @staticmethod
    def apply_evidence_marks_v2(
        cards: list[dict],
        is_evidence_task: bool,
        mark_count: int = 2,
    ) -> None:
        """
        在抽出的卡牌列表上原地标记 evidence_marked 字段。

        - 非证据任务：所有卡 evidence_marked=False
        - 证据任务：随机标记 mark_count 张，优先选 style != "normal" 的卡，
          凑不够时再用 normal 风格补足。

        设计意图：让玩家面临"选安全牌（normal）拿不到证据 vs 选危险牌
        （chaotic/rebel/corporate）能拿证据但会被怀疑"的策略抉择。
        """
        if not cards:
            return
        for c in cards:
            c["evidence_marked"] = False
        if not is_evidence_task or mark_count <= 0:
            return
        non_normal = [c for c in cards if str(c.get("style", "normal")).strip().lower() != "normal"]
        normal = [c for c in cards if str(c.get("style", "normal")).strip().lower() == "normal"]
        random.shuffle(non_normal)
        random.shuffle(normal)
        ordered = non_normal + normal
        for c in ordered[: min(mark_count, len(ordered))]:
            c["evidence_marked"] = True

    @staticmethod
    def classify_combo(emotion_id: str, action_id: str) -> str:
        """
        基于卡牌style标签的5档Combo判定。

        优先级：crazy > comply > rebel > steady > contrast（兜底）

        返回:
            "crazy" / "comply" / "rebel" / "steady" / "contrast"
        """
        # 获取style
        e_style = EventSystem._get_card_style(emotion_id, "emotion")
        a_style = EventSystem._get_card_style(action_id, "action")

        # 判定（按优先级从高到低）
        if e_style == "chaotic" and a_style == "chaotic":
            return "crazy"
        if (
            "corporate" in (e_style, a_style)
            and "rebel" not in (e_style, a_style)
            and "chaotic" not in (e_style, a_style)
        ):
            return "comply"
        if "rebel" in (e_style, a_style) and "chaotic" not in (e_style, a_style):
            return "rebel"
        if e_style == "normal" and a_style == "normal":
            return "steady"
        return "contrast"

    @staticmethod
    def _get_card_style(card_id: str, card_type: str) -> str:
        """获取卡牌style，优先读取DataLoader，缺失时从已加载卡牌数据回退。"""
        dl = DataLoader()
        style = dl.get_card_style(card_id)
        cards = EMOTION_CARDS if card_type == "emotion" else ACTION_CARDS
        for card in cards:
            if card.id == card_id:
                # DataLoader可能未配置该卡（会返回normal），此时以实际卡牌定义为准
                return style if style != "normal" else card.style
        return "normal"

    @staticmethod
    def classify_combination(emotion_id: str, action_id: str) -> str:
        """兼容旧调用，转发到v2方法。"""
        return EventSystem.classify_combo(emotion_id, action_id)

    @staticmethod
    def build_solo_event(
        room: str,
        solo_actions: list[dict],
        is_evidence_task: bool = False,
        evidence_type_value: str | None = None,
        scene_override: str | None = None,
        event_id: str | None = None,
        event_name: str | None = None,
    ) -> dict:
        """
        构建独自事件（房间无NPC时）。
        单人文案由骨架文本提供，不再从elements池读取。
        """
        from .event_templates import EVIDENCE_HINT_TEXTS

        scene = scene_override or "四周安静得有些不对劲。你觉得自己正在被某种看不见的东西注视着。"
        if not scene:
            scene = "四周安静得有些不对劲。你觉得自己正在被某种看不见的东西注视着。"

        display = {
            "event_id": event_id or f"SOLO_{room.upper()}",
            "event_name": event_name or "独自一人",
            "description": scene,
            "prompt": "",
            "emotion_cards": [],
            "action_cards": solo_actions,
            "solo_action_cards": solo_actions,
            "card_mode": "solo_action",
            "has_evidence_hint": False,
            "evidence_hint": "",
            "is_solo_event": True,
        }

        if is_evidence_task and evidence_type_value:
            hints = EVIDENCE_HINT_TEXTS.get(evidence_type_value, [])
            if hints:
                display["has_evidence_hint"] = True
                display["evidence_hint"] = random.choice(hints)

        return display

    # ==========================================
    # 骨架事件选择与拼装（新）
    # ==========================================

    @staticmethod
    def select_skeleton_event(
        room: Room,
        task_id: str,
        event_route: str,
        npcs_in_room: list[dict],
        boss_in_room: bool,
        triggered_today: list[str],
    ) -> dict | None:
        """
        选择并拼装一个骨架事件。

        参数:
            room: 当前房间
            task_id: 当前任务ID（如 task_office_001）
            event_route: 事件路线（"duo"/"solo"/"interaction"）
            npcs_in_room: 房间内NPC列表 [{"id": "npc_xxx", "name": "某同事", ...}]
            boss_in_room: 经理是否在场
            triggered_today: 今日已触发的骨架ID列表

        返回:
            拼装好的事件dict，或None
        """
        dl = DataLoader()
        room_value = room.value if isinstance(room, Room) else room

        # 事件使用“按地点文件 + 按task + 按事件类型”筛选
        skeletons = dl.get_skeletons_for_room_task(room_value, task_id, event_route)
        if not skeletons:
            return None

        # 筛选：仅排除今日已触发的骨架
        candidates = []
        for sk in skeletons:
            sk_id = sk["id"]
            if sk_id not in triggered_today:
                candidates.append(sk)

        # 如果全部触发过了，允许重复
        if not candidates:
            candidates = list(skeletons)

        if not candidates:
            return None

        skeleton = random.choice(candidates)

        # 分配NPC角色
        primary_npc = EventSystem._assign_npc_roles(npcs_in_room, boss_in_room)
        primary_name = primary_npc["name"] if primary_npc else "某人"

        # 非duo模式骨架通常不显式配置room，这里注入当前房间用于元素池替换
        skeleton_for_assemble = dict(skeleton)
        skeleton_for_assemble["room"] = room_value
        assembled_seed = dl.assemble_seed(skeleton_for_assemble, primary_name)

        return {
            "skeleton_id": skeleton["id"],
            "event_name": "工作突发事件",
            "assembled_seed": assembled_seed,
            "room": room_value,
            "primary_npc": primary_npc,
            "evidence_type": skeleton.get("evidence_type"),
            "evidence_hint": skeleton.get("evidence_hint", ""),
        }

    @staticmethod
    def _assign_npc_roles(
        npcs_in_room: list[dict],
        boss_in_room: bool,
    ) -> dict | None:
        """
        分配事件角色：只保留一个primary。

        参数:
            npcs_in_room: [{"id": "npc_xxx", "name": "某同事", "personality": "..."}]
            boss_in_room: 经理是否在场

        返回:
            primary_npc_dict
        """
        all_npcs = list(npcs_in_room)
        if boss_in_room:
            dl = DataLoader()
            boss_name = str(dl.get_npc_field("boss", "display_name", dl.get_npc_field("boss", "name", "经理"))).strip() or "经理"
            boss_personality = str(dl.get_npc_field("boss", "personality", "未知性格")).strip() or "未知性格"
            all_npcs.append({
                "id": "boss",
                "name": boss_name,
                "personality": boss_personality,
            })

        if not all_npcs:
            return None

        primary = random.choice(all_npcs)

        # MVP硬限制：事件只允许「玩家 + 1名NPC」。
        return primary

    # ==========================================
    # NPC反应结算（新）
    # ==========================================

    @staticmethod
    def resolve_npc_reactions(
        combo: str,
        primary_npc_id: str,
    ) -> dict:
        """
        根据combo类型和NPC反应档案，计算所有NPC的数值变化和thought。

        参数:
            combo: "steady"/"comply"/"rebel"/"contrast"/"crazy"
            primary_npc_id: 主角NPC的ID

        返回:
            {
                "primary": {
                    "npc_id": str,
                    "affinity_delta": int,
                    "suspicion_delta": int,
                    "thought": str,
                },
            }
        """
        dl = DataLoader()

        # Primary
        p_reaction = dl.get_npc_reaction(primary_npc_id, combo)
        p_aff = int(p_reaction["affinity"])
        p_sus = int(p_reaction["suspicion"])

        return {
            "primary": {
                "npc_id": primary_npc_id,
                "affinity_delta": p_aff,
                "suspicion_delta": p_sus,
                "thought": p_reaction["thought"],
                # 兼容旧字段，后续可移除
                "tone": p_reaction["thought"],
            }
        }

    # ==========================================
    # 构建前端展示数据（兼容旧接口）
    # ==========================================

    @staticmethod
    def build_event_display_v2(
        skeleton_event: dict,
        act1_text: str,
        emotions: list[dict],
        actions: list[dict],
        is_evidence_task: bool = False,
        evidence_type_value: str | None = None,
    ) -> dict:
        """
        构建发给前端的事件展示数据。

        参数:
            skeleton_event: select_skeleton_event()的返回值
            act1_text: AI生成的Act 1文本（或fallback文本）
            emotions: 抽到的5张情绪卡
            actions: 抽到的5张行动卡

        返回:
            和旧版 build_event_display 兼容的dict
        """
        from .event_templates import EVIDENCE_HINT_TEXTS

        display = {
            "event_id": skeleton_event["skeleton_id"],
            "event_name": skeleton_event["event_name"],
            "description": act1_text,
            "prompt": "",  # Act 1已包含结尾困境，不需要额外prompt
            "emotion_cards": emotions,
            "action_cards": actions,
            "has_evidence_hint": False,
            "evidence_hint": "",
        }

        if is_evidence_task and evidence_type_value:
            hints = EVIDENCE_HINT_TEXTS.get(evidence_type_value, [])
            if hints:
                display["has_evidence_hint"] = True
                display["evidence_hint"] = random.choice(hints)

        return display

    # ==========================================
    # 旧接口兼容（保留，逐步废弃）
    # ==========================================

    @staticmethod
    def select_event(room: Room, triggered_today: list[str]) -> dict | None:
        """旧版事件选择，保留兼容"""
        from .event_templates import EVENT_TEMPLATES
        candidates = [
            event for event in EVENT_TEMPLATES
            if event["room"] == room.value and event["id"] not in triggered_today
        ]
        if not candidates:
            candidates = [event for event in EVENT_TEMPLATES if event["room"] == room.value]
        if not candidates:
            return None
        return random.choice(candidates)

    @staticmethod
    def build_event_display(
        event: dict, emotions: list[dict], actions: list[dict],
        is_evidence_task: bool = False, evidence_type_value: str | None = None,
    ) -> dict:
        """旧版事件展示，保留兼容"""
        from .event_templates import EVIDENCE_HINT_TEXTS
        display = {
            "event_id": event["id"],
            "event_name": event["name"],
            "description": event["description"],
            "prompt": event["prompt_to_player"],
            "emotion_cards": emotions,
            "action_cards": actions,
            "has_evidence_hint": False,
            "evidence_hint": "",
        }
        if is_evidence_task and evidence_type_value:
            hints = EVIDENCE_HINT_TEXTS.get(evidence_type_value, [])
            if hints:
                display["has_evidence_hint"] = True
                display["evidence_hint"] = random.choice(hints)
        return display

    @staticmethod
    def resolve_event(emotion_id: str, action_id: str) -> dict:
        """旧版事件结算，保留兼容"""
        from .event_templates import RESULT_TEMPLATES
        combo_type = EventSystem.classify_combo(emotion_id, action_id)
        template = random.choice(RESULT_TEMPLATES.get(combo_type, RESULT_TEMPLATES.get("contrast", [{"text": "...", "affinity_delta": 0, "suspicion_delta": 0, "gold_delta": 0}])))

        emotion_name = emotion_id
        for card in EMOTION_CARDS:
            if card.id == emotion_id:
                emotion_name = card.name
                break
        action_name = action_id
        for card in ACTION_CARDS:
            if card.id == action_id:
                action_name = card.name
                break

        return {
            "combination_type": combo_type,
            "emotion_name": emotion_name,
            "action_name": action_name,
            "result_text": template["text"],
            "affinity_delta": template["affinity_delta"],
            "suspicion_delta": template["suspicion_delta"],
            "gold_delta": template["gold_delta"],
            "can_record": True,
        }
