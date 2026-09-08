"""
游戏主控制器 - 日循环主控。

将所有子系统串联为完整的游戏流程：
  每天：任务选择 → 工作执行（5个工作时段循环）→ 投票 → 夜间 → 下一天
  第5天投票后 → 结局判定

这个类是后续接WebSocket时，后端的唯一调用入口。
Godot前端通过WebSocket发送玩家操作，GameController处理后返回状态更新。
"""
import asyncio
import copy
import logging
import random

from .ai_service import AIService, DEEPSEEK_MODEL, _client
from .agent_service import AgentService
from .ai_logger import AILogger
from .config_loader import PUA_EVENTS_CONFIG
from .constants import (
    ACTION_CARDS,
    CHAT_MONITOR_BATTERY_COST,
    DAILY_ACTION_POINTS,
    EMOTION_CARDS,
    SCOUT_BATTERY_COST,
    SOLO_ACTION_CARDS,
    TASK_DEFINITIONS,
    TOTAL_DAYS,
)
from .data_loader import DataLoader
from .evidence_converter import EvidenceConverter
from .enums import BossBehavior, GamePhase, RecordCardStatus, RewardType, Room
from .game_state import GameState
from .memory_system import MemorySystem
from .movement_system import MovementSystem
from .models import RecordCard
from .night_alliance_system import NightAllianceSystem
from .prompt_registry import PromptRegistry
from .state_manager import StateManager


class GameController:
    """
    游戏主控制器。

    管理完整的游戏生命周期：
    1. 初始化新游戏
    2. 每日阶段切换
    3. 接收玩家操作并返回结果
    4. 判断游戏结束条件
    """

    def __init__(self):
        self.state: GameState = None
        self.manager: StateManager = None
        self.memory: MemorySystem = None
        self._last_event_description: str = ""
        self._last_event_prompt: str = ""
        self._current_skeleton_event = None
        self._current_event_card_mode = "combo"
        self._last_act1_text = ""
        self._last_npc_infos = []
        self._today_events_summary: list = []  # 缓存今日事件摘要
        self._agent_results = None  # Agent决策结果缓存
        self._pending_act1 = None  # 移动阶段预请求的Act 1任务
        self._pending_scout_result = None  # 小助理探查结果缓冲区
        self._pending_scout_task = None  # 小助理后台侦察任务
        self._pending_night_alliance = None  # 投票后预加载的夜间结盟任务
        self._active_night_visitor_id = ""  # 当前已开门等待回应的来访者
        self._alliances_to_enforce: list[tuple[str, str, str]] = []  # 上一夜结盟，次日投票用于背叛判定
        self._pending_work_mode_choice = None  # 工作阶段“单干/交流”待选择上下文
        self._current_event_context: dict = {}  # 当前事件参与者/旁观者上下文
        self._last_record_card_context: dict = {}  # 最近一次可记录事件的黑料元数据
        self._last_scout_record_context: dict = {}  # 最近一次侦察结果的记录元数据
        self._pending_solo_event_meta: dict = {}  # 单人事件 Act2 取证据触发判定用的元数据
        self._hour_settlement_context: dict = {}  # 每小时推进前的旁观/配对结算上下文
        self._hour_bystander_resolved = False  # 防止同一小时重复写入旁观/配对记忆
        self._pending_pua_interruption: dict | None = None  # 每小时实时PUA检查结果（供前端提示）
        self._pending_npc_pua_notification: str = ""  # 非玩家目标被PUA时的轻提示（供前端通知）
        self._work_logger = logging.getLogger("DoomsdayRoute")
        self._debug_mode_enabled = False
        self._hour_room_case_cache: dict[str, dict] = {}  # 每小时分发缓存（给侦察等后续系统读取）
        self._pending_case3_anomaly_context: dict = {}
        self._active_front_case_id: int = 0
        self._active_front_case_ctx: dict = {}
        self._npc_wallets: dict[str, int] = {}
        self._active_contracts: list[dict] = []
        self._npc_ledger: dict[str, list[dict]] = {}
        self._last_player_event_route: str = ""
        self._forced_duo_trigger_count: int = 0
        self._pending_negotiation: dict | None = None  # 当前等待玩家响应的协商上下文(协商和 WS 跨调用)
        self._last_pua_target_id: str = ""  # 缓存昨天 PUA 的目标(供今日 AI 决策参考)
        self._last_pua_day: int = 0  # 上一次 PUA 发生在第几天（用于连续天数判定）
        self._pua_same_target_streak: int = 0  # 连续几天 PUA 同一目标（按执行结果统计）
        self._last_pua_snapshot: dict = {}  # 缓存当前小时最近一次 PUA 完整文本（供侦察复用）

    @staticmethod
    def _npc_display_name(npc_id: str, fallback: str = "") -> str:
        dl = DataLoader()
        raw = dl.get_npc_field(npc_id, "display_name", dl.get_npc_field(npc_id, "name", fallback or npc_id))
        return str(raw).strip() or (fallback or npc_id)

    @staticmethod
    def _npc_personality(npc_id: str, fallback: str = "") -> str:
        dl = DataLoader()
        raw = dl.get_npc_field(npc_id, "personality", fallback)
        return str(raw).strip() or fallback

    def _ensure_npc_wallets(self) -> None:
        """初始化 NPC 钱包（协商与经济系统资金池）。"""
        if not isinstance(self._npc_wallets, dict):
            self._npc_wallets = {}
        for npc_id in self.state.npcs.keys():
            self._npc_wallets.setdefault(npc_id, 80)
        self._npc_wallets.setdefault("boss", 120)

    def _ensure_npc_ledger(self) -> None:
        if not isinstance(self._npc_ledger, dict):
            self._npc_ledger = {}
        for npc_id in self.state.npcs.keys():
            self._npc_ledger.setdefault(npc_id, [])
        self._npc_ledger.setdefault("boss", [])

    def _record_npc_ledger(self, npc_id: str, amount: int, reason: str) -> None:
        nid = str(npc_id or "").strip()
        if not nid:
            return
        self._ensure_npc_ledger()
        rows = self._npc_ledger.setdefault(nid, [])
        rows.append(
            {
                "day": int(self.state.current_day),
                "hour": int(self.state.current_hour),
                "amount": int(amount),
                "reason": str(reason or "").strip(),
            }
        )
        if len(rows) > 60:
            self._npc_ledger[nid] = rows[-60:]

    def _record_card_available_for_event(self) -> bool:
        return any(rc.status.value == "blank" for rc in self.state.player.record_cards)

    def _apply_npc_hourly_income(self) -> None:
        """
        二期经济：NPC 与玩家一样，按“当前小时任务”获得收益。
        reward_type == gold 且 reward_value > 0 时入账，否则为 0。
        """
        self._ensure_npc_wallets()
        self._ensure_npc_ledger()
        for npc_id, npc in self.state.npcs.items():
            if not npc.alive:
                continue
            idx = int(getattr(npc, "current_task_index", 0) or 0)
            tasks = list(getattr(npc, "selected_tasks", []) or [])
            if idx < 0 or idx >= len(tasks):
                continue
            task = tasks[idx]
            reward_type = str(getattr(task, "reward_type", RewardType.NONE) or "")
            reward_value = int(getattr(task, "reward_value", 0) or 0)
            if reward_type != str(RewardType.GOLD) and reward_type != "gold":
                continue
            if reward_value <= 0:
                continue
            self._npc_wallets[npc_id] = int(self._npc_wallets.get(npc_id, 0) or 0) + reward_value
            task_name = str(getattr(task, "name", "工作收益")).strip() or "工作收益"
            self._record_npc_ledger(npc_id, reward_value, f"任务收入:{task_name}")

    def _build_economy_snapshot(self) -> dict:
        self._ensure_npc_wallets()
        return {
            "player_gold": int(self.state.player.gold),
            "npc_wallets": {str(k): int(v) for k, v in sorted(self._npc_wallets.items(), key=lambda x: str(x[0]))},
        }

    # ==========================================================
    # 协商系统(Batch 6): 祈求 / 勒索辅助方法
    # ==========================================================

    def _negotiation_alive_npc_names(self, exclude_npc_id: str = "") -> list[str]:
        """
        返回今晚还活着的同事显示名列表,用于勒索 prompt 中"投票目标"选项。
        排除: boss(不参与玩家投票)、玩家自己、当前协商的 NPC、已死亡 NPC。
        """
        names: list[str] = []
        exclude = str(exclude_npc_id or "").strip()
        for npc_id, npc in self.state.npcs.items():
            if not getattr(npc, "alive", True):
                continue
            if npc_id == exclude:
                continue
            display = self._npc_display_name(npc_id, getattr(npc, "name", npc_id))
            if display:
                names.append(display)
        return names

    def _negotiation_blackmail_targets(self, exclude_npc_id: str = "") -> list[dict]:
        """
        返回 NPC 现编黑料时可选的目标列表(其他 NPC,不含自己/玩家/boss/死人)。
        返回格式: [{"id": "xiaoli", "name": "小李"}, ...]
        """
        targets: list[dict] = []
        exclude = str(exclude_npc_id or "").strip()
        for npc_id, npc in self.state.npcs.items():
            if not getattr(npc, "alive", True):
                continue
            if npc_id == exclude:
                continue
            name = self._npc_display_name(npc_id, getattr(npc, "name", npc_id))
            targets.append({"id": npc_id, "name": name})
        return targets

    def _compute_extortion_amount_range(self, npc_id: str) -> tuple[int, int]:
        """
        计算 NPC 勒索玩家时的金额范围。
        来源: npc_profiles.json 的 extortion_price_min/max + 玩家钱包封顶。

        返回: (amount_min, amount_max)
        """
        dl = DataLoader()
        try:
            npc_min = int(dl.get_npc_field(npc_id, "extortion_price_min", 20) or 20)
        except (TypeError, ValueError):
            npc_min = 20
        try:
            npc_max = int(dl.get_npc_field(npc_id, "extortion_price_max", 50) or 50)
        except (TypeError, ValueError):
            npc_max = 50

        player_money = int(getattr(self.state.player, "gold", 0) or 0)

        # 玩家钱包封顶
        amount_max = min(npc_max, player_money)
        amount_min = npc_min

        # 边界: 玩家钱不够该 NPC 的最低勒索价 → 降级到 [10, player_money]
        if amount_max < amount_min:
            amount_min = 10
            amount_max = max(10, player_money)

        # 极端边界: 玩家钱包真的低于 10 → 返回 (10, 10),让 AI prompt 上仍然显示一个范围
        # 上层调用者会自己判断 AI 是否该选金钱方式
        return (amount_min, amount_max)

    def _compute_plea_amount_range(self, npc_id: str) -> tuple[int, int, bool]:
        """
        计算 NPC 祈求玩家时的金额范围(从 NPC 钱包出钱)。

        返回: (amount_min, amount_max, cash_available)
        cash_available=False 表示 NPC 钱不够最低祈求门槛,该方式不可用。
        """
        AMOUNT_FLOOR = 10  # 祈求最低门槛
        AMOUNT_CEIL = 80   # 单次祈求金额上限

        self._ensure_npc_wallets()
        npc_money = int(self._npc_wallets.get(npc_id, 0) or 0)

        if npc_money < AMOUNT_FLOOR:
            return (0, 0, False)

        amount_min = AMOUNT_FLOOR
        amount_max = min(npc_money, AMOUNT_CEIL)
        return (amount_min, amount_max, True)

    def _build_negotiation_payload(self, ai_result: dict, npc_id: str, kind: str) -> dict:
        """
        把 AI 返回的协商结果,打包成前端可消费的 negotiation 字段格式。

        参数:
            ai_result: AIService.generate_npc_plea / generate_npc_extortion 的返回值
            npc_id: 协商发起的 NPC ID
            kind: "plea" / "extortion"

        返回:
            {
                "type": "plea" / "extortion",
                "npc_id": "...",
                "npc_name": "...",
                "story_text": "...",
                "offer": {
                    "method": "金钱" / "黑料" / "投票" / "无",
                    "amount": int,
                    "blackmail_target_id": str,      # 仅 plea+黑料
                    "blackmail_target_name": str,    # 仅 plea+黑料
                    "blackmail_summary": str,        # 仅 plea+黑料
                    "vote_target_name": str,         # 仅 extortion+投票
                    "vote_target_id": str,           # 仅 extortion+投票(系统侧追加)
                }
            }
        """
        npc_name = self._npc_display_name(npc_id, npc_id)
        method = str(ai_result.get("method", "无")).strip()

        offer = {
            "method": method,
            "amount": int(ai_result.get("amount", 0) or 0),
            "blackmail_target_id": "",
            "blackmail_target_name": "",
            "blackmail_summary": "",
            "vote_target_name": "",
            "vote_target_id": "",
        }

        if kind == "plea" and method == "黑料":
            target_id = str(ai_result.get("target_id", "")).strip()
            offer["blackmail_target_id"] = target_id
            offer["blackmail_target_name"] = self._npc_display_name(target_id, target_id)
            offer["blackmail_summary"] = str(ai_result.get("summary", "")).strip()
        elif kind == "extortion" and method == "投票":
            target_name = str(ai_result.get("target_name", "")).strip()
            offer["vote_target_name"] = target_name
            # 反查 NPC ID(从 display_name → id)
            target_id = self._npc_id_from_display_name(target_name)
            offer["vote_target_id"] = target_id

        return {
            "type": kind,
            "npc_id": npc_id,
            "npc_name": npc_name,
            "story_text": str(ai_result.get("story", "")).strip(),
            "memory_text": str(ai_result.get("memory_text", "")).strip(),
            "impression": str(ai_result.get("impression", "")).strip(),
            "offer": offer,
        }

    async def _check_post_act2_negotiation(
        self,
        primary_npc_id: str,
        accident_meta: dict,
        act1_text: str,
        room_name: str,
        task_text: str,
    ) -> dict | None:
        """
        Act2 结算后调用,判断是否触发协商(祈求 / 勒索),并调用相应 AI 方法。

        参数:
            primary_npc_id: 当前事件主 NPC 的 ID
            accident_meta: 从 _current_event_context["accident_meta"] 复制的副本
                          { "subject_id": str, "condition": str, "text": str, "primary_npc_id": str }
            act1_text: Act1 已生成的剧情文本
            room_name: 房间中文名
            task_text: 任务描述

        返回:
            None: 不触发协商,正常游戏继续
            dict: negotiation 字段,见 _build_negotiation_payload 文档
        """
        # 边界检查
        if not isinstance(accident_meta, dict) or not accident_meta:
            return None
        condition = str(accident_meta.get("condition", "")).strip().lower()
        subject_id = str(accident_meta.get("subject_id", "")).strip().lower()
        if condition != "negative":
            return None
        if not primary_npc_id or primary_npc_id == "boss":
            return None

        # NPC 当事人 → 祈求(看 fear 阈值)
        if subject_id == primary_npc_id:
            npc = self.state.npcs.get(primary_npc_id)
            if npc is None or not getattr(npc, "alive", True):
                return None
            npc_fear = int(getattr(npc, "fear", 30) or 0)
            if npc_fear < 70:
                self._work_logger.info(
                    "[NEGOTIATION] skip plea: npc=%s fear=%d (< 70)",
                    primary_npc_id, npc_fear,
                )
                return None

            # 阈值过 → 调祈求 AI
            return await self._invoke_plea_ai(
                primary_npc_id, accident_meta, act1_text, room_name, task_text,
            )

        # 玩家是当事人 → 勒索(AI 自决,不卡阈值)
        if subject_id == "player":
            # 一日内只能被勒索成功一次,后续直接走普通 Act2
            if bool(getattr(self.state.daily, "player_already_extorted_today", False)):
                self._work_logger.info(
                    "[NEGOTIATION] skip extortion: player already extorted today"
                )
                return None
            return await self._invoke_extortion_ai(
                primary_npc_id, accident_meta, act1_text, room_name, task_text,
            )

        # subject_id 是其他值 → 不触发(防御性)
        return None

    async def _invoke_plea_ai(
        self,
        primary_npc_id: str,
        accident_meta: dict,
        act1_text: str,
        room_name: str,
        task_text: str,
    ) -> dict | None:
        """调用 AIService.generate_npc_plea,把结果打包成 negotiation payload。"""
        from .ai_service import AIService  # 避免循环 import

        npc = self.state.npcs.get(primary_npc_id)
        if npc is None:
            return None

        npc_profile = self._build_npc_info_for_negotiation(primary_npc_id)
        amount_min, amount_max, cash_available = self._compute_plea_amount_range(primary_npc_id)
        blackmail_targets = self._negotiation_blackmail_targets(primary_npc_id)

        # 如果钱不够 + 没有黑料目标 → 没法祈求,跳过
        if not cash_available and not blackmail_targets:
            self._work_logger.info(
                "[NEGOTIATION] skip plea: npc=%s no cash AND no blackmail targets",
                primary_npc_id,
            )
            return None

        recap_result = await AIService.generate_event_recap(
            npc_name=npc_profile["name"],
            player_name=self.state.player.name,
            act1_text=act1_text,
        )
        event_recap = (recap_result.get("recap_text") or act1_text or "")

        ai_result = await AIService.generate_npc_plea(
            npc_profile=npc_profile,
            npc_name=npc_profile["name"],
            npc_identity=npc_profile["identity"],
            npc_aim=npc_profile["aim"],
            npc_memory_rel=npc_profile["memory_and_relations"],
            player_name=self.state.player.name,
            room_name=room_name,
            task_text=task_text,
            act1_text=act1_text,
            accident_text=str(accident_meta.get("text", "")),
            amount_min=amount_min,
            amount_max=amount_max,
            cash_available=cash_available,
            available_blackmail_targets=blackmail_targets,
            npc_id=primary_npc_id,
            event_recap=event_recap,
        )

        # 不管 AI 是否同意,都构建 payload —— story_text 都要用
        # 区别仅在: agree=False 时 method 会是"无",前端据此不显示同意/拒绝按钮
        payload = self._build_negotiation_payload(ai_result, primary_npc_id, "plea")

        if not ai_result.get("agree", False):
            self._work_logger.info(
                "[NEGOTIATION] plea declined by AI: npc=%s (story used as Act2)",
                primary_npc_id,
            )
        else:
            self._work_logger.info(
                "[NEGOTIATION] plea accepted by AI: npc=%s method=%s",
                primary_npc_id, payload.get("offer", {}).get("method"),
            )
        return payload

    async def _invoke_extortion_ai(
        self,
        primary_npc_id: str,
        accident_meta: dict,
        act1_text: str,
        room_name: str,
        task_text: str,
    ) -> dict | None:
        """调用 AIService.generate_npc_extortion,把结果打包成 negotiation payload。"""
        from .ai_service import AIService

        npc = self.state.npcs.get(primary_npc_id)
        if npc is None:
            return None

        npc_profile = self._build_npc_info_for_negotiation(primary_npc_id)
        amount_min, amount_max = self._compute_extortion_amount_range(primary_npc_id)
        alive_npcs = self._negotiation_alive_npc_names(primary_npc_id)

        recap_result = await AIService.generate_event_recap(
            npc_name=npc_profile["name"],
            player_name=self.state.player.name,
            act1_text=act1_text,
        )
        event_recap = (recap_result.get("recap_text") or act1_text or "")

        ai_result = await AIService.generate_npc_extortion(
            npc_profile=npc_profile,
            npc_name=npc_profile["name"],
            npc_identity=npc_profile["identity"],
            npc_aim=npc_profile["aim"],
            npc_memory_rel=npc_profile["memory_and_relations"],
            player_name=self.state.player.name,
            room_name=room_name,
            task_text=task_text,
            act1_text=act1_text,
            accident_text=str(accident_meta.get("text", "")),
            amount_min=amount_min,
            amount_max=amount_max,
            alive_npc_names=alive_npcs,
            npc_id=primary_npc_id,
            event_recap=event_recap,
        )

        payload = self._build_negotiation_payload(ai_result, primary_npc_id, "extortion")
        if not ai_result.get("agree", False):
            self._work_logger.info(
                "[NEGOTIATION] extortion declined by AI: npc=%s (story used as Act2)",
                primary_npc_id,
            )
        else:
            self._work_logger.info(
                "[NEGOTIATION] extortion accepted by AI: npc=%s method=%s",
                primary_npc_id, payload.get("offer", {}).get("method"),
            )
        return payload

    def _build_npc_info_for_negotiation(self, npc_id: str) -> dict:
        """构建协商 AI 调用所需的 NPC 信息包(复用 memory_system 的 build_npc_info_for_ai)。"""
        if self.memory is None:
            # 极端边界:记忆系统未初始化,降级
            return {
                "id": npc_id,
                "name": self._npc_display_name(npc_id, npc_id),
                "identity": "",
                "aim": "",
                "memory_and_relations": "",
            }
        info = self.memory.build_npc_info_for_ai(
            npc_id=npc_id,
            relationships=self.state.relationships,
            npcs=self.state.npcs,
            player_name=self.state.player.name,
        )
        return info

    async def respond_to_negotiation(self, agree: bool) -> dict:
        """
        处理玩家对协商弹窗的响应(同意/拒绝)。

        前置条件: self._pending_negotiation 不为 None(由 play_cards_with_ai_v2 设置)。

        返回:
            {
                "success": bool,
                "agree": bool,
                "summary_text": str,           # 简短结算总结(给前端弹 toast 用)
                "gold_after": int,
                "blame_cards_count": int,
                "new_blackmail_card": dict | None,   # 玩家新获得的黑料卡(同意 plea+黑料 时)
                "can_use_record_card": bool,   # 同意 → False
                "economy_snapshot": dict,
                "error": str,                  # 仅 success=False 时
            }
        """
        if self._pending_negotiation is None:
            return {
                "success": False,
                "error": "no_pending_negotiation",
                "summary_text": "",
            }

        ctx = dict(self._pending_negotiation)
        self._pending_negotiation = None  # 立即清空,防止重复响应

        nego = dict(ctx.get("negotiation") or {})
        kind = str(nego.get("type", "")).strip()  # "plea" / "extortion"
        npc_id = str(nego.get("npc_id", "")).strip()
        offer = dict(nego.get("offer", {}) or {})
        method = str(offer.get("method", "无")).strip()
        day = int(ctx.get("current_day", self.state.current_day))
        room_name = str(ctx.get("room_name", "") or "")

        if kind not in ("plea", "extortion") or not npc_id:
            return {
                "success": False,
                "error": "invalid_negotiation_context",
                "summary_text": "",
            }

        # ===== 数值层强校验(Batch 6 修订) =====
        # AI 返回的字段如果在数值上不合法,统一退化为"协商无效"
        # 退化时玩家应该可以正常记录(回到普通 Act2 三按钮)
        validation_failed = False
        validation_reason = ""

        if method == "金钱":
            amount = int(offer.get("amount", 0) or 0)
            if amount <= 0:
                validation_failed = True
                validation_reason = f"invalid_amount_{amount}"
            elif kind == "extortion" and amount > int(self.state.player.gold):
                validation_failed = True
                validation_reason = f"player_cant_afford_{amount}"
            elif kind == "plea":
                self._ensure_npc_wallets()
                if amount > int(self._npc_wallets.get(npc_id, 0) or 0):
                    validation_failed = True
                    validation_reason = f"npc_cant_afford_{amount}"
        elif method == "黑料":
            target_id = str(offer.get("blackmail_target_id", "")).strip()
            summary = str(offer.get("blackmail_summary", "")).strip()
            if not target_id or not summary:
                validation_failed = True
                validation_reason = "blackmail_target_or_summary_missing"
            elif target_id == npc_id or target_id == "player" or target_id == "boss":
                validation_failed = True
                validation_reason = f"invalid_blackmail_target_{target_id}"
        elif method == "投票":
            vote_target_id = str(offer.get("vote_target_id", "")).strip()
            if not vote_target_id:
                validation_failed = True
                validation_reason = "vote_target_missing"
            elif vote_target_id not in self.state.npcs:
                validation_failed = True
                validation_reason = f"invalid_vote_target_{vote_target_id}"
            elif not getattr(self.state.npcs.get(vote_target_id), "alive", True):
                validation_failed = True
                validation_reason = f"vote_target_dead_{vote_target_id}"
        elif method == "无":
            # method=无 是合法的"AI 不协商"——但理论上前端不会发 respond_negotiation 上来
            # 如果发了,视为玩家点了"拒绝"(走正常流程)
            pass
        else:
            validation_failed = True
            validation_reason = f"unknown_method_{method}"

        if validation_failed:
            self._work_logger.warning(
                "[NEGOTIATION] validation failed: kind=%s npc=%s method=%s reason=%s → fallback to normal flow",
                kind, npc_id, method, validation_reason,
            )
            # 退化为"协商无效":玩家可正常记录,无金额转移,无 fear/好感变化
            return {
                "success": True,
                "agree": False,
                "summary_text": "(AI 返回的数据无法验证,本次协商作废,你可以正常处理事件。)",
                "gold_after": int(self.state.player.gold),
                "player_gold": int(self.state.player.gold),
                "gold": int(self.state.player.gold),
                "blame_cards_count": int(self.state.player.items.get("blame_card", 0) or 0),
                "new_blackmail_card": None,
                "can_use_record_card": True,  # 退化时玩家可记录
                "economy_snapshot": self._build_economy_snapshot(),
                "validation_failed": True,
                "validation_reason": validation_reason,
            }
        # ===== 校验通过,继续原结算流程 =====

        npc = self.state.npcs.get(npc_id)
        npc_name = self._npc_display_name(npc_id, npc_id)
        player_name = self.state.player.name or "调查员"

        result = {
            "success": True,
            "agree": bool(agree),
            "summary_text": "",
            "gold_after": int(self.state.player.gold),
            "player_gold": int(self.state.player.gold),
            "gold": int(self.state.player.gold),
            "blame_cards_count": int(self.state.player.items.get("blame_card", 0) or 0),
            "new_blackmail_card": None,
            "can_use_record_card": True,  # 默认可记录,同意时改 False
            "economy_snapshot": {},
        }

        # NPC 不存在(死亡或上下文失效)时直接视为无效上下文
        if npc is None:
            return {
                "success": False,
                "error": "invalid_negotiation_context",
                "summary_text": "",
            }

        # ============ 分支处理 ============
        if kind == "plea":
            self._handle_plea_response(
                agree=agree, npc_id=npc_id, offer=offer, day=day,
                room_name=room_name, player_name=player_name, result=result,
            )
        elif kind == "extortion":
            self._handle_extortion_response(
                agree=agree, npc_id=npc_id, offer=offer, day=day,
                room_name=room_name, player_name=player_name, result=result,
            )

        # 同意 → 玩家不能记录该事件
        if agree:
            result["can_use_record_card"] = False

        # 刷新返回字段
        result["gold_after"] = int(self.state.player.gold)
        result["player_gold"] = int(self.state.player.gold)
        result["gold"] = int(self.state.player.gold)
        result["blame_cards_count"] = int(self.state.player.items.get("blame_card", 0) or 0)
        self._ensure_npc_wallets()
        result["economy_snapshot"] = self._build_economy_snapshot()

        self._work_logger.info(
            "[NEGOTIATION_RESPONSE] kind=%s agree=%s npc=%s method=%s gold_after=%d",
            kind, agree, npc_id, method, int(self.state.player.gold),
        )
        return result

    def _handle_plea_response(
        self,
        *,
        agree: bool,
        npc_id: str,
        offer: dict,
        day: int,
        room_name: str,
        player_name: str,
        result: dict,
    ) -> None:
        """处理祈求响应(NPC 求玩家保密)。"""
        method = str(offer.get("method", "无")).strip()
        npc_name = self._npc_display_name(npc_id, npc_id)

        if not agree:
            # 玩家拒绝 → NPC.fear +5, 好感 -10, 走正常流程(可记录可传播)
            self._increase_fear(npc_id, 5, reason=f"plea_rejected_by_{player_name}")
            self.manager.modify_affinity(npc_id, "player", -10)
            self.manager.append_relationship_reason(
                npc_id, "player",
                f"向{player_name}祈求被拒绝，记下了这笔账。",
            )
            if self.memory is not None:
                self.memory.merge_into_last_impression(
                    observer_id=npc_id,
                    target_id="player",
                    day=day,
                    append_text=f"我向{player_name}祈求保守秘密，但他拒绝了。这人真不识抬举！",
                    sealed=False,  # 拒绝的记忆可正常传播
                    source="plea_rejected",
                )
            result["summary_text"] = f"你拒绝了{npc_name}的请求。{npc_name}的脸色明显沉了下来。"
            return

        # 玩家同意 → NPC.fear -5, 好感 +3
        self._increase_fear(npc_id, -5, reason=f"plea_accepted_by_{player_name}")
        self.manager.modify_affinity(npc_id, "player", 3)
        self.manager.append_relationship_reason(
            npc_id, "player",
            f"恳求{player_name}保密，对方答应了，欠了一份人情。",
        )

        if method == "金钱":
            amount = int(offer.get("amount", 0) or 0)
            self._ensure_npc_wallets()
            current_npc_money = int(self._npc_wallets.get(npc_id, 0) or 0)
            actual = min(amount, current_npc_money)  # 防超支
            if actual > 0:
                self._npc_wallets[npc_id] = current_npc_money - actual
                self.manager.modify_gold(actual)
                self._record_npc_ledger(npc_id, -actual, f"祈求{player_name}支付封口费")
            result["summary_text"] = f"{npc_name}悄悄塞给你 {actual} 金币。这事就此打住。"
        elif method == "黑料":
            target_id = str(offer.get("blackmail_target_id", "")).strip()
            target_name = str(offer.get("blackmail_target_name", "")).strip() or target_id
            summary = str(offer.get("blackmail_summary", "")).strip()
            # 玩家获得新黑料卡
            new_card = self._grant_blackmail_card_from_plea(
                target_id=target_id, target_name=target_name, summary=summary, day=day,
            )
            if new_card:
                result["new_blackmail_card"] = new_card
                result["summary_text"] = f"{npc_name}给了你一条关于{target_name}的猛料：{summary}"
            else:
                result["summary_text"] = f"{npc_name}本想给你点什么，但话到嘴边又咽了回去。"
        else:
            # method == "无" 或非法值 → 视为拒绝
            result["summary_text"] = f"{npc_name}最后什么也没说。"
            return

        # 写入 sealed 记忆(NPC 不主动传播此事)
        if self.memory is not None:
            self.memory.merge_into_last_impression(
                observer_id=npc_id,
                target_id="player",
                day=day,
                append_text=f"我向{player_name}祈求保守秘密，他答应了。这事不能再提。",
                sealed=True,
                source="plea_accepted",
            )

    def _handle_extortion_response(
        self,
        *,
        agree: bool,
        npc_id: str,
        offer: dict,
        day: int,
        room_name: str,
        player_name: str,
        result: dict,
    ) -> None:
        """处理勒索响应(NPC 敲诈玩家)。"""
        method = str(offer.get("method", "无")).strip()
        npc_name = self._npc_display_name(npc_id, npc_id)

        if not agree:
            # 玩家拒绝 → NPC 好感 -10, 怀疑度 +5, 走正常流程(可记录可传播"被勒索")
            self.manager.modify_affinity(npc_id, "player", -10)
            self.manager.modify_suspicion(npc_id, "player", 5)
            self.manager.append_relationship_reason(
                npc_id, "player",
                f"敲诈{player_name}失败，对方反而更可疑了。",
            )
            if self.memory is not None:
                self.memory.merge_into_last_impression(
                    observer_id=npc_id,
                    target_id="player",
                    day=day,
                    append_text=f"我试图敲诈{player_name}保守秘密，他拒绝了。也许我该改变策略。",
                    sealed=False,  # 拒绝的勒索记忆可正常传播
                    source="extortion_rejected",
                )
            result["summary_text"] = f"你拒绝了{npc_name}的敲诈。{npc_name}的眼神冷了下来。"
            return

        # 玩家同意勒索 → 标记今日已被勒索成功一次,后续 NPC 不再勒索
        self.state.daily.player_already_extorted_today = True

        # 玩家同意 → NPC 好感 +5(扭曲的"惺惺相惜")
        self.manager.modify_affinity(npc_id, "player", 5)
        self.manager.append_relationship_reason(
            npc_id, "player",
            f"成功敲诈到{player_name}，这人挺识相。",
        )

        if method == "金钱":
            amount = int(offer.get("amount", 0) or 0)
            current_player_gold = int(self.state.player.gold)
            actual = min(amount, current_player_gold)
            if actual > 0:
                self.manager.modify_gold(-actual)
                self._ensure_npc_wallets()
                self._npc_wallets[npc_id] = int(self._npc_wallets.get(npc_id, 0) or 0) + actual
                self._record_npc_ledger(npc_id, actual, f"敲诈{player_name}的封口费")
            result["summary_text"] = f"你掏出 {actual} 金币交给{npc_name}。{npc_name}满意地走开了。"
        elif method == "投票":
            target_id = str(offer.get("vote_target_id", "")).strip()
            target_name = str(offer.get("vote_target_name", "")).strip() or target_id
            # 设置 daily 强制投票字段(投票路由会检测此字段强制锁定目标)
            self.state.daily.forced_vote_target_id = target_id
            result["summary_text"] = f"你被{npc_name}胁迫了。今晚必须投给{target_name}。"
        else:
            result["summary_text"] = f"{npc_name}还没说要什么。"
            return

        # 写入 sealed 记忆(NPC 不主动传播此事)
        if self.memory is not None:
            self.memory.merge_into_last_impression(
                observer_id=npc_id,
                target_id="player",
                day=day,
                append_text=f"我成功敲诈到{player_name}。这事绝不能让别人知道。",
                sealed=True,
                source="extortion_accepted",
            )

    def _grant_blackmail_card_from_plea(
        self,
        target_id: str,
        target_name: str,
        summary: str,
        day: int,
    ) -> dict | None:
        """
        玩家从祈求中获得一张黑料卡(NPC 现编内容)。

        实际写入 self.state.player.record_cards 中类型为 blackmail 的卡。
        返回前端用的 dict,失败时返回 None。
        """
        if not target_id or not summary:
            return None

        next_index = len(self.state.player.record_cards) + len(self.state.evidence_collected) + 1
        card_id = f"rc_{next_index:03d}"
        card = RecordCard(
            id=card_id,
            status=RecordCardStatus.RECORDED,
            record_type="blackmail",
            linked_evidence_tag="",
            source_description=f"negotiation:{target_name or target_id}",
            day_recorded=day,
            subject_npc_id=target_id,
            subject_npc_name=target_name or target_id,
            summary_text=str(summary)[:100],
            is_evidence=False,
        )
        self.state.player.record_cards.append(card)
        return {
            "card_id": card_id,
            "subject_npc_id": target_id,
            "subject_npc_name": target_name or target_id,
            "summary_text": str(summary)[:100],
            "day": day,
        }

    def _npc_id_from_display_name(self, display_name: str) -> str:
        """根据显示名反查 NPC ID。失败时返回空字符串。"""
        target = str(display_name or "").strip()
        if not target:
            return ""
        for npc_id, npc in self.state.npcs.items():
            name = self._npc_display_name(npc_id, getattr(npc, "name", npc_id))
            if name == target:
                return npc_id
        return ""

    def _should_force_interaction_after_solo(self) -> bool:
        return str(self._last_player_event_route or "").strip().lower() == "solo"

    def _pick_non_boss_roommate_for_forced_duo(self) -> str:
        from .room_system import RoomSystem
        room_info = RoomSystem.get_room_occupants(self.state.player, self.state.npcs, self.state.boss, self.state.player.current_room)
        npc_ids = [str(x).strip() for x in room_info.get("npcs", []) if str(x).strip() and str(x).strip() != "boss"]
        random.shuffle(npc_ids)
        for npc_id in npc_ids:
            npc = self.state.npcs.get(npc_id)
            if npc and npc.alive:
                return npc_id
        return ""


    def _increase_fear(self, character_id: str, delta: int, reason: str = "") -> None:
        value = int(delta or 0)
        if value == 0:
            return
        cid = str(character_id or "").strip()
        if cid == "boss":
            old = int(getattr(self.state.boss, "fear", 30) or 0)
            self.state.boss.fear = max(0, min(100, old + value))
            self._work_logger.info(
                "[FEAR] id=boss old=%s delta=%s new=%s reason=%s",
                old,
                value,
                int(getattr(self.state.boss, "fear", 0)),
                str(reason or "").strip(),
            )
            return
        npc = self.state.npcs.get(cid)
        if npc is None:
            return
        old = int(getattr(npc, "fear", 30) or 0)
        npc.fear = max(0, min(100, old + value))
        self._work_logger.info(
            "[FEAR] id=%s old=%s delta=%s new=%s reason=%s",
            cid,
            old,
            value,
            int(getattr(npc, "fear", 0)),
            str(reason or "").strip(),
        )

    def _apply_daily_fear_decay(self) -> None:
        old_boss = int(getattr(self.state.boss, "fear", 30) or 0)
        self.state.boss.fear = max(0, old_boss - 5)
        self._work_logger.info(
            "[FEAR_DECAY] day=%s id=boss old=%s new=%s",
            self.state.current_day,
            old_boss,
            int(getattr(self.state.boss, "fear", 0)),
        )
        for npc_id, npc in self.state.npcs.items():
            old = int(getattr(npc, "fear", 30) or 0)
            npc.fear = max(0, old - 5)
            self._work_logger.info(
                "[FEAR_DECAY] day=%s id=%s old=%s new=%s",
                self.state.current_day,
                npc_id,
                old,
                int(getattr(npc, "fear", 0)),
            )

    def _apply_blackmail_broadcast_judgement_v2(
        self,
        *,
        listener_id: str,
        target_id: str,
        judgement: str,
        reason_text: str,
    ) -> tuple[int, int]:
        """
        传播黑料结算的关系调整三件套：suspicion + affinity + reason。

        参数:
            listener_id: 听众 NPC（动作发起者方向：listener_id -> target_id）
            target_id: 关系对象，值可以是 "player" 或 NPC id
            judgement: AI 判定，取值 "增加怀疑" / "减少怀疑" / "无感"
            reason_text: 写入关系 reason 的人话理由（与记忆 impression 互补、更短）

        返回 (suspicion_delta, affinity_delta)。
        说明：怀疑度与好感度方向相反（增加怀疑→好感降低；减少怀疑→好感升高）。
        """
        sus_map = {"增加怀疑": 10, "减少怀疑": -10, "无感": 0}
        aff_map = {"增加怀疑": -5, "减少怀疑": 5, "无感": 0}
        sus_delta = sus_map.get(str(judgement or "").strip(), 0)
        aff_delta = aff_map.get(str(judgement or "").strip(), 0)
        if not sus_delta and not aff_delta:
            return 0, 0
        listener_id = str(listener_id or "").strip()
        target_id = str(target_id or "").strip()
        if not listener_id or not target_id:
            return 0, 0
        if target_id != "player" and target_id not in self.state.relationships.get(listener_id, {}):
            return 0, 0
        if sus_delta:
            self.manager.modify_suspicion(listener_id, target_id, sus_delta)
        if aff_delta and target_id != "boss":
            self.manager.modify_affinity(listener_id, target_id, aff_delta)
        if reason_text:
            self.manager.append_relationship_reason(listener_id, target_id, reason_text)
        return sus_delta, aff_delta

    def _blackmail_subject_reaction_text(self, listener_id: str, subject_judgement: str) -> str:
        judgement = str(subject_judgement or "").strip() or "无感"
        if judgement == "减少怀疑":
            return "我觉得不太可信。"
        if judgement == "增加怀疑":
            personality = self._npc_personality(listener_id, "谨慎")
            if "冲动" in personality or "急躁" in personality:
                return "这事越听越不对劲，我得盯紧点。"
            if "冷静" in personality or "理性" in personality:
                return "听起来确实有点可疑，我先记一笔。"
            return "听起来确实有点可疑。"
        return "跟我没关系，懒得管。"

    def _build_blackmail_subject_impression_text(
        self,
        listener_id: str,
        player_name: str,
        subject_npc_name: str,
        blackmail_summary: str,
        subject_judgement: str,
        ai_subject_reaction_text: str = "",
    ) -> str:
        summary_text = str(blackmail_summary or "").strip() or "有些见不得人的旧事"
        reaction_text = str(ai_subject_reaction_text or "").strip()
        if not reaction_text:
            reaction_text = self._blackmail_subject_reaction_text(listener_id, subject_judgement)
        return f"据{player_name}说，{subject_npc_name}{summary_text}。{reaction_text}"

    def _npc_name_id_map_for_result(self) -> dict[str, str]:
        mapping = DataLoader().get_npc_name_to_id_map()
        mapping[self.state.player.name] = "player"
        mapping["玩家"] = "player"
        mapping["调查员"] = "player"
        for npc_id, npc in self.state.npcs.items():
            mapping[npc.name] = npc_id
        return mapping

    def _serialize_recorded_cards(self) -> list[dict]:
        return [
            {
                "id": rc.id,
                "source": rc.source_description,
                "day": rc.day_recorded,
                "record_type": str(getattr(rc, "record_type", "") or ""),
                "subject_npc_id": str(getattr(rc, "subject_npc_id", "") or ""),
                "subject_npc_name": str(getattr(rc, "subject_npc_name", "") or ""),
                "summary_text": str(getattr(rc, "summary_text", "") or ""),
                "is_evidence": bool(getattr(rc, "is_evidence", False)),
            }
            for rc in self.state.player.record_cards
            if rc.status.value == "recorded"
        ]

    def _valid_evidence_count(self) -> int:
        """
        有效证据：仅统计带有效 evidence_tag 的记录项。
        """
        count = 0
        for card in self.state.evidence_collected:
            tag = str(getattr(card, "linked_evidence_tag", "") or "").strip()
            if tag.startswith("evidence_"):
                count += 1
        return count

    def _recorded_cards_count(self) -> int:
        return sum(1 for rc in self.state.player.record_cards if rc.status.value == "recorded")

    def _count_player_evidence(self) -> int:
        """统计玩家收集的证据数量。"""
        # 当前项目主口径：仅统计有效证据（linked_evidence_tag 以 evidence_ 开头）。
        try:
            return int(self._valid_evidence_count())
        except Exception:
            pass

        # 兜底：兼容旧结构或异常状态。
        evidence_collected = getattr(self.state, "evidence_collected", None)
        if evidence_collected is not None:
            return int(len(evidence_collected))

        record_cards = getattr(self.state.player, "record_cards", []) if getattr(self, "state", None) else []
        evidence = [c for c in record_cards if str(getattr(c, "record_type", "")).strip().lower() == "evidence"]
        return int(len(evidence))

    def _determine_ending(self) -> dict:
        """
        判定游戏结局类型(基于 game_result 权威字段)。

        三种结局:
        - perfect_victory: game_result == "win"
        - eliminated: game_result == "fail_voted_out" / "fail_boss_executed"
        - survived_no_evidence: game_result == "fail_no_evidence" 或撑过 5 天证据不足
        """
        game_result = str(getattr(self.state, "game_result", "") or "").strip()
        game_over = bool(getattr(self.state, "game_over", False))
        current_day = int(getattr(self.state, "current_day", 1))
        evidence_count = self._count_player_evidence()
        required_evidence = 5

        # 权威字段判定
        if game_result == "win":
            return {
                "ending_type": "perfect_victory",
                "title": "完美胜利!",
                "subtitle": "你成功揪出了鲍斯私吞公款的罪证。",
                "icon": "🏆",
                "image_path": "res://assets/ending/ending_perfect_victory.png",
                "current_day": current_day,
                "evidence_count": evidence_count,
                "required_evidence": required_evidence,
            }

        if game_result in ("fail_voted_out", "fail_boss_executed"):
            return {
                "ending_type": "eliminated",
                "title": "你被处决了",
                "subtitle": "卧底身份未暴露,但任务也终结于此。",
                "icon": "💀",
                "image_path": "res://assets/ending/ending_eliminated.png",
                "current_day": current_day,
                "evidence_count": evidence_count,
                "required_evidence": required_evidence,
            }

        if game_result == "fail_no_evidence":
            return {
                "ending_type": "survived_no_evidence",
                "title": "你活下来了",
                "subtitle": f"但只收集到 {evidence_count}/{required_evidence} 份证据,任务失败。",
                "icon": "🟡",
                "image_path": "res://assets/ending/ending_survived.png",
                "current_day": current_day,
                "evidence_count": evidence_count,
                "required_evidence": required_evidence,
            }

        # game_over 但 game_result 没设(防御性兜底):按证据数判定
        if game_over:
            if evidence_count >= required_evidence:
                return {
                    "ending_type": "perfect_victory",
                    "title": "完美胜利!",
                    "subtitle": "你成功揪出了鲍斯私吞公款的罪证。",
                    "icon": "🏆",
                    "image_path": "res://assets/ending/ending_perfect_victory.png",
                    "current_day": current_day,
                    "evidence_count": evidence_count,
                    "required_evidence": required_evidence,
                }
            return {
                "ending_type": "survived_no_evidence",
                "title": "你活下来了",
                "subtitle": f"但只收集到 {evidence_count}/{required_evidence} 份证据,任务失败。",
                "icon": "🟡",
                "image_path": "res://assets/ending/ending_survived.png",
                "current_day": current_day,
                "evidence_count": evidence_count,
                "required_evidence": required_evidence,
            }

        # 游戏未结束
        return {
            "ending_type": "ongoing",
            "title": "",
            "subtitle": "",
            "icon": "",
            "image_path": "",
            "current_day": current_day,
            "evidence_count": evidence_count,
            "required_evidence": required_evidence,
        }

    def _load_ending_cutscenes(self, ending_type: str) -> list:
        """加载结局过场剧情文案。"""
        if not ending_type or ending_type == "ongoing":
            return []

        import csv
        from pathlib import Path

        csv_path = Path(__file__).parent / "data" / "ending_cutscenes.csv"
        if not csv_path.exists():
            self._work_logger.warning(f"[ENDING] cutscenes 文件不存在: {csv_path}")
            return []

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get("ending_type", "")).strip() == ending_type:
                        sentences_text = str(row.get("sentences", "")).strip()
                        return [s.strip() for s in sentences_text.split("|") if s.strip()]
        except Exception as e:
            self._work_logger.warning(f"[ENDING] 加载过场剧情失败: {e}")
        return []

    def build_ending_summary(self) -> dict:
        """
        构建结算界面的完整数据包(所有 NPC 对所有 target 的分天记忆)。
        """
        ending = self._determine_ending()
        ending["sentences"] = self._load_ending_cutscenes(ending.get("ending_type", ""))
        player_name = str(getattr(self.state.player, "name", "调查员"))

        if self.memory is None:
            return {
                "ending": ending,
                "npc_memories": {},
                "tab_order": [],
                "player_name": player_name,
            }

        npc_memories: dict = {}
        tab_order: list[str] = []
        preferred_order = ["laowang", "xiaoli", "ahua", "dazhuang", "zhoujie"]
        state_npc_ids = list(getattr(self.state, "npcs", {}).keys())

        npc_ids: list[str] = [nid for nid in preferred_order if nid in state_npc_ids]
        npc_ids.extend([nid for nid in state_npc_ids if nid not in npc_ids])
        npc_ids_with_boss = npc_ids + ["boss"]

        for npc_id in npc_ids_with_boss:
            npc_name = self._npc_display_name(npc_id, npc_id)

            if npc_id == "boss":
                identity = str(DataLoader().get_npc_field("boss", "identity", "") or "")
            else:
                npc = self.state.npcs.get(npc_id)
                if npc is None:
                    continue
                identity = str(getattr(npc, "identity", "") or "")

            observer_mem = self.memory.memories.get(npc_id, {})
            memories_by_day: dict = {}

            for target_id, day_map in observer_mem.items():
                target_name = self._memory_target_display_name(target_id, player_name)
                for day, entries in day_map.items():
                    day_int = int(day)
                    day_bucket = memories_by_day.setdefault(day_int, {})
                    target_bucket = day_bucket.setdefault(
                        target_id,
                        {
                            "target_name": target_name,
                            "texts": [],
                        },
                    )
                    for entry in entries:
                        text, sealed = self.memory.unpack_memory_entry(entry)
                        if not text:
                            continue
                        if sealed:
                            text = f"🤫 {text}"
                        target_bucket["texts"].append(text)

            npc_memories[npc_id] = {
                "name": npc_name,
                "identity": identity,
                "memories_by_day": memories_by_day,
            }
            tab_order.append(npc_id)

        return {
            "ending": ending,
            "npc_memories": npc_memories,
            "tab_order": tab_order,
            "player_name": player_name,
        }

    def _memory_target_display_name(self, target_id: str, player_name: str) -> str:
        """记忆 target 的显示名(player → 玩家名,boss → 鲍斯,其他 → NPC name)。"""
        if target_id == "player":
            return player_name
        if target_id == "boss":
            return "鲍斯"
        npc = self.state.npcs.get(target_id)
        if npc:
            return str(getattr(npc, "name", target_id))
        return str(target_id)

    def _available_blackmail_cards_for_target(self, target_npc_id: str) -> list[dict]:
        """筛选在指定传播对象下可用的黑料卡（黑料主人不可等于传播对象）。"""
        target_npc_id = str(target_npc_id or "").strip()
        cards: list[dict] = []
        for card in self._serialize_recorded_cards():
            if str(card.get("record_type", "")).strip().lower() != "blackmail":
                continue
            subject_id = str(card.get("subject_npc_id", "")).strip()
            if not subject_id or subject_id == target_npc_id:
                continue
            subject_npc = self.state.npcs.get(subject_id)
            if subject_npc is None or not getattr(subject_npc, "alive", False):
                continue
            cards.append(card)
        return cards

    def _available_blackmail_cards_for_room_npcs(self, room_npc_ids: list[str]) -> list[dict]:
        """筛选在群体传播场景下可用的黑料卡（黑料主人不可在同房NPC集合内）。"""
        room_set = {str(x).strip() for x in room_npc_ids if str(x).strip()}
        cards: list[dict] = []
        for card in self._serialize_recorded_cards():
            if str(card.get("record_type", "")).strip().lower() != "blackmail":
                continue
            subject_id = str(card.get("subject_npc_id", "")).strip()
            if not subject_id or subject_id in room_set:
                continue
            subject_npc = self.state.npcs.get(subject_id)
            if subject_npc is None or not getattr(subject_npc, "alive", False):
                continue
            cards.append(card)
        return cards

    def _get_recorded_card_by_id(self, card_id: str):
        cid = str(card_id or "").strip()
        if not cid:
            return None
        for rc in self.state.player.record_cards:
            if rc.id == cid and rc.status.value == "recorded":
                return rc
        return None

    def _consume_blackmail_record_card(self, card_id: str) -> bool:
        card = self._get_recorded_card_by_id(card_id)
        if card is None:
            return False
        if str(getattr(card, "record_type", "")).strip().lower() != "blackmail":
            return False
        self.state.player.record_cards.remove(card)
        if card in self.state.evidence_collected:
            self.state.evidence_collected.remove(card)
        return True

    async def _generate_distorted_blackmail_summary(self, subject_npc_name: str, original_summary: str) -> str:
        import re

        subject = str(subject_npc_name or "").strip() or "某同事"
        original = str(original_summary or "").strip() or "有些见不得人的旧事"
        fallback = f"又有人说{subject}最近不太对劲，背后肯定有鬼。"
        prompt = PromptRegistry.render(
            "distorted_blackmail_prompt",
            subject=subject,
            original=original,
        )
        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.95,
                max_tokens=90,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).replace("\r", "\n").strip()
            one_line = cleaned.split("\n")[0].strip(" \t\"'“”‘’")
            if subject not in one_line:
                one_line = f"{subject}{one_line}"
            if len(one_line) > 60:
                one_line = one_line[:60].rstrip("，。；、 ") + "。"
            if not one_line:
                one_line = fallback
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="BLACKMAIL_DISTORT",
                context={"subject": subject},
                system_prompt="",
                user_prompt=prompt,
                raw_reply=raw,
                final_output=one_line,
                status="success",
                elapsed_ms=_elapsed,
            )
            return one_line
        except Exception as e:
            AILogger.log_call(
                call_type="BLACKMAIL_DISTORT",
                context={"subject": subject},
                system_prompt="",
                user_prompt=prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback,
                status="fallback",
                elapsed_ms=0,
            )
            return fallback

    @staticmethod
    def _solo_evidence_element(current_task) -> str:
        if not current_task or current_task.evidence_type is None:
            return "本次事件无证据"
        type_map = {
            "product_fake": "产品造假",
            "finance_fake": "财务造假",
            "employee_abuse": "员工压榨",
            "safety_hazard": "安全隐患",
            "corruption": "高层腐败",
        }
        e_val = str(getattr(current_task.evidence_type, "value", "")).strip()
        return type_map.get(e_val, e_val or "本次事件无证据")

    def _set_hour_settlement_context(
        self,
        *,
        is_blackmail: bool,
        participant_npc_ids: list[str] | None = None,
        blackmail_listener_ids: list[str] | None = None,
    ) -> None:
        self._hour_settlement_context = {
            "is_blackmail": bool(is_blackmail),
            "participant_npc_ids": [str(x).strip() for x in (participant_npc_ids or []) if str(x).strip()],
            "blackmail_listener_ids": [str(x).strip() for x in (blackmail_listener_ids or []) if str(x).strip()],
        }
        self._hour_bystander_resolved = False

    def _current_task_for_npc(self, npc_id: str):
        npc = self.state.npcs.get(str(npc_id))
        if npc is None or not npc.alive:
            return None
        idx = int(getattr(npc, "current_task_index", -1))
        tasks = list(getattr(npc, "selected_tasks", []) or [])
        if idx < 0 or idx >= len(tasks):
            return None
        return tasks[idx]

    def _current_task_for_player(self):
        player = self.state.player
        idx = int(getattr(player, "current_task_index", -1))
        tasks = list(getattr(player, "selected_tasks", []) or [])
        if idx < 0 or idx >= len(tasks):
            return None
        return tasks[idx]

    def _build_room_dispatch_context(self, room_key: str, occupants: dict) -> dict:
        player_present = bool(occupants.get("player_present", False))
        boss_present = bool(occupants.get("boss_present", False))
        npc_ids = [str(x).strip() for x in occupants.get("npcs", []) if str(x).strip()]
        npc_count = len(npc_ids)
        npc_names = [self._npc_display_name(nid, nid) for nid in npc_ids]

        player_task = self._current_task_for_player()
        player_task_id = str(getattr(player_task, "id", "")).strip()
        npc_task_ids: dict[str, str] = {}
        for npc_id in npc_ids:
            task = self._current_task_for_npc(npc_id)
            npc_task_ids[npc_id] = str(getattr(task, "id", "")).strip()

        has_same_work_with_player = False
        if player_task_id:
            has_same_work_with_player = any(
                bool(task_id) and task_id == player_task_id
                for task_id in npc_task_ids.values()
            )

        same_work_between_two_npcs = False
        if npc_count == 2:
            left_id, right_id = npc_ids[0], npc_ids[1]
            left_task = str(npc_task_ids.get(left_id, "")).strip()
            right_task = str(npc_task_ids.get(right_id, "")).strip()
            same_work_between_two_npcs = bool(left_task) and left_task == right_task

        pua_planned = bool(getattr(self.state.daily, "pua_triggered", False))
        if not pua_planned:
            pua_planned = (
                boss_present
                and str(getattr(self.state.boss, "current_behavior", "")).strip().lower()
                == str(BossBehavior.PUA).strip().lower()
            )

        return {
            "room": str(room_key or "").strip(),
            "player_present": player_present,
            "boss_present": boss_present,
            "npc_ids": npc_ids,
            "npc_names": npc_names,
            "npc_count": npc_count,
            "player_task_id": player_task_id,
            "npc_task_ids": npc_task_ids,
            "has_same_work_with_player": has_same_work_with_player,
            "same_work_between_two_npcs": same_work_between_two_npcs,
            "pua_planned": pua_planned,
            "day": int(self.state.current_day),
            "hour": int(self.state.current_hour),
        }

    @staticmethod
    def _determine_room_case_id(room_ctx: dict) -> int:
        player_present = bool(room_ctx.get("player_present", False))
        boss_present = bool(room_ctx.get("boss_present", False))
        npc_count = int(room_ctx.get("npc_count", 0))
        same_with_player = bool(room_ctx.get("has_same_work_with_player", False))
        same_between_two = bool(room_ctx.get("same_work_between_two_npcs", False))

        # 情况一：玩家独自
        if player_present and (not boss_present) and npc_count == 0:
            return 1
        # 情况一：NPC独自（玩家不在）
        if (not player_present) and (not boss_present) and npc_count == 1:
            return 1
        # 情况十二：经理独自
        if (not player_present) and boss_present and npc_count == 0:
            return 12
        # 情况二 / 三：玩家 + 1NPC（经理不在）
        if player_present and (not boss_present) and npc_count == 1:
            return 2 if same_with_player else 3
        # 情况四：玩家 + 经理
        if player_present and boss_present and npc_count == 0:
            return 4
        # 情况五：经理 + 1NPC（玩家不在）
        if (not player_present) and boss_present and npc_count == 1:
            return 5
        # 情况六 / 七：2NPC（玩家/经理都不在）
        if (not player_present) and (not boss_present) and npc_count == 2:
            return 6 if same_between_two else 7
        # 情况八：经理 + 多NPC（玩家不在）
        if (not player_present) and boss_present and npc_count >= 2:
            return 8
        # 情况九 / 十：玩家 + 多NPC（经理可在可不在）
        if player_present and npc_count >= 2:
            return 9 if same_with_player else 10
        # 情况十一：多NPC（玩家和经理都不在）
        if (not player_present) and (not boss_present) and npc_count >= 3:
            return 11
        return 0

    def _cache_room_case_result(self, room_key: str, case_id: int, payload: dict | None = None) -> None:
        self._hour_room_case_cache[str(room_key)] = {
            "day": int(self.state.current_day),
            "hour": int(self.state.current_hour),
            "room": str(room_key),
            "case_id": int(case_id),
            "payload": dict(payload or {}),
        }

    def _log_witness_event(
        self,
        *,
        source: str,
        observer_id: str,
        target_id: str,
        room_key: str,
        text: str,
        extra: dict | None = None,
    ) -> None:
        observer = str(observer_id or "").strip()
        target = str(target_id or "").strip()
        room = str(room_key or "").strip() or str(getattr(self.state.player.current_room, "value", ""))
        if not observer or not target:
            return
        observer_name = self._npc_display_name(observer, observer)
        if target == "player":
            target_name = str(self.state.player.name or "玩家").strip() or "玩家"
        elif target == "boss":
            target_name = self._npc_display_name("boss", "经理")
        else:
            target_name = self._npc_display_name(target, target)
        payload = {
            "day": int(self.state.current_day),
            "hour": int(self.state.current_hour),
            "room": room,
            "source": str(source or "").strip() or "unknown",
            "observer_id": observer,
            "observer_name": observer_name,
            "target_id": target,
            "target_name": target_name,
            "text": str(text or "").strip(),
        }
        if extra:
            payload.update({str(k): v for k, v in dict(extra).items()})
        self._work_logger.info("[WITNESS] %s", payload)

    def _get_cached_room_scout_text(self, room_key: str, target_npc_id: str = "") -> str:
        cache = dict(self._hour_room_case_cache.get(str(room_key), {}) or {})
        if not cache:
            return ""
        if int(cache.get("day", -1)) != int(self.state.current_day):
            return ""
        if int(cache.get("hour", -1)) != int(self.state.current_hour):
            return ""
        payload = dict(cache.get("payload", {}) or {})
        target_id = str(target_npc_id or "").strip()
        by_npc = dict(payload.get("scout_by_npc_id", {}) or {})
        if target_id and target_id in by_npc:
            return str(by_npc.get(target_id, "")).strip()
        return str(payload.get("scout_text", "")).strip()

    def _is_cached_room_manager_pua(self, room_key: str, target_npc_id: str = "") -> bool:
        cache = dict(self._hour_room_case_cache.get(str(room_key), {}) or {})
        if not cache:
            return False
        if int(cache.get("day", -1)) != int(self.state.current_day):
            return False
        if int(cache.get("hour", -1)) != int(self.state.current_hour):
            return False
        payload = dict(cache.get("payload", {}) or {})
        msg = str(payload.get("message", "")).strip().lower()
        if "pua" not in msg:
            return False
        target_id = str(target_npc_id or "").strip()
        if not target_id:
            return True
        by_npc = dict(payload.get("scout_by_npc_id", {}) or {})
        return target_id in by_npc

    def _is_boss_pua_condition_met(self, target_id: str) -> bool:
        """
        判定当前情境是否触发 PUA:
        Agent 化版本——以经理 AI 早上的决策为准,不再看怀疑度阈值。
        """
        target = str(target_id or "").strip()
        # ===== Debug 日志(诊断 PUA 第 2 天起失效) =====
        self._work_logger.info(
            "[BOSS_PUA_CHECK] day=%s | target=%s | executed=%s | ai_target=%s | ai_hour=%s | current_hour=%s",
            int(getattr(self.state, "current_day", 0)),
            target,
            getattr(self.state.daily, "boss_pua_executed", "MISSING"),
            getattr(self.state.daily, "boss_pua_target_id", "MISSING"),
            getattr(self.state.daily, "boss_pua_hour", "MISSING"),
            getattr(self.state, "current_hour", "MISSING"),
        )
        if not target:
            return False
        # 今日已 PUA 过一次,不再触发
        if bool(getattr(self.state.daily, "boss_pua_executed", False)):
            return False
        # 检查 AI 决策的目标和时间
        ai_target = str(getattr(self.state.daily, "boss_pua_target_id", "") or "").strip()
        ai_hour = int(getattr(self.state.daily, "boss_pua_hour", -1))
        if not ai_target or ai_hour < 0:
            return False
        # 目标必须匹配
        if target != ai_target:
            return False
        # 时间必须匹配
        current_hour = int(getattr(self.state, "current_hour", 0))
        if current_hour != ai_hour:
            return False
        return True

    async def _invoke_boss_pua_planning(self) -> None:
        """
        每天早上调一次经理 AI,决定今日 PUA 目标 + PUA 小时。
        结果写入 self.state.daily.boss_pua_target_id / boss_pua_hour。
        AI 拒绝时(target=""),今日不 PUA。
        """
        from .ai_service import AIService

        # 1. 重置当天 PUA 状态
        self.state.daily.boss_pua_target_id = ""
        self.state.daily.boss_pua_hour = -1
        self.state.daily.boss_pua_decision_reason = ""
        self.state.daily.boss_pua_executed = False

        # 2. 构建 AI 输入
        # 候选目标列表: 所有活着的 NPC + 玩家(boss 不能 PUA 自己)
        candidates: list[dict] = [{"id": "player", "name": self.state.player.name}]
        for npc_id, npc in self.state.npcs.items():
            if not getattr(npc, "alive", True):
                continue
            candidates.append({"id": npc_id, "name": getattr(npc, "name", npc_id)})

        # 经理对所有员工的关系账本(人话版,复用 memory_system)
        relations_text = "（无关系数据）"
        if self.memory is not None:
            try:
                relations_text = self.memory.build_memory_and_relations_text(
                    npc_id="boss",
                    relationships=self.state.relationships,
                    npcs=self.state.npcs,
                    player_name=self.state.player.name,
                    alive_only=True,
                )
            except Exception as e:
                self._work_logger.warning(f"[BOSS_PUA] build_memory_and_relations_text 失败: {e}")

        # 经理最近的记忆(取最近 5 条)
        recent_memories: list[str] = []
        if self.memory is not None:
            try:
                recent_memories = self.memory.get_memories("boss")[-5:]
            except Exception:
                recent_memories = []

        # 昨天 PUA 谁了
        last_pua_target_name = ""
        last_target_id = str(getattr(self, "_last_pua_target_id", "") or "")
        if last_target_id:
            last_pua_target_name = self._npc_display_name(last_target_id, last_target_id)

        # boss 身份和 aim
        dl = DataLoader()
        boss_identity = str(dl.get_npc_field("boss", "identity", "") or "").strip() or "八条触手的克苏鲁老板"
        boss_aim = str(dl.get_npc_field("boss", "aim", "") or "").strip() or "找出卧底,维持统治"

        # 3. 调 AI
        try:
            result = await AIService.generate_boss_pua_plan(
                boss_identity=boss_identity,
                boss_aim=boss_aim,
                boss_relations_text=relations_text,
                last_pua_target_name=last_pua_target_name,
                recent_memories=recent_memories,
                candidates=candidates,
                total_hours=DAILY_ACTION_POINTS,
            )
        except Exception as e:
            self._work_logger.warning(f"[BOSS_PUA] AI 调用异常: {e}")
            return

        # 4. 写入 state
        raw_target_id = str(result.get("target_id", "") or "").strip()
        target_id = self._apply_boss_pua_target_guardrails(raw_target_id)
        hour = int(result.get("hour", -1) if result.get("hour") is not None else -1)
        reason = str(result.get("reason", "") or "").strip()
        patrol_rooms_keys = list(result.get("patrol_rooms", []) or [])
        if raw_target_id != target_id:
            self._work_logger.info(
                "[BOSS_PUA_GUARD] 目标替换: raw=%s -> final=%s (day=%s, streak=%s, last_target=%s, last_day=%s)",
                raw_target_id,
                target_id,
                int(getattr(self.state, "current_day", 0)),
                int(getattr(self, "_pua_same_target_streak", 0)),
                str(getattr(self, "_last_pua_target_id", "")),
                int(getattr(self, "_last_pua_day", 0)),
            )

        self.state.daily.boss_pua_target_id = target_id
        self.state.daily.boss_pua_hour = hour
        self.state.daily.boss_pua_decision_reason = reason

        # ===== 新增: 把 AI 的全天行程写入 boss_hourly_plan + boss.patrol_rooms =====
        # 这套写入彻底接管老 BOSS_PLAN 系统的职责
        from .enums import BossBehavior, Room
        room_key_to_enum = {
            "office": Room.OFFICE,
            "meeting": Room.MEETING,
            "warehouse": Room.WAREHOUSE,
            "pantry": Room.PANTRY,
            "reception": Room.RECEPTION,
            "boss_office": Room.BOSS_OFFICE,
        }

        total_hours = int(getattr(self.state.daily, "daily_action_points", 5) or 5)
        # 兜底: 不足时用 office 补齐
        while len(patrol_rooms_keys) < total_hours:
            patrol_rooms_keys.append("office")
        # 截断超长
        patrol_rooms_keys = patrol_rooms_keys[:total_hours]

        # 构建 boss_hourly_plan(每小时的行为):
        # PUA 那一小时填 BossBehavior.PUA,其他小时填 BossBehavior.PATROL
        plan: list = []
        patrol_enums: list = []
        for h in range(total_hours):
            if h == hour and target_id:
                # PUA 小时: 行为=PUA,房间=经理办公室
                plan.append(BossBehavior.PUA)
                patrol_enums.append(Room.BOSS_OFFICE)
            else:
                # 普通小时: 行为=PATROL,房间=AI 选的
                plan.append(BossBehavior.PATROL)
                room_enum = room_key_to_enum.get(patrol_rooms_keys[h], Room.OFFICE)
                patrol_enums.append(room_enum)

        self.state.daily.boss_hourly_plan = plan
        self.state.boss.patrol_rooms = patrol_enums

        if target_id and hour >= 0:
            target_name = self._npc_display_name(target_id, target_id)
            self._work_logger.info(
                "[BOSS_PUA] 今日决策: target=%s(%s) hour=%d reason=%s",
                target_id, target_name, hour, reason[:60],
            )
            self._work_logger.info(
                "[BOSS_PUA] 全天行程: hourly_plan=%s patrol_rooms=%s",
                [str(p) for p in plan],
                [str(r) for r in patrol_enums],
            )
        else:
            self._work_logger.info(
                "[BOSS_PUA] 今日决策: 不 PUA, 全天巡视 patrol_rooms=%s",
                [str(r) for r in patrol_enums],
            )

    def _record_last_pua_target(self, target_id: str) -> None:
        """PUA 执行成功后调用,缓存目标供下次决策参考。"""
        target = str(target_id or "").strip()
        if not target:
            return
        current_day = int(getattr(self.state, "current_day", 0))
        last_target = str(getattr(self, "_last_pua_target_id", "") or "").strip()
        last_day = int(getattr(self, "_last_pua_day", 0))
        if target == last_target and current_day == last_day + 1:
            self._pua_same_target_streak = int(getattr(self, "_pua_same_target_streak", 0)) + 1
        else:
            self._pua_same_target_streak = 1
        self._last_pua_target_id = target
        self._last_pua_day = current_day

    def _pick_random_pua_target_replacement(self, *, exclude_ids: set[str], allow_player: bool) -> str:
        candidates: list[str] = []
        if allow_player:
            candidates.append("player")
        for npc_id, npc in self.state.npcs.items():
            if not getattr(npc, "alive", True):
                continue
            candidates.append(str(npc_id))
        filtered = [c for c in candidates if c not in exclude_ids]
        if not filtered:
            return ""
        return str(random.choice(filtered))

    def _apply_boss_pua_target_guardrails(self, planned_target_id: str) -> str:
        """
        对 AI 已选目标做最小后处理（不改 AI）:
        1) 第 1 天不能 PUA 玩家；
        2) 同一目标最多连续 2 天，第 3 天强制换人。
        """
        target = str(planned_target_id or "").strip()
        if target == "":
            return ""

        current_day = int(getattr(self.state, "current_day", 0))
        allow_player = current_day != 1

        # 规则1：第一轮(第1天)经理不能叫玩家
        if current_day == 1 and target == "player":
            replacement = self._pick_random_pua_target_replacement(
                exclude_ids={"player"},
                allow_player=False,
            )
            target = replacement if replacement else ""

        # 规则2：同一目标最多连续2天，第3天必须更换
        last_target = str(getattr(self, "_last_pua_target_id", "") or "").strip()
        last_day = int(getattr(self, "_last_pua_day", 0))
        streak = int(getattr(self, "_pua_same_target_streak", 0))
        projected_streak = 1
        if target and target == last_target and current_day == last_day + 1:
            projected_streak = streak + 1
        if target and projected_streak > 2:
            replacement = self._pick_random_pua_target_replacement(
                exclude_ids={target},
                allow_player=allow_player,
            )
            target = replacement if replacement else ""

        return target

    def _build_npc_pua_notification_text(self, target_id: str, target_name: str) -> str:
        text_tpl = DataLoader().get_fallback(
            "f15_npc_pua_notification",
            npc_id=str(target_id or "").strip(),
            default="你注意到经理把{npc_name}叫去了办公室，{npc_name}的脸色一下子白了。",
        )
        text = str(text_tpl or "").strip() or "你注意到经理把{npc_name}叫去了办公室，{npc_name}的脸色一下子白了。"
        try:
            text = text.format(npc_name=str(target_name or "").strip() or "某同事")
        except Exception:
            pass
        return text

    def _cache_last_pua_snapshot(self, *, target_id: str, full_text: str, opening_text: str, reaction_text: str, ending_text: str) -> None:
        self._last_pua_snapshot = {
            "day": int(self.state.current_day),
            "hour": int(self.state.current_hour),
            "room": str(getattr(self.state.boss.current_room, "value", "") or ""),
            "target_id": str(target_id or "").strip(),
            "full_text": str(full_text or "").strip(),
            "opening_text": str(opening_text or "").strip(),
            "reaction_text": str(reaction_text or "").strip(),
            "ending_text": str(ending_text or "").strip(),
        }

    def _get_active_pua_full_text_for_scout(self, room_key: str, chosen_target_id: str) -> str:
        if not bool(getattr(self.state.daily, "boss_pua_executed", False)):
            return ""
        target_id = str(getattr(self.state.daily, "boss_pua_target_id", "") or "").strip()
        if not target_id or target_id == "player":
            return ""
        if int(getattr(self.state.daily, "boss_pua_hour", -1)) != int(self.state.current_hour):
            return ""
        room = str(room_key or "").strip()
        boss_room = str(getattr(self.state.boss.current_room, "value", "") or "").strip()
        if room == "" or room != boss_room:
            return ""

        target_npc = self.state.npcs.get(target_id)
        target_room = str(getattr(getattr(target_npc, "current_room", None), "value", "") or "").strip()
        if target_room != room:
            return ""

        chosen_id = str(chosen_target_id or "").strip()
        if chosen_id and chosen_id not in ["boss", target_id]:
            return ""

        snap = dict(self._last_pua_snapshot or {})
        if (
            int(snap.get("day", -1)) == int(self.state.current_day)
            and int(snap.get("hour", -1)) == int(self.state.current_hour)
            and str(snap.get("target_id", "")).strip() == target_id
            and str(snap.get("room", "")).strip() == room
        ):
            full_text = str(snap.get("full_text", "") or "").strip().replace("\\n", "\n")
            if full_text:
                return full_text
            pieces = [
                str(snap.get("opening_text", "") or "").strip().replace("\\n", "\n"),
                str(snap.get("reaction_text", "") or "").strip().replace("\\n", "\n"),
                str(snap.get("ending_text", "") or "").strip().replace("\\n", "\n"),
            ]
            return "\n\n".join([p for p in pieces if p])

        # 兜底：极端情况下缓存缺失，回退到模板拼接并重新写回快照，避免改走 AI 导致文风跳变
        segments = DataLoader().pick_pua_segments(target_id) or {}
        opening_text = str(segments.get("opening_text", "") or "").strip().replace("\\n", "\n")
        reaction_text = str(segments.get("reaction_text", "") or "").strip().replace("\\n", "\n")
        ending_text = str(segments.get("ending_text", "") or "").strip().replace("\\n", "\n")
        full_text = str(segments.get("full_text", "") or "").strip().replace("\\n", "\n")
        if not full_text:
            full_text = "\n\n".join([p for p in [opening_text, reaction_text, ending_text] if p])
        if full_text:
            self._cache_last_pua_snapshot(
                target_id=target_id,
                full_text=full_text,
                opening_text=opening_text,
                reaction_text=reaction_text,
                ending_text=ending_text,
            )
        return full_text

    async def _execute_boss_pua(self, target_id: str) -> dict:
        """
        执行 PUA: 拼接模板剧情 + 落库经理记忆 + 经理对目标的好感/怀疑变化。

        返回:
            {
                "success": bool,
                "target_id": str,
                "target_name": str,
                "full_text": str,        # 完整 PUA 剧情(给前端展示)
                "is_player_target": bool,
            }
        """
        target = str(target_id or "").strip()
        if not target:
            return {"success": False, "target_id": "", "target_name": "", "full_text": "", "is_player_target": False}

        is_player = target == "player"
        target_name = self.state.player.name if is_player else self._npc_display_name(target, target)

        # 记录目标原房间（用于旁观者记忆）
        original_room = self.state.player.current_room if is_player else None
        if not is_player:
            npc_state = self.state.npcs.get(target)
            if npc_state is not None:
                original_room = npc_state.current_room

        # 拼接 PUA 剧情
        dl = DataLoader()
        segments = dl.pick_pua_segments(target)
        if segments is None:
            self._work_logger.warning(f"[BOSS_PUA] 模板缺失,无法 PUA target={target}")
            return {"success": False, "target_id": target, "target_name": target_name, "full_text": "", "is_player_target": is_player}

        # 强制场景: 经理 + 目标 都被拉到经理办公室
        self.state.boss.current_room = Room.BOSS_OFFICE
        if is_player:
            self.state.player.current_room = Room.BOSS_OFFICE
        else:
            npc = self.state.npcs.get(target)
            if npc and getattr(npc, "alive", True):
                npc.current_room = Room.BOSS_OFFICE

        # 落 PUA 记忆: 调 AI 把整段剧本压缩成 boss 和 target NPC 两个视角的第一人称回忆
        full_pua_text = str(segments.get("full_text", "") or "").strip()
        if self.memory is not None and full_pua_text:
            recap = await AIService.generate_pua_memory_recap(
                target_name=target_name,
                full_pua_text=full_pua_text,
            )
            boss_memory = str(recap.get("boss_memory", "")).strip()
            if boss_memory:
                self.memory.add_impression(
                    observer_id="boss",
                    target_id=target,
                    day=int(self.state.current_day),
                    impression_text=boss_memory,
                    sealed=False,
                    source="pua",
                )
            # 玩家被 PUA 不写 target NPC 记忆 (player 不在 NPC memory 体系里)
            if not is_player:
                target_memory = str(recap.get("target_memory", "")).strip()
                if target_memory:
                    self.memory.add_impression(
                        observer_id=target,
                        target_id="boss",
                        day=int(self.state.current_day),
                        impression_text=target_memory,
                        sealed=False,
                        source="pua_target",
                    )

        # 经理对目标的关系变化(NPC 才有,玩家不变)
        aff_delta = int(segments.get("affinity_delta", 0) or 0)
        sus_delta = int(segments.get("suspicion_delta", 0) or 0)
        if (not is_player) and (aff_delta != 0 or sus_delta != 0):
            self.manager.modify_affinity("boss", target, aff_delta)
            self.manager.modify_suspicion("boss", target, sus_delta)

        # 标记今日 PUA 已执行
        self.state.daily.boss_pua_executed = True
        self.state.daily.pua_triggered = True  # 兼容旧字段
        self.state.boss.current_behavior = BossBehavior.PUA
        self.state.boss.target_npc = target
        if not is_player:
            self._pending_npc_pua_notification = self._build_npc_pua_notification_text(target, target_name)

        # 缓存供下次 AI 决策
        self._record_last_pua_target(target)

        # 旁观者记忆: 同房间内其他 NPC 看到目标被叫去经理办公室
        # (按设计: 仅怀疑度 +5,好感不变)
        if original_room and original_room != Room.BOSS_OFFICE:
            for npc_id, npc in self.state.npcs.items():
                if npc_id == target or not getattr(npc, "alive", True):
                    continue
                if npc.current_room == original_room:
                    if self.memory is not None:
                        self.memory.add_impression(
                            observer_id=npc_id,
                            target_id=target,
                            day=int(self.state.current_day),
                            impression_text=f"我看见{target_name}被经理叫到办公室谈话了。",
                            sealed=False,
                            source="pua_witness",
                        )
                    self.manager.modify_suspicion(npc_id, target, 5)

        self._work_logger.info(
            "[BOSS_PUA] 执行: target=%s(%s) is_player=%s",
            target, target_name, is_player,
        )
        self._cache_last_pua_snapshot(
            target_id=target,
            full_text=str(segments.get("full_text", "") or ""),
            opening_text=str(segments.get("opening_text", "") or ""),
            reaction_text=str(segments.get("reaction_text", "") or ""),
            ending_text=str(segments.get("ending_text", "") or ""),
        )

        return {
            "success": True,
            "target_id": target,
            "target_name": target_name,
            "full_text": str(segments.get("full_text", "") or ""),
            "opening_text": str(segments.get("opening_text", "") or ""),
            "reaction_text": str(segments.get("reaction_text", "") or ""),
            "ending_text": str(segments.get("ending_text", "") or ""),
            "is_player_target": is_player,
        }

    def _build_pua_player_event_result(self, pua_result: dict) -> dict:
        """
        玩家被 PUA 时的 card_result 构建。
        玩家不出牌,直接展示剧情,然后进入下一小时。
        """
        full_text = str(pua_result.get("full_text", "") or "")

        result = {
            "success": True,
            "is_pua_event": True,
            "act1_text": "",
            "act2_text": full_text,
            "evidence": None,
            "blame_card": None,
            "can_use_record_card": False,  # PUA 事件玩家不能记录
            "negotiation": None,
            "scout_available_rooms": [],
            "scout_result": None,
            "economy_snapshot": self._build_economy_snapshot(),
            "summary_text": "你被经理叫去谈话了。",
        }

        # 复用既有协议标记，便于上层按 card_result 处理
        result["_response_type"] = "card_result"

        # 让 PUA 事件 result 也经过标准小时收尾,与普通事件保持一致
        self._advance_hour_after_pua(result)

        return result

    def _advance_hour_after_pua(self, result: dict) -> None:
        """
        PUA 事件结算: 让 PUA 的 card_result 走标准的小时收尾路径,
        与普通事件保持一致(否则下一小时分发会回退到 solo)。

        注意: 不在这里调 advance_hour——小时推进由前端点[继续]后的
        advance_to_next_hour 处理。
        """
        try:
            self._finalize_hour_settlement_for_result(result)
        except Exception as e:
            self._work_logger.warning(f"[BOSS_PUA] _finalize_hour_settlement_for_result 失败: {e}")

    def _grant_auto_blackmail_card(
        self,
        *,
        subject_npc_id: str,
        summary_text: str,
    ) -> dict:
        subject_id = str(subject_npc_id or "").strip()
        summary = str(summary_text or "").strip()
        if not subject_id or not summary:
            return {}
        subject_name = self._npc_display_name(subject_id, subject_id)
        next_index = len(self.state.player.record_cards) + len(self.state.evidence_collected) + 1
        card_id = f"rc_{next_index:03d}"
        card = RecordCard(
            id=card_id,
            status=RecordCardStatus.RECORDED,
            record_type="blackmail",
            linked_evidence_tag="",
            source_description=f"anomaly:{subject_name}",
            day_recorded=self.state.current_day,
            subject_npc_id=subject_id,
            subject_npc_name=subject_name,
            summary_text=summary[:100],
            is_evidence=False,
        )
        self.state.player.record_cards.append(card)
        return {
            "card_id": card_id,
            "subject_npc_id": subject_id,
            "subject_npc_name": subject_name,
            "summary_text": summary[:100],
        }

    def _maybe_trigger_case3_anomaly(self) -> dict:
        ctx = dict(self._pending_case3_anomaly_context or {})
        self._pending_case3_anomaly_context = {}
        if not ctx:
            return {}
        if random.random() >= 0.25:
            return {}
        npc_id = str(ctx.get("npc_id", "")).strip()
        if not npc_id:
            return {}
        event = DataLoader().get_npc_anomaly_event(npc_id)
        text = str(event.get("text", "")).strip()
        if not text:
            return {}
        card_info = self._grant_auto_blackmail_card(
            subject_npc_id=npc_id,
            summary_text=text,
        )
        return {
            "triggered": True,
            "text": text,
            "subject_npc_id": npc_id,
            "subject_npc_name": self._npc_display_name(npc_id, npc_id),
            "card": card_info,
        }

    @staticmethod
    def _solo_style_to_act2_pool(style: str) -> str:
        key = str(style or "").strip().lower()
        mapping = {
            "normal": "solo_act2_steady",
            "corporate": "solo_act2_comply",
            "rebel": "solo_act2_rebel",
            "chaotic": "solo_act2_crazy",
        }
        return mapping.get(key, "solo_act2_contrast")

    def _pick_room_element_text(self, room_key: str, pool: str, fallback: str = "") -> str:
        source = str(room_key or "").strip().lower()
        dl = DataLoader()
        row = dl.pick_weighted_element_row("solo_common", pool)
        if not row:
            row = dl.pick_weighted_element_row(source, pool)
        text = str((row or {}).get("text", "")).strip()
        if text:
            return text
        return str(fallback or "").strip()

    def _grant_auto_evidence_record_card(self, evidence_tag: str, summary_text: str) -> dict:
        tag = str(evidence_tag or "").strip()
        summary = str(summary_text or "").strip()
        if not tag.startswith("evidence_"):
            return {}
        next_index = len(self.state.player.record_cards) + len(self.state.evidence_collected) + 1
        card_id = f"rc_{next_index:03d}"
        card = RecordCard(
            id=card_id,
            status=RecordCardStatus.RECORDED,
            record_type="evidence",
            linked_evidence_tag=tag,
            source_description="solo_reward:boss_secret",
            day_recorded=self.state.current_day,
            subject_npc_id="boss",
            subject_npc_name=self._npc_display_name("boss", "经理"),
            summary_text=summary[:100],
            is_evidence=True,
        )
        self.state.player.record_cards.append(card)
        self.state.evidence_collected.append(card)
        return {
            "card_id": card_id,
            "evidence_tag": tag,
            "summary_text": summary[:100],
        }

    def _resolve_solo_reward(self, room_key: str, current_task) -> dict:
        if random.random() >= 0.5:
            return {}
        dl = DataLoader()
        row = dl.pick_weighted_element_row(str(room_key or "").strip().lower(), "solo_reward")
        if not row:
            row = dl.pick_weighted_element_row("solo_common", "solo_reward")
        if not row:
            return {}
        reward_type = str(row.get("reward_type", "")).strip().lower()
        text_tpl = str(row.get("text", "")).strip()
        payload = {
            "text": "",
            "reward_type": reward_type or "none",
            "gold_delta": 0,
            "blank_cards_delta": 0,
            "blackmail_card": {},
            "evidence_card": {},
        }
        if reward_type == "gold":
            min_v = row.get("reward_value_min")
            max_v = row.get("reward_value_max")
            try:
                lo = int(min_v if min_v is not None else 15)
            except (TypeError, ValueError):
                lo = 15
            try:
                hi = int(max_v if max_v is not None else lo)
            except (TypeError, ValueError):
                hi = lo
            if hi < lo:
                lo, hi = hi, lo
            amount = random.randint(lo, hi)
            self.manager.modify_gold(amount)
            payload["gold_delta"] = amount
            payload["text"] = (text_tpl or "你在角落里摸到一小袋旧硬币，居然有{gold}金币。").format(gold=amount)
            return payload
        if reward_type == "blank_card":
            self.manager.add_record_card()
            payload["blank_cards_delta"] = 1
            payload["text"] = text_tpl or "你在文件夹夹层里翻到了一张空白记录卡。"
            return payload
        if reward_type == "blackmail":
            candidates = [
                npc_id for npc_id, npc in self.state.npcs.items()
                if getattr(npc, "alive", False)
            ]
            if not candidates:
                return {}
            subject_id = random.choice(candidates)
            subject_name = self._npc_display_name(subject_id, subject_id)
            reward_text = (text_tpl or "你在{npc_name}的工位边发现了一份可疑文件。").format(npc_name=subject_name)
            card_info = self._grant_auto_blackmail_card(
                subject_npc_id=subject_id,
                summary_text=reward_text,
            )
            payload["blackmail_card"] = card_info
            payload["text"] = reward_text
            return payload
        if reward_type == "boss_secret":
            reward_text = text_tpl or "你在废纸篓里翻到了一份经理的私人账单复印件。"
            ev_type = str(getattr(getattr(current_task, "evidence_type", None), "value", "")).strip().lower()
            ev_tag = str(getattr(current_task, "evidence_tag", "") or "").strip()
            if ev_type == "corruption" and ev_tag.startswith("evidence_"):
                ev_card = self._grant_auto_evidence_record_card(
                    evidence_tag=ev_tag,
                    summary_text=reward_text,
                )
                payload["evidence_card"] = ev_card
                payload["text"] = f"{reward_text} 这条线索直指高层腐败，你当场记成了证据。"
                return payload
            card_info = self._grant_auto_blackmail_card(
                subject_npc_id="boss",
                summary_text=reward_text,
            )
            payload["blackmail_card"] = card_info
            payload["text"] = reward_text
            return payload
        if reward_type == "none":
            payload["text"] = text_tpl
            return payload
        return {}

    async def _dispatch_player_frontstage_case(self, case_id: int, room_ctx: dict) -> dict | None:
        self._pending_case3_anomaly_context = {}
        self._active_front_case_id = int(case_id)
        self._active_front_case_ctx = dict(room_ctx or {})
        self._current_event_context["room_case_id"] = int(case_id)
        self._current_event_context["room_case_ctx"] = dict(room_ctx or {})
        # 经理 PUA 最高优先级：在前台分发入口统一拦截，避免任意 case 绕过。
        if self._is_boss_pua_condition_met("player"):
            pua_result = await self._execute_boss_pua("player")
            if pua_result.get("success"):
                return await self._trigger_pua_event(pua_result)
        if case_id == 1:
            skeleton_event = self.manager.trigger_skeleton_event(force_mode="solo")
            if skeleton_event:
                return await self._render_work_event_from_skeleton(skeleton_event)
            return await self.trigger_event_v2()
        if case_id == 3:
            npc_ids = list(room_ctx.get("npc_ids", []) or [])
            npc_id = str(npc_ids[0]).strip() if npc_ids else ""
            npc_task_id = str((room_ctx.get("npc_task_ids", {}) or {}).get(npc_id, "")).strip()
            self._pending_case3_anomaly_context = {
                "day": int(self.state.current_day),
                "hour": int(self.state.current_hour),
                "room": str(room_ctx.get("room", "")).strip(),
                "npc_id": npc_id,
                "npc_task_id": npc_task_id,
            }
            skeleton_event = self.manager.trigger_skeleton_event(force_mode="solo")
            if skeleton_event:
                return await self._render_work_event_from_skeleton(skeleton_event)
            return await self.trigger_event_v2()
        if case_id == 4:
            if self._is_boss_pua_condition_met("player"):
                pua_result = await self._execute_boss_pua("player")
                if pua_result.get("success"):
                    return await self._trigger_pua_event(pua_result)
            report_cards = self._available_blackmail_cards_for_target("boss")
            if report_cards:
                self._pending_work_mode_choice = {
                    "choice_variant": "solo_or_report_boss",
                    "candidates": [],
                    "duo_candidate": {},
                    "blackmail_target": {"id": "boss", "name": self._npc_display_name("boss", "经理")},
                    "blackmail_targets": [],
                    "blackmail_room_npc_ids": [],
                    "blackmail_cards": report_cards,
                    "debug_scenario_code": "CASE4",
                    "debug_choice_source": "solo_or_report_boss",
                }
                self._current_event_card_mode = "work_mode_choice"
                return self._build_work_mode_choice_event(
                    candidates=[],
                    choice_variant="solo_or_report_boss",
                    blackmail_target={"id": "boss", "name": self._npc_display_name("boss", "经理")},
                    blackmail_cards=report_cards,
                    debug_scenario_code="CASE4",
                    debug_choice_source="solo_or_report_boss",
                )
            skeleton_event = self.manager.trigger_skeleton_event(force_mode="solo")
            if skeleton_event:
                return await self._render_work_event_from_skeleton(skeleton_event)
            return await self.trigger_event_v2()
        if case_id == 10:
            npc_ids = [str(x).strip() for x in room_ctx.get("npc_ids", []) if str(x).strip()]
            chosen_npc = random.choice(npc_ids) if npc_ids else ""
            if chosen_npc:
                self._pending_case3_anomaly_context = {
                    "day": int(self.state.current_day),
                    "hour": int(self.state.current_hour),
                    "room": str(room_ctx.get("room", "")).strip(),
                    "npc_id": chosen_npc,
                    "npc_task_id": str((room_ctx.get("npc_task_ids", {}) or {}).get(chosen_npc, "")).strip(),
                }
            return await self.trigger_event_v2()
        if case_id in {2, 9}:
            return await self.trigger_event_v2()
        if case_id == 5:
            skeleton_event = self.manager.trigger_skeleton_event(force_mode="solo")
            if skeleton_event:
                return await self._render_work_event_from_skeleton(skeleton_event)
        return await self.trigger_event_v2()

    async def _dispatch_background_case(self, case_id: int, room_ctx: dict) -> dict:
        handlers = {
            1: self._handle_case_1,
            2: self._handle_case_2,
            3: self._handle_case_3,
            4: self._handle_case_4,
            5: self._handle_case_5,
            6: self._handle_case_6,
            7: self._handle_case_7,
            8: self._handle_case_8,
            9: self._handle_case_9,
            10: self._handle_case_10,
            11: self._handle_case_11,
            12: self._handle_case_12,
        }
        handler = handlers.get(case_id, self._handle_case_unknown)
        return await handler(room_ctx)

    async def _dispatch_current_hour_rooms(self, *, generate_player_event: bool = True) -> dict | None:
        """
        每小时统一分发器：
        1) 玩家房间：前台事件（可交互）
        2) 其他房间：后台静默处理（占位，不改现有玩法）
        """
        # ===== Batch 9: 全局 PUA 调度(NPC 目标) =====
        # 玩家被 PUA 的场景由 _dispatch_player_frontstage_case 顶部的玩家分支处理。
        # 本段只处理 NPC 被 PUA 的场景——避免依赖"玩家在场"导致漏触发。
        ai_target = str(getattr(self.state.daily, "boss_pua_target_id", "") or "").strip()
        ai_hour = int(getattr(self.state.daily, "boss_pua_hour", -1))
        current_hour = int(getattr(self.state, "current_hour", 0))
        pua_already_executed = bool(getattr(self.state.daily, "boss_pua_executed", False))

        if (
            ai_target
            and ai_target != "player"  # 玩家分支由 _dispatch_player_frontstage_case 处理
            and ai_hour == current_hour
            and not pua_already_executed
        ):
            try:
                await self._execute_boss_pua(ai_target)
                self._work_logger.info(
                    "[BOSS_PUA] 全局调度执行: target=%s hour=%d",
                    ai_target, current_hour,
                )
            except Exception as e:
                self._work_logger.warning(
                    f"[BOSS_PUA] 全局调度执行失败: target={ai_target} error={e}"
                )
        # ===== 全局 PUA 调度结束,继续原有房间分发逻辑 =====

        from .room_system import RoomSystem

        self._hour_room_case_cache = {}
        snapshot = RoomSystem.get_all_room_occupants(self.state.player, self.state.npcs, self.state.boss)
        player_room = self.state.player.current_room.value

        player_event = None
        player_ctx = self._build_room_dispatch_context(player_room, snapshot.get(player_room, {}))
        player_case = self._determine_room_case_id(player_ctx)
        self._work_logger.info(
            "[ROOM_DISPATCH] day=%s hour=%s room=%s mode=front case=%s player=%s boss=%s npc_count=%s pua_planned=%s",
            self.state.current_day,
            self.state.current_hour,
            player_room,
            player_case,
            player_ctx.get("player_present"),
            player_ctx.get("boss_present"),
            player_ctx.get("npc_count"),
            player_ctx.get("pua_planned"),
        )
        self._cache_room_case_result(player_room, player_case, {"frontstage": True})
        if generate_player_event:
            player_event = await self._dispatch_player_frontstage_case(player_case, player_ctx)

        for room_key, occupants in snapshot.items():
            if room_key == player_room:
                continue
            room_ctx = self._build_room_dispatch_context(room_key, occupants)
            case_id = self._determine_room_case_id(room_ctx)
            self._work_logger.info(
                "[ROOM_DISPATCH] day=%s hour=%s room=%s mode=background case=%s player=%s boss=%s npc_count=%s pua_planned=%s",
                self.state.current_day,
                self.state.current_hour,
                room_key,
                case_id,
                room_ctx.get("player_present"),
                room_ctx.get("boss_present"),
                room_ctx.get("npc_count"),
                room_ctx.get("pua_planned"),
            )
            payload = await self._dispatch_background_case(case_id, room_ctx)
            self._cache_room_case_result(room_key, case_id, payload)

        return player_event

    async def _handle_case_unknown(self, room_ctx: dict) -> dict:
        return {"ok": True, "message": "case_unknown_placeholder", "room": room_ctx.get("room", "")}

    async def _handle_case_1(self, room_ctx: dict) -> dict:
        player_present = bool(room_ctx.get("player_present", False))
        room_key = str(room_ctx.get("room", "")).strip()
        if player_present:
            return {"ok": True, "message": "case_1_player_front", "room": room_key}
        npc_ids = list(room_ctx.get("npc_ids", []) or [])
        if not npc_ids:
            idle_text = DataLoader().get_room_idle(room_key)
            return {
                "ok": True,
                "message": "case_1_idle",
                "room": room_key,
                "scout_text": idle_text,
                "scout_by_npc_id": {},
            }
        npc_id = str(npc_ids[0]).strip()
        npc_task_id = str((room_ctx.get("npc_task_ids", {}) or {}).get(npc_id, "")).strip() or "any"
        obs = DataLoader().get_boss_observation(npc_id, npc_task_id)
        scout_text = str(obs.get("scout_text", "")).strip() or DataLoader().get_room_idle(room_key)
        return {
            "ok": True,
            "message": "case_1_npc_alone",
            "room": room_key,
            "scout_text": scout_text,
            "scout_by_npc_id": {npc_id: scout_text} if scout_text else {},
        }

    async def _handle_case_2(self, room_ctx: dict) -> dict:
        return {"ok": True, "message": "case_2_placeholder", "room": room_ctx.get("room", "")}

    async def _handle_case_3(self, room_ctx: dict) -> dict:
        return {"ok": True, "message": "case_3_placeholder", "room": room_ctx.get("room", "")}

    async def _handle_case_4(self, room_ctx: dict) -> dict:
        return {"ok": True, "message": "case_4_placeholder", "room": room_ctx.get("room", "")}

    async def _handle_case_5(self, room_ctx: dict) -> dict:
        room_key = str(room_ctx.get("room", "")).strip()
        npc_ids = list(room_ctx.get("npc_ids", []) or [])
        if not npc_ids:
            return {"ok": True, "message": "case_5_no_npc", "room": room_key}
        npc_id = str(npc_ids[0]).strip()
        npc_name = self._npc_display_name(npc_id, npc_id)
        npc_task_id = str((room_ctx.get("npc_task_ids", {}) or {}).get(npc_id, "")).strip() or "any"

        if self._is_boss_pua_condition_met(npc_id):
            pua_exec = await self._execute_boss_pua(npc_id)
            if pua_exec.get("success"):
                scout_text = str(pua_exec.get("full_text", "")).strip()
                return {
                    "ok": True,
                    "message": "case_5_pua_template",
                    "room": room_key,
                    "npc_id": npc_id,
                    "npc_name": npc_name,
                    "scout_text": scout_text,
                    "scout_by_npc_id": {npc_id: scout_text} if scout_text else {},
                    "memory_text": str(pua_exec.get("opening_text", "")).strip(),
                    "affinity_delta": 0,
                    "suspicion_delta": 0,
                }

        obs = DataLoader().get_boss_observation(npc_id, npc_task_id)
        memory_text = str(obs.get("memory_text", "")).strip()
        scout_text = str(obs.get("scout_text", "")).strip()
        if memory_text and self.memory:
            self.memory.add_impression(
                observer_id="boss",
                target_id=npc_id,
                day=self.state.current_day,
                impression_text=memory_text,
            )
            self.manager.append_relationship_reason("boss", npc_id, memory_text[:50])
            self._log_witness_event(
                source="case5_observe_boss_memory",
                observer_id="boss",
                target_id=npc_id,
                room_key=room_key,
                text=memory_text,
            )
        if not scout_text:
            scout_text = DataLoader().get_room_idle(room_key)
        return {
            "ok": True,
            "message": "case_5_boss_observe",
            "room": room_key,
            "npc_id": npc_id,
            "npc_name": npc_name,
            "scout_text": scout_text,
            "scout_by_npc_id": {npc_id: scout_text} if scout_text else {},
            "memory_text": memory_text,
        }

    async def _handle_case_6(self, room_ctx: dict) -> dict:
        room_key = str(room_ctx.get("room", "")).strip()
        rows = self._collect_room_npc_task_snapshot(room_key)
        if len(rows) < 2:
            return {"ok": True, "message": "case_6_no_pair", "room": room_key}
        pair = self._pair_npcs_for_same_task(rows)
        if not pair:
            return {"ok": True, "message": "case_6_no_pair", "room": room_key}
        a, b = pair[0]
        pair_info = self._resolve_npc_npc_template_interaction(
            npc_a_id=str(a.get("id", "")),
            npc_b_id=str(b.get("id", "")),
            task_name=str(a.get("task_name", "")).strip() or str(b.get("task_name", "")).strip(),
        )
        scout_text = str(pair_info.get("memory_text", "")).strip()
        return {
            "ok": True,
            "message": "case_6_pair_interaction",
            "room": room_key,
            "scout_text": scout_text,
            "f13_interactions": [
                {
                    "npc_a_id": str(a.get("id", "")),
                    "npc_b_id": str(b.get("id", "")),
                    "text": scout_text,
                }
            ] if scout_text else [],
        }

    async def _handle_case_7(self, room_ctx: dict) -> dict:
        room_key = str(room_ctx.get("room", "")).strip()
        room_npc_ids = [str(x).strip() for x in room_ctx.get("npc_ids", []) if str(x).strip()]
        gossip_result = self._resolve_room_gossip(
            room_npc_ids=room_npc_ids,
            room_key=room_key,
            allow_gossip=True,
        )
        if gossip_result.get("triggered"):
            return {
                "ok": True,
                "message": "case_7_gossip",
                "room": room_key,
                "scout_text": str(gossip_result.get("scout_text", "")).strip(),
                "gossip": gossip_result,
            }
        return {
            "ok": True,
            "message": "case_7_idle",
            "room": room_key,
            "scout_text": DataLoader().get_room_idle(room_key),
            "gossip": gossip_result,
        }

    async def _handle_case_8(self, room_ctx: dict) -> dict:
        room_key = str(room_ctx.get("room", "")).strip()
        npc_ids = [str(x).strip() for x in room_ctx.get("npc_ids", []) if str(x).strip()]
        if not npc_ids:
            return {
                "ok": True,
                "message": "case_8_no_npc",
                "room": room_key,
                "scout_text": DataLoader().get_room_idle(room_key),
            }

        pua_candidates = [
            npc_id for npc_id in npc_ids
            if int(self._boss_suspicion_to(npc_id)) >= 40
        ]
        pua_candidates.sort(key=lambda nid: (-int(self._boss_suspicion_to(nid)), nid))
        if pua_candidates and not bool(getattr(self.state.daily, "pua_triggered", False)):
            pua_target = pua_candidates[0]
            pua_payload = await self._handle_case_5(
                {
                    "room": room_key,
                    "player_present": False,
                    "boss_present": True,
                    "npc_ids": [pua_target],
                    "npc_task_ids": room_ctx.get("npc_task_ids", {}),
                }
            )
            witness_text = (
                f"我在{EvidenceConverter.ROOM_NAMES.get(Room(room_key), room_key)}看见经理把"
                f"{self._npc_display_name(pua_target, pua_target)}叫到一边谈话了。"
            )
            if self.memory:
                for witness_id in npc_ids:
                    if witness_id == pua_target:
                        continue
                    self.memory.add_impression(
                        observer_id=witness_id,
                        target_id=pua_target,
                        day=self.state.current_day,
                        impression_text=witness_text,
                    )
                    self._log_witness_event(
                        source="case8_pua_bystander",
                        observer_id=witness_id,
                        target_id=pua_target,
                        room_key=room_key,
                        text=witness_text,
                    )
                    if "boss" in self.state.relationships.get(witness_id, {}):
                        self.manager.append_relationship_reason(witness_id, "boss", witness_text[:50])
            pua_payload["case8_witness_text"] = witness_text
            pua_payload["message"] = "case_8_pua"
            return pua_payload

        chosen_for_boss = random.choice(npc_ids)
        chosen_task_id = str((room_ctx.get("npc_task_ids", {}) or {}).get(chosen_for_boss, "")).strip() or "any"
        boss_obs = DataLoader().get_boss_observation(chosen_for_boss, chosen_task_id)
        boss_memory = str(boss_obs.get("memory_text", "")).strip()
        if boss_memory and self.memory:
            self.memory.add_impression(
                observer_id="boss",
                target_id=chosen_for_boss,
                day=self.state.current_day,
                impression_text=boss_memory,
            )
            self.manager.append_relationship_reason("boss", chosen_for_boss, boss_memory[:50])
            self._log_witness_event(
                source="case8_boss_observation",
                observer_id="boss",
                target_id=chosen_for_boss,
                room_key=room_key,
                text=boss_memory,
            )

        rows = self._collect_room_npc_task_snapshot(room_key)
        pairs = self._pair_npcs_for_same_task(rows)
        f13_texts: list[str] = []
        for a, b in pairs:
            pair_info = self._resolve_npc_npc_template_interaction(
                npc_a_id=str(a.get("id", "")),
                npc_b_id=str(b.get("id", "")),
                task_name=str(a.get("task_name", "")).strip() or str(b.get("task_name", "")).strip(),
            )
            text = str(pair_info.get("memory_text", "")).strip()
            if text:
                f13_texts.append(text)

        scout_text = ""
        if f13_texts:
            scout_text = random.choice(f13_texts)
        else:
            scout_text = DataLoader().get_room_idle(room_key)
        return {
            "ok": True,
            "message": "case_8_observe_and_pairs",
            "room": room_key,
            "boss_memory_text": boss_memory,
            "f13_interactions": f13_texts,
            "gossip": {"triggered": False, "blocked_by_boss": True},
            "scout_text": scout_text,
        }

    async def _handle_case_9(self, room_ctx: dict) -> dict:
        return {"ok": True, "message": "case_9_frontstage", "room": room_ctx.get("room", "")}

    async def _handle_case_10(self, room_ctx: dict) -> dict:
        return {"ok": True, "message": "case_10_frontstage", "room": room_ctx.get("room", "")}

    async def _handle_case_11(self, room_ctx: dict) -> dict:
        room_key = str(room_ctx.get("room", "")).strip()
        room_npc_ids = [str(x).strip() for x in room_ctx.get("npc_ids", []) if str(x).strip()]
        rows = self._collect_room_npc_task_snapshot(room_key)
        pairs = self._pair_npcs_for_same_task(rows)
        used_ids: set[str] = set()
        f13_texts: list[str] = []
        for a, b in pairs:
            a_id = str(a.get("id", "")).strip()
            b_id = str(b.get("id", "")).strip()
            if not a_id or not b_id:
                continue
            used_ids.update({a_id, b_id})
            pair_info = self._resolve_npc_npc_template_interaction(
                npc_a_id=a_id,
                npc_b_id=b_id,
                task_name=str(a.get("task_name", "")).strip() or str(b.get("task_name", "")).strip(),
            )
            text = str(pair_info.get("memory_text", "")).strip()
            if text:
                f13_texts.append(text)

        gossip_result = self._resolve_room_gossip(
            room_npc_ids=room_npc_ids,
            room_key=room_key,
            allow_gossip=True,
        )

        if f13_texts:
            scout_text = random.choice(f13_texts)
        elif gossip_result.get("triggered"):
            scout_text = str(gossip_result.get("scout_text", "")).strip()
        else:
            scout_text = DataLoader().get_room_idle(room_key)
        return {
            "ok": True,
            "message": "case_11_pairs_and_gossip",
            "room": room_key,
            "paired_npc_ids": sorted(list(used_ids)),
            "f13_interactions": f13_texts,
            "gossip": gossip_result,
            "scout_text": scout_text,
        }

    async def _handle_case_12(self, room_ctx: dict) -> dict:
        room_key = str(room_ctx.get("room", "")).strip()
        if (
            room_key == "boss_office"
            and not bool(getattr(self.state.daily, "pua_triggered", False))
            and str(getattr(self.state.boss, "current_behavior", "")).strip().lower() == str(BossBehavior.PUA).strip().lower()
        ):
            candidates = [
                npc_id for npc_id, npc in self.state.npcs.items()
                if npc.alive and int(self._boss_suspicion_to(npc_id)) >= 50
            ]
            candidates.sort(key=lambda nid: (-int(self._boss_suspicion_to(nid)), nid))
            if candidates:
                target_id = candidates[0]
                self.state.npcs[target_id].current_room = Room.BOSS_OFFICE
                summon_payload = await self._handle_case_5(
                    {
                        "room": "boss_office",
                        "player_present": False,
                        "boss_present": True,
                        "npc_ids": [target_id],
                        "npc_task_ids": {"%s" % target_id: "any"},
                    }
                )
                summon_payload["message"] = "case_12_summon_case5"
                return summon_payload
        return {
            "ok": True,
            "message": "case_12_idle",
            "room": room_key,
            "scout_text": DataLoader().get_room_idle("boss_office"),
        }

    def _resolve_room_gossip(self, room_npc_ids: list[str], room_key: str, allow_gossip: bool) -> dict:
        if not allow_gossip:
            return {"triggered": False, "blocked_by_boss": True}
        ids = [str(x).strip() for x in room_npc_ids if str(x).strip()]
        if len(ids) <= 1 or not self.memory:
            return {"triggered": False}
        dl = DataLoader()
        speaker_candidates: list[dict] = []
        room_npc_set = set(ids)
        for speaker_id in ids:
            observer_memories = self.memory.memories.get(speaker_id, {}) if self.memory else {}
            candidate_memories: list[tuple[str, str]] = []
            for target_id, day_map in observer_memories.items():
                target = str(target_id).strip()
                if not target or target in {speaker_id, "player"}:
                    continue
                if target in room_npc_set:
                    continue
                target_npc = self.state.npcs.get(target)
                if target_npc is None or not getattr(target_npc, "alive", False):
                    continue
                if not isinstance(day_map, dict):
                    continue
                for texts in day_map.values():
                    if not isinstance(texts, list):
                        continue
                    for entry in texts:
                        memory_line, is_sealed = MemorySystem.unpack_memory_entry(entry)
                        if is_sealed:
                            continue
                        if memory_line:
                            candidate_memories.append((target, memory_line))
            if not candidate_memories:
                continue
            try:
                gossip_chance = float(dl.get_npc_field(speaker_id, "gossip_chance", 0.0))
            except (TypeError, ValueError):
                gossip_chance = 0.0
            gossip_chance = max(0.0, min(1.0, gossip_chance))
            gossip_style = str(dl.get_npc_field(speaker_id, "gossip_style", "")).strip() or "{memory}"
            speaker_candidates.append(
                {
                    "speaker_id": speaker_id,
                    "gossip_chance": gossip_chance,
                    "gossip_style": gossip_style,
                    "candidate_memories": candidate_memories,
                }
            )
        if not speaker_candidates:
            return {"triggered": False}
        speaker_candidates.sort(key=lambda row: (-float(row.get("gossip_chance", 0.0)), str(row.get("speaker_id", ""))))
        chosen = None
        for row in speaker_candidates:
            if random.random() <= float(row.get("gossip_chance", 0.0)):
                chosen = row
                break
        if not chosen:
            return {"triggered": False}
        speaker_id = str(chosen.get("speaker_id", "")).strip()
        candidate_memories = list(chosen.get("candidate_memories", []) or [])
        if not speaker_id or not candidate_memories:
            return {"triggered": False}
        owner_id, memory_text = random.choice(candidate_memories)
        owner_id = str(owner_id).strip()
        listeners = [x for x in ids if x not in {speaker_id, owner_id}]
        if not owner_id or not listeners:
            return {"triggered": False}
        clean_memory = str(memory_text or "").rstrip("。.！!？?，,；;：: \t\r\n").strip()
        gossip_content = str(chosen.get("gossip_style", "{memory}")).strip().replace("{memory}", clean_memory)
        speaker_name = self._npc_display_name(speaker_id, speaker_id)
        owner_name = self._npc_display_name(owner_id, owner_id)
        for listener_id in listeners:
            told_about_text = dl.get_npc_gossip_text(
                "listener_about_speaker",
                default="我听{speaker_name}凑过来嘀咕了一段{owner_name}的旧账，看来{speaker_name}对{owner_name}有意见。",
                speaker_name=speaker_name,
                owner_name=owner_name,
                gossip_content=gossip_content,
                memory=memory_text,
            )
            repeated_text = dl.get_npc_gossip_text(
                "listener_about_owner",
                default="我从{speaker_name}嘴里听到{owner_name}最近不太对劲——这事我先记一笔。",
                speaker_name=speaker_name,
                owner_name=owner_name,
                gossip_content=gossip_content,
                memory=memory_text,
            )
            self.memory.add_impression(
                observer_id=listener_id,
                target_id=speaker_id,
                day=self.state.current_day,
                impression_text=told_about_text,
            )
            self._log_witness_event(
                source="gossip_listener_to_speaker",
                observer_id=listener_id,
                target_id=speaker_id,
                room_key=room_key,
                text=told_about_text,
                extra={"speaker_id": speaker_id, "owner_id": owner_id},
            )
            self.memory.add_impression(
                observer_id=listener_id,
                target_id=owner_id,
                day=self.state.current_day,
                impression_text=repeated_text,
            )
            self._log_witness_event(
                source="gossip_listener_to_owner",
                observer_id=listener_id,
                target_id=owner_id,
                room_key=room_key,
                text=repeated_text,
                extra={"speaker_id": speaker_id, "owner_id": owner_id},
            )
            sus_delta = random.randint(3, 5)
            rels = self.state.relationships.get(listener_id, {})
            if owner_id in rels:
                self.manager.modify_suspicion(listener_id, owner_id, sus_delta)
                self.manager.append_relationship_reason(listener_id, owner_id, repeated_text)
        scout_text = dl.get_npc_gossip_text(
            "scout_observation",
            default="你的小助理看到{speaker_name}凑在同事耳边嘀嘀咕咕，其他人表情明显紧张了几分。",
            speaker_name=speaker_name,
            owner_name=owner_name,
            gossip_content=gossip_content,
            memory=memory_text,
        )
        self._work_logger.info("[NPC_GOSSIP_BG] speaker=%s owner=%s listeners=%s", speaker_id, owner_id, listeners)
        return {
            "triggered": True,
            "speaker_id": speaker_id,
            "owner_id": owner_id,
            "listeners": listeners,
            "scout_text": scout_text,
        }

    def _collect_room_npc_task_snapshot(self, room_key: str | None = None) -> list[dict]:
        if room_key:
            try:
                room = Room(str(room_key))
            except ValueError:
                room = self.state.player.current_room
        else:
            room = self.state.player.current_room
        rows: list[dict] = []
        for npc_id, npc in self.state.npcs.items():
            if not npc.alive or npc.current_room != room:
                continue
            current_task = self._current_task_for_npc(npc_id)
            task_id = str(getattr(current_task, "id", "")).strip()
            task_name = str(getattr(current_task, "name", "")).strip()
            rows.append(
                {
                    "id": npc_id,
                    "name": npc.name,
                    "task_id": task_id,
                    "task_name": task_name,
                }
            )
        return rows

    @staticmethod
    def _pair_npcs_for_same_task(
        npc_rows: list[dict],
        excluded_ids: set[str] | None = None,
    ) -> list[tuple[dict, dict]]:
        excluded = set(excluded_ids or set())
        used: set[str] = set()
        pairs: list[tuple[dict, dict]] = []
        for i in range(len(npc_rows)):
            a = npc_rows[i]
            a_id = str(a.get("id", "")).strip()
            a_task = str(a.get("task_id", "")).strip()
            if not a_id or not a_task or a_id in used or a_id in excluded:
                continue
            for j in range(i + 1, len(npc_rows)):
                b = npc_rows[j]
                b_id = str(b.get("id", "")).strip()
                b_task = str(b.get("task_id", "")).strip()
                if not b_id or b_id in used or b_id in excluded:
                    continue
                if a_task != b_task:
                    continue
                used.add(a_id)
                used.add(b_id)
                pairs.append((a, b))
                break
        return pairs

    def _resolve_npc_npc_template_interaction(
        self,
        npc_a_id: str,
        npc_b_id: str,
        task_name: str,
        tone: str | None = None,
    ) -> dict:
        row = DataLoader().get_npc_npc_interaction_template(tone=tone)
        if not row:
            return {}
        npc_a_name = self._npc_display_name(npc_a_id, npc_a_id)
        npc_b_name = self._npc_display_name(npc_b_id, npc_b_id)
        task_text = str(task_name).strip() or "当前工作"
        template = str(row.get("template", "")).strip()
        if not template:
            return {}
        template_active = str(row.get("template_active", "")).strip() or template
        template_passive = str(row.get("template_passive", "")).strip() or template_active
        try:
            memory_text = template.format(a=npc_a_name, b=npc_b_name, task=task_text)
        except Exception:
            memory_text = template
        try:
            memory_text_a = template_active.format(other=npc_b_name, task=task_text)
        except Exception:
            memory_text_a = memory_text
        try:
            memory_text_b = template_passive.format(other=npc_a_name, task=task_text)
        except Exception:
            memory_text_b = memory_text
        affinity_delta = int(row.get("affinity_delta", 0))
        suspicion_delta = int(row.get("suspicion_delta", 0))
        if self.memory:
            self.memory.add_impression(
                observer_id=npc_a_id,
                target_id=npc_b_id,
                day=self.state.current_day,
                impression_text=memory_text_a,
            )
            self._log_witness_event(
                source="f13_pairing",
                observer_id=npc_a_id,
                target_id=npc_b_id,
                room_key="",
                text=memory_text_a,
                extra={"affinity_delta": affinity_delta, "suspicion_delta": suspicion_delta},
            )
            self.memory.add_impression(
                observer_id=npc_b_id,
                target_id=npc_a_id,
                day=self.state.current_day,
                impression_text=memory_text_b,
            )
            self._log_witness_event(
                source="f13_pairing",
                observer_id=npc_b_id,
                target_id=npc_a_id,
                room_key="",
                text=memory_text_b,
                extra={"affinity_delta": affinity_delta, "suspicion_delta": suspicion_delta},
            )
        for from_id, to_id in ((npc_a_id, npc_b_id), (npc_b_id, npc_a_id)):
            rels = self.state.relationships.get(from_id, {})
            if to_id not in rels:
                continue
            if affinity_delta:
                self.manager.modify_affinity(from_id, to_id, affinity_delta)
            if suspicion_delta:
                self.manager.modify_suspicion(from_id, to_id, suspicion_delta)
            if affinity_delta or suspicion_delta:
                self.manager.append_relationship_reason(from_id, to_id, memory_text)
        self._work_logger.info(
            "[NPC_NPC_TEMPLATE] %s<->%s task=%s tone=%s aff=%s sus=%s text=%s",
            npc_a_id,
            npc_b_id,
            task_text,
            str(row.get("tone", "")),
            affinity_delta,
            suspicion_delta,
            memory_text,
        )
        return {
            "tone": str(row.get("tone", "")).strip().lower(),
            "memory_text": memory_text,
            "affinity_delta": affinity_delta,
            "suspicion_delta": suspicion_delta,
        }

    def _resolve_hour_bystander_and_npc_pairs(self) -> str:
        context = dict(self._hour_settlement_context or {})
        self._hour_settlement_context = {}
        if not context:
            return ""
        player = self.state.player
        task_index = int(player.current_task_index)
        if task_index < 0 or task_index >= len(player.selected_tasks):
            return ""
        player_task = player.selected_tasks[task_index]
        player_task_name = str(getattr(player_task, "name", "")).strip() or "当前工作"
        room_name = EvidenceConverter.ROOM_NAMES.get(player.current_room, "未知")
        room_npcs = self._collect_room_npc_task_snapshot()

        participant_ids = {
            str(x).strip() for x in context.get("participant_npc_ids", []) if str(x).strip()
        }
        is_blackmail = bool(context.get("is_blackmail", False))
        if is_blackmail:
            self._work_logger.info(
                "[NPC_NPC_TEMPLATE] skip pairing due to blackmail room=%s listeners=%s",
                room_name,
                context.get("blackmail_listener_ids", []),
            )
            return ""

        pair_candidates = [row for row in room_npcs if str(row.get("id", "")).strip() not in participant_ids]
        pairs = self._pair_npcs_for_same_task(pair_candidates)
        interaction_events: list[dict] = []
        if participant_ids:
            primary_npc_id = next(iter(participant_ids), "")
            if primary_npc_id:
                interaction_events.append(
                    {
                        "kind": "player_duo",
                        "participants": ["player", primary_npc_id],
                        "task_name": player_task_name,
                        "npc_name": self._npc_display_name(primary_npc_id, primary_npc_id),
                    }
                )
        for a, b in pairs:
            a_id = str(a.get("id", ""))
            b_id = str(b.get("id", ""))
            pair_task_name = str(a.get("task_name", "")) or str(b.get("task_name", ""))
            pair_info = self._resolve_npc_npc_template_interaction(
                npc_a_id=a_id,
                npc_b_id=b_id,
                task_name=pair_task_name,
            )
            interaction_events.append(
                {
                    "kind": "npc_pair",
                    "participants": [a_id, b_id],
                    "task_name": pair_task_name,
                    "npc_a_name": self._npc_display_name(a_id, a_id),
                    "npc_b_name": self._npc_display_name(b_id, b_id),
                    "tone": str(pair_info.get("tone", "")).strip().lower(),
                }
            )

        if not self.memory:
            return ""
        player_name = str(player.name).strip() or "调查员"
        dl = DataLoader()
        room_npc_ids = [
            str(row.get("id", "")).strip()
            for row in room_npcs
            if str(row.get("id", "")).strip()
        ]
        observer_ids = list(room_npc_ids)
        if self.state.boss.current_room == self.state.player.current_room:
            observer_ids.append("boss")
        for event in interaction_events:
            participants = [
                str(x).strip()
                for x in (event.get("participants", []) or [])
                if str(x).strip()
            ]
            if len(participants) < 2:
                continue
            participant_set = set(participants)
            for observer_id in observer_ids:
                if observer_id in participant_set:
                    continue
                witness_reaction = dl.get_npc_witness_reaction(observer_id)
                if not witness_reaction:
                    witness_reaction = "我默默记在心里，准备再观察。"

                task_text = str(event.get("task_name", "")).strip() or "当前工作"
                kind = str(event.get("kind", "")).strip()
                if kind == "player_duo":
                    npc_name = str(event.get("npc_name", "")).strip() or "同事"
                    memory_text = f"我在{room_name}看到{player_name}和{npc_name}在{task_text}，{witness_reaction}"
                else:
                    npc_a_name = str(event.get("npc_a_name", "")).strip() or "同事A"
                    npc_b_name = str(event.get("npc_b_name", "")).strip() or "同事B"
                    memory_text = f"我在{room_name}看到{npc_a_name}和{npc_b_name}在一起{task_text}，{witness_reaction}"

                for target_id in participants:
                    if target_id == observer_id:
                        continue
                    self.memory.add_impression(
                        observer_id=observer_id,
                        target_id=target_id,
                        day=self.state.current_day,
                        impression_text=memory_text,
                    )
                    self._log_witness_event(
                        source="hour_settlement_bystander",
                        observer_id=observer_id,
                        target_id=target_id,
                        room_key=self.state.player.current_room.value,
                        text=memory_text,
                        extra={"kind": kind},
                    )
            if "boss" in observer_ids and str(event.get("kind", "")) == "npc_pair":
                tone = str(event.get("tone", "")).strip().lower()
                if tone in {"negative", "chaotic"}:
                    for target_id in participants:
                        rels = self.state.relationships.get("boss", {})
                        if target_id in rels:
                            self.manager.modify_suspicion("boss", target_id, 3)
        if len(room_npc_ids) <= 1:
            return ""

        speaker_candidates: list[dict] = []
        room_npc_set = set(room_npc_ids)
        for speaker_id in room_npc_ids:
            observer_memories = self.memory.memories.get(speaker_id, {}) if self.memory else {}
            candidate_memories: list[tuple[str, str]] = []
            for target_id, day_map in observer_memories.items():
                target = str(target_id).strip()
                if not target or target == speaker_id or target == "player":
                    continue
                if target in room_npc_set:
                    continue
                target_npc = self.state.npcs.get(target)
                if target_npc is None or not getattr(target_npc, "alive", False):
                    continue
                if not isinstance(day_map, dict):
                    continue
                for texts in day_map.values():
                    if not isinstance(texts, list):
                        continue
                    for entry in texts:
                        memory_line, is_sealed = MemorySystem.unpack_memory_entry(entry)
                        if is_sealed:
                            continue
                        if memory_line:
                            candidate_memories.append((target, memory_line))
            if not candidate_memories:
                continue
            chance_raw = dl.get_npc_field(speaker_id, "gossip_chance", 0.0)
            try:
                gossip_chance = float(chance_raw)
            except (TypeError, ValueError):
                gossip_chance = 0.0
            gossip_chance = max(0.0, min(1.0, gossip_chance))
            gossip_style = str(dl.get_npc_field(speaker_id, "gossip_style", "")).strip()
            if not gossip_style:
                gossip_style = "{memory}"
            speaker_candidates.append(
                {
                    "speaker_id": speaker_id,
                    "gossip_chance": gossip_chance,
                    "gossip_style": gossip_style,
                    "candidate_memories": candidate_memories,
                }
            )
        if not speaker_candidates:
            return ""

        speaker_candidates.sort(
            key=lambda row: (
                -float(row.get("gossip_chance", 0.0)),
                str(row.get("speaker_id", "")),
            )
        )
        chosen: dict | None = None
        for row in speaker_candidates:
            if random.random() <= float(row.get("gossip_chance", 0.0)):
                chosen = row
                break
        if not chosen:
            return ""

        speaker_id = str(chosen.get("speaker_id", "")).strip()
        candidate_memories = list(chosen.get("candidate_memories", []) or [])
        if not speaker_id or not candidate_memories:
            return ""
        owner_id, memory_text = random.choice(candidate_memories)
        owner_id = str(owner_id).strip()
        if not owner_id:
            return ""
        listeners = [x for x in room_npc_ids if x not in {speaker_id, owner_id}]
        if not listeners:
            return ""

        gossip_style = str(chosen.get("gossip_style", "{memory}")).strip() or "{memory}"
        clean_memory = str(memory_text or "").rstrip("。.！!？?，,；;：: \t\r\n").strip()
        gossip_content = gossip_style.replace("{memory}", clean_memory)
        speaker_name = self._npc_display_name(speaker_id, speaker_id)
        owner_name = self._npc_display_name(owner_id, owner_id)
        for listener_id in listeners:
            told_about_text = dl.get_npc_gossip_text(
                "listener_about_speaker",
                default="我听{speaker_name}凑过来嘀咕了一段{owner_name}的旧账，看来{speaker_name}对{owner_name}有意见。",
                speaker_name=speaker_name,
                owner_name=owner_name,
                gossip_content=gossip_content,
                memory=memory_text,
            )
            repeated_text = dl.get_npc_gossip_text(
                "listener_about_owner",
                default="我从{speaker_name}嘴里听到{owner_name}最近不太对劲——这事我先记一笔。",
                speaker_name=speaker_name,
                owner_name=owner_name,
                gossip_content=gossip_content,
                memory=memory_text,
            )
            self.memory.add_impression(
                observer_id=listener_id,
                target_id=speaker_id,
                day=self.state.current_day,
                impression_text=told_about_text,
            )
            self.memory.add_impression(
                observer_id=listener_id,
                target_id=owner_id,
                day=self.state.current_day,
                impression_text=repeated_text,
            )
            sus_delta = random.randint(3, 5)
            rels = self.state.relationships.get(listener_id, {})
            if owner_id in rels:
                self.manager.modify_suspicion(listener_id, owner_id, sus_delta)
                self.manager.append_relationship_reason(listener_id, owner_id, repeated_text)
        self._work_logger.info(
            "[NPC_GOSSIP] speaker=%s owner=%s listeners=%s chance=%.2f",
            speaker_id,
            owner_id,
            listeners,
            float(chosen.get("gossip_chance", 0.0)),
        )
        return dl.get_npc_gossip_text(
            "player_notice",
            default="你注意到{speaker_name}正凑在其他人耳边嘀嘀咕咕……",
            speaker_name=speaker_name,
            owner_name=owner_name,
            gossip_content=gossip_content,
            memory=memory_text,
        )

    def _finalize_hour_settlement_for_result(self, result: dict) -> None:
        if self._hour_bystander_resolved:
            return
        self._hour_bystander_resolved = True
        notice_text = str(self._resolve_hour_bystander_and_npc_pairs() or "").strip()
        warning_text = ""
        boss_to_player = self.state.relationships.get("boss", {}).get("player")
        boss_suspicion = int(getattr(boss_to_player, "suspicion", 0) or 0) if boss_to_player else 0
        if boss_suspicion >= 60 and not bool(getattr(self.state.daily, "boss_player_warning_shown", False)):
            warning_text = "⚠️ 你注意到经理最近一直在盯着你看，那八只眼睛里写满了审视。你感觉到了一股不安……"
            self.state.daily.boss_player_warning_shown = True

        append_parts = [x for x in [notice_text, warning_text] if str(x).strip()]
        if append_parts:
            result["settlement_append_text"] = "\n".join(append_parts)

    def new_game(self) -> dict:
        if self._pending_act1 and not self._pending_act1.done():
            self._pending_act1.cancel()
        if self._pending_night_alliance and not self._pending_night_alliance.done():
            self._pending_night_alliance.cancel()
        self._pending_act1 = None
        self._pending_night_alliance = None
        self._active_night_visitor_id = ""
        self._alliances_to_enforce = []
        self._pending_scout_result = None
        if self._pending_scout_task and not self._pending_scout_task.done():
            self._pending_scout_task.cancel()
        self._pending_scout_task = None
        self._pending_work_mode_choice = None
        self._current_skeleton_event = None
        self._current_event_card_mode = "combo"
        self._current_event_context = {}
        self._last_record_card_context = {}
        self._last_scout_record_context = {}
        self._hour_settlement_context = {}
        self._hour_bystander_resolved = False
        self._pending_pua_interruption = None
        self._pending_npc_pua_notification = ""
        self._last_pua_snapshot = {}
        self._last_pua_target_id = ""
        self._last_pua_day = 0
        self._pua_same_target_streak = 0
        self._hour_room_case_cache = {}
        self._active_front_case_id = 0
        self._active_front_case_ctx = {}
        self._active_contracts = []
        self._npc_ledger = {}
        self._last_player_event_route = ""
        self._forced_duo_trigger_count = 0
        self.state = GameState.new_game()
        self.manager = StateManager(self.state)
        self.memory = MemorySystem()
        self._ensure_npc_wallets()
        self._ensure_npc_ledger()
        return self._build_phase_response("游戏开始！欢迎来到救世主集团。")

    def start_task_selection(self) -> dict:
        """
        开始任务选择阶段。生成当日任务池，等待玩家选择。

        返回:
            当日任务池数据（供前端渲染任务选择界面）
        """
        self.state.current_phase = GamePhase.TASK_SELECTION
        self.manager.setup_daily_tasks()
        self._agent_results = None
        # 注意：经理 PUA 规划改为在 submit_task_selection 中同步 await，
        # 确保玩家第1小时事件触发前，boss_pua_target_id / boss_pua_hour 已就绪。

        task_pool = self.manager.get_task_pool_for_frontend()

        # NPC任务在玩家提交后由规则引擎分配；经理Agent同样在提交后触发。

        return {
            "phase": "task_selection",
            "day": self.state.current_day,
            "message": f"第{self.state.current_day}天开始了。今天有{len(task_pool)}个任务可选，你有{DAILY_ACTION_POINTS}小时行动力。",
            "task_pool": task_pool,
            "action_points": self.state.player.action_points,
            "gold": self.state.player.gold,
            "battery": self.state.player.battery,
            "player_blank_cards": sum(1 for rc in self.state.player.record_cards if rc.status.value == "blank"),
            "valid_evidence_count": self._valid_evidence_count(),
            "recorded_cards_count": self._recorded_cards_count(),
            "opening": self._build_opening(),
        }

    async def trigger_agent_decisions(self, task_pool) -> None:
        """
        兼容旧调用：任务选择阶段不再触发NPC/经理Agent预决策。
        经理决策会在玩家与NPC任务都确定后触发。
        """
        self._agent_results = None

    async def submit_task_selection(self, task_ids: list[str]) -> dict:
        """
        玩家提交任务选择，进入工作执行阶段。

        参数:
            task_ids: 玩家选择的任务ID列表（按执行顺序）

        返回:
            工作阶段初始状态，或错误信息
        """
        success, msg = self.manager.player_select_tasks(task_ids)
        if not success:
            return {"error": msg}

        # NPC改为规则引擎选任务：从当日12个候选任务中，按偏好权重 + 随机分配5个。
        self._assign_npc_tasks_by_rule_engine(max_tasks=5)

        # 经理 PUA 决策必须在玩家第1小时事件触发之前完成，避免异步竞态漏触发。
        await self._invoke_boss_pua_planning()

        # 经理AI请求改为在玩家/NPC任务都确定后触发，确保prompt含完整员工排班。
        self._agent_results = None
        if self.memory:
            employee_schedule = self._build_employee_schedule_for_boss(total_hours=5)
            try:
                self._agent_results = await AgentService.all_agents_select_tasks(
                    npcs=self.state.npcs,
                    boss=self.state.boss,
                    day=self.state.current_day,
                    task_list=self.state.daily.task_pool,
                    player_tasks_summary=employee_schedule,
                    relationships=self.state.relationships,
                    memory=self.memory,
                    player_name=self.state.player.name,
                    max_tasks=5,
                )
            except Exception:
                self._agent_results = None

        if self._agent_results:
            self._apply_agent_selections()

        self.state.current_phase = GamePhase.WORKING
        self.state.current_hour = 0

        positions = self.manager.get_all_positions()

        return {
            "phase": "working",
            "day": self.state.current_day,
            "hour": 0,
            "total_hours": sum(t.duration for t in self.state.player.selected_tasks),
            "message": f"任务确认！你今天要做{len(task_ids)}个任务。出发吧！",
            "player_gold": self.state.player.gold,
            "gold": self.state.player.gold,
            "player_battery": self.state.player.battery,
            "battery": self.state.player.battery,
            "positions": positions,
            "player_room": self.state.player.current_room.value,
            "coworkers": self.manager.get_player_coworkers(),
            "social_energy_left": self.state.daily.social_energy_left,
            "player_blank_cards": sum(1 for rc in self.state.player.record_cards if rc.status.value == "blank"),
            "valid_evidence_count": self._valid_evidence_count(),
            "recorded_cards_count": self._recorded_cards_count(),
        }

    def _select_weighted_tasks_from_pool(self, npc, task_pool, max_tasks: int = 5):
        candidates = [copy.deepcopy(t) for t in task_pool]
        selected = []
        room_counts: dict[str, int] = {}
        while candidates and len(selected) < max_tasks:
            weights = []
            for t in candidates:
                room_key = getattr(t.room, "value", str(t.room))
                base = float(getattr(npc, "task_preferences", {}).get(room_key, 0.1) or 0.1)
                if base <= 0:
                    base = 0.01
                # 给重复房间施加衰减，避免NPC日程过于极端集中。
                repeat_penalty = 0.65 ** room_counts.get(room_key, 0)
                weights.append(max(base * repeat_penalty, 0.001))
            pick_idx = random.choices(range(len(candidates)), weights=weights, k=1)[0]
            picked = candidates.pop(pick_idx)
            selected.append(picked)
            room_key = getattr(picked.room, "value", str(picked.room))
            room_counts[room_key] = room_counts.get(room_key, 0) + 1
        return selected[:max_tasks]

    def _assign_npc_tasks_by_rule_engine(self, max_tasks: int = 5) -> None:
        from .task_system import TaskSystem

        task_pool = list(getattr(self.state.daily, "task_pool", []) or [])
        if not task_pool:
            for _, npc in self.state.npcs.items():
                if not npc.alive:
                    continue
                npc.selected_tasks = TaskSystem.assign_npc_tasks(npc)
                npc.current_task_index = 0
                if npc.selected_tasks:
                    npc.current_room = npc.selected_tasks[0].room
            return

        for npc_id, npc in self.state.npcs.items():
            if not npc.alive:
                continue
            selected_tasks = self._select_weighted_tasks_from_pool(npc, task_pool, max_tasks=max_tasks)
            if not selected_tasks:
                selected_tasks = TaskSystem.assign_npc_tasks(npc)
            npc.selected_tasks = selected_tasks[:max_tasks]
            npc.current_task_index = 0
            if npc.selected_tasks:
                npc.current_room = npc.selected_tasks[0].room
            self._work_logger.info(
                "[NPC_RULE_TASKS] npc=%s tasks=%s",
                npc_id,
                [getattr(t, "id", "") for t in npc.selected_tasks],
            )

    def _build_employee_schedule_for_boss(self, total_hours: int = 5) -> str:
        def _fmt_row(tasks: list) -> str:
            cells = []
            for i in range(total_hours):
                if i < len(tasks):
                    task = tasks[i]
                    room_name = EvidenceConverter.ROOM_NAMES.get(task.room, str(getattr(task.room, "value", "未知")))
                    cells.append(f"H{i + 1}:{task.name}@{room_name}")
                else:
                    cells.append(f"H{i + 1}:空闲")
            return "；".join(cells)

        rows = [f"玩家：{_fmt_row(self.state.player.selected_tasks)}"]
        for _, npc in self.state.npcs.items():
            if not npc.alive:
                continue
            rows.append(f"{npc.name}：{_fmt_row(list(getattr(npc, 'selected_tasks', []) or []))}")
        return "\n".join(rows)

    async def start_movement_phase(self, task_index: int) -> dict:
        """
        开始移动阶段：计算移动 + 预请求Act 1。
        返回移动数据给前端播动画，同时后台开始请求AI。
        """
        if not self.state or not self.manager:
            return {"error": "游戏尚未初始化"}
        if self.state.current_phase != GamePhase.WORKING:
            return {"error": "当前不在工作阶段"}

        player = self.state.player
        if task_index < 0 or task_index >= len(player.selected_tasks):
            return {"error": "没有更多任务了"}

        if self._pending_act1 and not self._pending_act1.done():
            return {"error": "已有待处理事件，请先调用 movement_done"}

        # 新小时开始，允许本小时的旁观/NPC配对结算执行一次。
        self._hour_bystander_resolved = False

        target_task = player.selected_tasks[task_index]
        target_room = target_task.room.value
        ai_target = str(getattr(self.state.daily, "boss_pua_target_id", "") or "").strip()
        ai_hour = int(getattr(self.state.daily, "boss_pua_hour", -1))
        is_player_pua_incoming = (
            ai_target == "player"
            and ai_hour == int(task_index)
            and not bool(getattr(self.state.daily, "boss_pua_executed", False))
        )
        movement_target_room_key = "boss_office" if is_player_pua_incoming else target_room
        current_room = player.current_room.value if player.current_room else "office"

        boss_patrol = getattr(self.state.boss, "patrol_rooms", [])
        boss_current_room = self.state.boss.current_room.value if self.state.boss.current_room else "boss_office"

        move_data = MovementSystem.calculate_movement_phase(
            current_room,
            movement_target_room_key,
            self.state.npcs,
            boss_patrol,
            task_index,
            boss_current_room=boss_current_room,
        )

        # 更新角色位置到目标状态（移动动画表现由前端负责）
        player.current_room = Room.BOSS_OFFICE if is_player_pua_incoming else target_task.room
        player.current_task_index = task_index
        self.state.current_hour = task_index

        for _, npc in self.state.npcs.items():
            if npc.alive and task_index < len(npc.selected_tasks):
                npc.current_room = npc.selected_tasks[task_index].room
                npc.current_task_index = task_index

        if boss_patrol and task_index < len(boss_patrol):
            target = boss_patrol[task_index]
            if isinstance(target, str):
                self.state.boss.current_room = Room(target)
            else:
                self.state.boss.current_room = target

        self._pending_act1 = asyncio.create_task(
            self._dispatch_current_hour_rooms(generate_player_event=True)
        )

        move_data["target_room"] = "经理办公室" if is_player_pua_incoming else target_room
        move_data["target_room_key"] = movement_target_room_key
        move_data["task_name"] = target_task.name
        move_data["task_index"] = task_index
        move_data["positions"] = self.manager.get_all_positions()
        move_data["is_player_pua_incoming"] = bool(is_player_pua_incoming)
        if is_player_pua_incoming:
            move_data["max_duration"] = 3.0
            incoming_text = DataLoader().get_fallback(
                "f14_pua_incoming_player",
                default="糟糕！你似乎被经理盯上了，他喊你去一趟办公室！",
            )
            move_data["player_pua_incoming_text"] = str(incoming_text).strip() or "糟糕！你似乎被经理盯上了，他喊你去一趟办公室！"
        return move_data

    async def get_act1_after_movement(self) -> dict:
        """
        移动动画播完后，获取Act 1结果。
        如果AI还没返回，等待；如果已返回，直接拿缓存。
        """
        if not self._pending_act1:
            return {"error": "没有待处理的事件"}

        try:
            event = await self._pending_act1
        finally:
            self._pending_act1 = None

        if event is None:
            return {"error": "无法生成事件"}
        event["positions"] = self.manager.get_all_positions()
        if self._pending_npc_pua_notification:
            event["npc_pua_notification"] = str(self._pending_npc_pua_notification)
            self._pending_npc_pua_notification = ""
        # 首小时的NPC被经理叫走提示暂不弹窗，避免把上一小时状态残留到下一轮。
        self._pending_pua_interruption = None
        return event

    def _is_character_in_player_duo(self, char_id: str, task_index: int) -> bool:
        """判断目标当前小时是否处于玩家双人事件候选（同房+同任务）。"""
        char_key = str(char_id).strip()
        if not char_key:
            return False
        player = self.state.player
        if task_index < 0 or task_index >= len(player.selected_tasks):
            return False
        player_task = player.selected_tasks[task_index]
        player_task_id = str(getattr(player_task, "id", "")).strip()
        if not player_task_id:
            return False

        if char_key == "player":
            for _, npc in self.state.npcs.items():
                if not npc.alive:
                    continue
                if npc.current_room != player.current_room:
                    continue
                idx = npc.current_task_index
                if idx < 0 or idx >= len(npc.selected_tasks):
                    continue
                if str(getattr(npc.selected_tasks[idx], "id", "")).strip() == player_task_id:
                    return True
            return False

        npc = self.state.npcs.get(char_key)
        if not npc or not npc.alive:
            return False
        if npc.current_room != player.current_room:
            return False
        idx = npc.current_task_index
        if idx < 0 or idx >= len(npc.selected_tasks):
            return False
        npc_task_id = str(getattr(npc.selected_tasks[idx], "id", "")).strip()
        return npc_task_id == player_task_id

    def _boss_suspicion_to(self, target_id: str) -> int:
        rel = self.state.relationships.get("boss", {}).get(target_id)
        if not rel:
            return 0
        return int(getattr(rel, "suspicion", 0) or 0)

    def _apply_npc_pua_template_result(self, target_id: str, mode: str) -> None:
        """
        NPC被经理PUA时的模板结算（不调AI）：
        - NPC对经理好感 +5
        - NPC对经理怀疑度按性格调整（老实型下降，刺头型上升）
        """
        npc = self.state.npcs.get(target_id)
        if not npc or not npc.alive:
            return
        personality = self._npc_personality(target_id, "")
        lower = str(personality).lower()
        if any(k in lower for k in ["刺头", "叛逆", "冲动", "暴躁", "强硬"]):
            suspicion_delta = 5
            reason = "经理当众施压后，你对经理更警惕了。"
        elif any(k in lower for k in ["老实", "顺从", "谨慎", "温和", "保守", "讨好"]):
            suspicion_delta = -5
            reason = "经理施压后你选择服软，觉得先低头更安全。"
        else:
            suspicion_delta = -2
            reason = "经理施压让你短暂收敛，暂时不敢对抗。"

        self.manager.modify_affinity(target_id, "boss", 5)
        self.manager.modify_suspicion(target_id, "boss", suspicion_delta)
        self.manager.append_relationship_reason(target_id, "boss", reason)
        self._increase_fear(target_id, 10, "被经理PUA")
        if self.memory:
            mode_text = "被叫到办公室" if mode == "summon" else "被经理叫到一边"
            self.memory.add_impression(
                observer_id=target_id,
                target_id="boss",
                day=self.state.current_day,
                impression_text=f"你{mode_text}谈话，经理持续施压，让你重新掂量了自己的处境。",
            )

    def _check_pua_interruption(self, task_index: int) -> dict | None:
        """
        每小时实时判定经理PUA（废弃预排）：
        A. 同房偶遇：同房 + 怀疑>=40 + 今日未PUA + 目标不在玩家双人事件
        B. 召见PUA：经理在办公室 + 全员最高怀疑>=50 + 今日未PUA
        """
        if getattr(self.state.daily, "pua_triggered", False):
            return None

        boss_room = self.state.boss.current_room
        encounter_candidates: list[dict] = []
        if self.state.player.current_room == boss_room and not self._is_character_in_player_duo("player", task_index):
            sus = self._boss_suspicion_to("player")
            if sus >= 40:
                encounter_candidates.append({"target_id": "player", "suspicion": sus, "target_name": self.state.player.name})

        for npc_id, npc in self.state.npcs.items():
            if not npc.alive or npc.current_room != boss_room:
                continue
            if self._is_character_in_player_duo(npc_id, task_index):
                continue
            sus = self._boss_suspicion_to(npc_id)
            if sus >= 40:
                encounter_candidates.append({"target_id": npc_id, "suspicion": sus, "target_name": npc.name})

        chosen = None
        mode = "encounter"
        if encounter_candidates:
            encounter_candidates.sort(key=lambda x: (-int(x.get("suspicion", 0)), str(x.get("target_id", ""))))
            chosen = encounter_candidates[0]
        else:
            if self.state.boss.current_room == Room.BOSS_OFFICE:
                summon_candidates = [{"target_id": "player", "suspicion": self._boss_suspicion_to("player"), "target_name": self.state.player.name}]
                for npc_id, npc in self.state.npcs.items():
                    if npc.alive:
                        summon_candidates.append({"target_id": npc_id, "suspicion": self._boss_suspicion_to(npc_id), "target_name": npc.name})
                summon_candidates.sort(key=lambda x: (-int(x.get("suspicion", 0)), str(x.get("target_id", ""))))
                top = summon_candidates[0] if summon_candidates else None
                if top and int(top.get("suspicion", 0)) >= 50:
                    chosen = top
                    mode = "summon"

        if not chosen:
            return None

        target_id = str(chosen.get("target_id", "")).strip()
        target_name = str(chosen.get("target_name", target_id)).strip() or target_id
        is_player = target_id == "player"
        self.state.daily.pua_triggered = True
        self.state.daily.boss_pua_executed = True
        self.state.boss.current_behavior = BossBehavior.PUA
        self.state.boss.target_npc = target_id
        self._record_last_pua_target(target_id)

        if mode == "summon":
            self.state.boss.current_room = Room.BOSS_OFFICE
            if is_player:
                self.state.player.current_room = Room.BOSS_OFFICE
            else:
                npc = self.state.npcs.get(target_id)
                if npc and npc.alive:
                    npc.current_room = Room.BOSS_OFFICE
        else:
            self.state.boss.current_room = boss_room

        if is_player:
            message = "⚠️ 经理突然把你叫到一边，空气瞬间凝固了。"
        elif mode == "summon":
            message = f"⚠️ {target_name}被经理叫去了办公室。"
        else:
            message = f"⚠️ 经理把{target_name}叫到一边开始谈话。"

        if not is_player:
            self._apply_npc_pua_template_result(target_id, mode)

        return {
            "pua_active": True,
            "mode": mode,
            "target_id": target_id,
            "target_name": target_name,
            "target_is_player": is_player,
            "message": message,
        }

    async def _trigger_pua_event(self, pua_result: dict | None = None) -> dict:
        """触发经理PUA事件（玩家可出牌版本）。"""
        from .event_system import EventSystem

        dl = DataLoader()
        boss_display_name = self._npc_display_name("boss", "经理")
        boss_personality = self._npc_personality("boss", "威严、多疑")
        boss_identity = str(dl.get_npc_identity("boss") or "").strip() or "未知身份"
        pua_reason = str(getattr(self.state.daily, "boss_pua_decision_reason", "") or "").strip()
        if not pua_reason:
            pua_reason = "你需要确认对方是否在隐瞒真实身份。"
        fallback_scene = dl.pick_pua_segments("player") or {}
        fallback_opening = str((pua_result or {}).get("opening_text", "")).strip()
        if not fallback_opening:
            fallback_opening = str(fallback_scene.get("opening_text", "")).strip()
        if not fallback_opening:
            fallback_opening = str((pua_result or {}).get("full_text", "")).strip()
        if not fallback_opening:
            fallback_opening = str(fallback_scene.get("full_text", "")).strip()
        if not fallback_opening:
            fallback_opening = "鲍斯把你叫进经理办公室，八条触手在桌边缓慢收拢，像在给你的呼吸计时。"

        boss_info = {
            "id": "boss",
            "name": boss_display_name,
            "identity": boss_identity,
            "aim": MemorySystem.get_aim("boss"),
            "relationships": MemorySystem.build_relationship_text("boss", self.state.relationships, self.state.npcs),
            "memories": self.memory.get_memories("boss") if self.memory else [],
            "memory_and_relations": self.memory.build_memory_and_relations_text(
                "boss",
                self.state.relationships,
                self.state.npcs,
                player_name=self.state.player.name,
            ) if self.memory else "",
        }
        boss_memory_rel = str(boss_info.get("memory_and_relations", "") or "").strip()
        if not boss_memory_rel:
            boss_memory_rel = "（暂无可用记忆）"

        act1_result = await AIService.generate_pua_player_act1(
            boss_identity=boss_identity,
            pua_reason=pua_reason,
            boss_memory_relations=boss_memory_rel,
            player_name=self.state.player.name,
        )
        act1_text = str(act1_result.get("act1_text", "")).strip() or fallback_opening
        if not act1_result.get("success", True):
            act1_text = fallback_opening
        self._last_act1_text = act1_text
        self._last_event_description = act1_text
        self._last_npc_infos = [boss_info]

        self._current_skeleton_event = {
            "skeleton_id": "PUA_PLAYER_AI",
            "event_name": "经理灵魂拷问",
            "assembled_seed": act1_text,
            "room": "pua",
            "primary_npc": {"id": "boss", "name": boss_display_name, "personality": boss_personality},
            "evidence_type": None,
            "evidence_hint": "",
            "pua_reason": pua_reason,
        }
        self._current_event_card_mode = "combo"

        emotions, actions = EventSystem.draw_cards()
        self.state.player.hand_emotions = [c["id"] for c in emotions]
        self.state.player.hand_actions = [c["id"] for c in actions]

        return {
            "event_id": "PUA_PLAYER_AI",
            "event_name": "🐙 经理灵魂拷问",
            "description": act1_text,
            "prompt": "",
            "emotion_cards": emotions,
            "action_cards": actions,
            "has_evidence_hint": False,
            "evidence_hint": "",
            "is_pua": True,
        }

    def _fallback_pua_event(self) -> dict:
        """PUA事件降级。"""
        from .event_system import EventSystem

        emotions, actions = EventSystem.draw_cards()
        self.state.player.hand_emotions = [c["id"] for c in emotions]
        self.state.player.hand_actions = [c["id"] for c in actions]

        boss_display_name = self._npc_display_name("boss", "经理")
        boss_info = {
            "id": "boss",
            "name": boss_display_name,
            "identity": MemorySystem.get_identity("boss"),
            "aim": MemorySystem.get_aim("boss"),
            "relationships": MemorySystem.build_relationship_text("boss", self.state.relationships, self.state.npcs),
            "memories": self.memory.get_memories("boss") if self.memory else [],
            "memory_and_relations": self.memory.build_memory_and_relations_text(
                "boss",
                self.state.relationships,
                self.state.npcs,
                player_name=self.state.player.name,
            ) if self.memory else "",
        }
        self._last_npc_infos = [boss_info]
        self._current_skeleton_event = {
            "skeleton_id": "PUA_FALLBACK",
            "room": "pua",
            "primary_npc": {"id": "boss", "name": boss_display_name},
        }
        self._current_event_card_mode = "combo"
        pua_template = random.choice(PUA_EVENTS_CONFIG)
        fallback_text = pua_template.get("description", "")
        fallback_prompt = pua_template.get("prompt", "")
        fallback_name = pua_template.get("name", "经理的灵魂拷问")
        self._last_act1_text = fallback_text
        self._last_event_description = fallback_text
        self._last_event_prompt = fallback_prompt

        return {
            "event_id": pua_template.get("id", "PUA_FALLBACK"),
            "event_name": f"🐙 {fallback_name}",
            "description": fallback_text,
            "prompt": fallback_prompt,
            "emotion_cards": emotions,
            "action_cards": actions,
            "has_evidence_hint": False,
            "evidence_hint": "",
            "is_pua": True,
        }

    def _apply_agent_selections(self) -> None:
        """应用 NPC Agent 任务决策(经理 PUA/巡视由 _invoke_boss_pua_planning 接管,本方法不再处理 boss)。"""
        if not self._agent_results:
            return

        # ===== 经理 boss_plan 已由 _invoke_boss_pua_planning 接管,跳过老应用 =====
        # 老逻辑会写入 boss_hourly_plan = [PATROL]*5 和 boss.patrol_rooms,
        # 与新 _invoke_boss_pua_planning 冲突。直接跳过。
        # 老代码保留在下方但不再执行(boss_plan 字段为空,if patrol: 自动跳过)。
        boss_plan = self._agent_results.get("boss_plan", {})

        # 应用经理巡视计划
        patrol = boss_plan.get("patrol_rooms", [])
        if patrol:
            from .enums import BossBehavior, Room

            room_map = {
                "office": Room.OFFICE,
                "meeting": Room.MEETING,
                "warehouse": Room.WAREHOUSE,
                "pantry": Room.PANTRY,
                "reception": Room.RECEPTION,
                "boss_office": Room.BOSS_OFFICE,
            }
            self.state.daily.boss_hourly_plan = []
            for _room_str in patrol:
                self.state.daily.boss_hourly_plan.append(BossBehavior.PATROL)

            # 设置经理每小时的目标房间（供后续移动系统接入）
            self.state.boss.patrol_rooms = [
                room_map.get(r, Room.BOSS_OFFICE) for r in patrol
            ]

    def play_cards(self, emotion_id: str, action_id: str) -> dict:
        """
        玩家打出卡牌组合，结算当前事件。

        参数:
            emotion_id: 情绪卡ID
            action_id: 行动卡ID

        返回:
            事件结算结果 + 是否可以使用记录卡
        """
        if self.state.game_over:
            return {"error": "游戏已结束"}

        result = self.manager.resolve_player_cards(emotion_id, action_id)
        if "error" in result:
            return result
        self._current_event_card_mode = ""

        # 结算当前任务奖励（金币/关系等）
        current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
        task_reward_info = self._apply_task_reward(current_task)
        result.update(task_reward_info)
        self._last_record_card_context = {
            "subject_npc_id": "",
            "subject_npc_name": "",
            "summary_text": str(self._last_event_description or "")[:100],
            "is_evidence": bool(result.get("is_evidence_task", False)),
        }

        result["can_use_record_card"] = result.get("can_record", False) and any(
            rc.status.value == "blank" for rc in self.state.player.record_cards
        )
        result["blank_cards_count"] = sum(
            1 for rc in self.state.player.record_cards if rc.status.value == "blank"
        )
        # 嫁祸卡信息
        result["blame_cards_count"] = self.state.player.items.get("blame_card", 0)
        result["blame_used_today"] = self.state.daily.blame_card_used
        result["player_gold"] = self.state.player.gold
        result["gold"] = self.state.player.gold
        result["battery"] = self.state.player.battery
        result["valid_evidence_count"] = self._valid_evidence_count()
        result["recorded_cards_count"] = self._recorded_cards_count()
        # 已记录的记录卡列表（供"致命小黑历"功能使用）
        result["recorded_cards"] = self._serialize_recorded_cards()
        result["coworkers"] = self.manager.get_player_coworkers()
        result["scout_available_rooms"] = self._get_scout_available_rooms()

        event_context = dict(self._current_event_context or {})
        self._set_hour_settlement_context(
            is_blackmail=False,
            participant_npc_ids=[str(x) for x in event_context.get("participant_npc_ids", []) if str(x)],
        )
        self._current_event_context = {}

        # 附带小助理结果（如有）
        if self._pending_scout_result is not None:
            result["scout_result"] = self._pending_scout_result
            self._pending_scout_result = None
        else:
            result["scout_result"] = None

        self._finalize_hour_settlement_for_result(result)
        return result

    async def trigger_event_v2(self) -> dict | None:
        """
        新版事件触发：骨架拼装 + AI生成Act 1。

        返回:
            和旧版trigger_event兼容的event display dict，
            额外包含 skeleton_event 数据供后续Act 2使用。
            如果骨架不可用，fallback到旧版逻辑。
        """
        # ===== Batch 8: 经理 PUA 优先级最高 =====
        self._pending_pua_interruption = None
        if self._is_boss_pua_condition_met("player"):
            pua_result = await self._execute_boss_pua("player")
            if pua_result.get("success"):
                return await self._trigger_pua_event(pua_result)

        ai_target = str(getattr(self.state.daily, "boss_pua_target_id", "") or "").strip()
        ai_hour = int(getattr(self.state.daily, "boss_pua_hour", -1))
        current_hour = int(getattr(self.state, "current_hour", 0))
        if (
            ai_target and ai_target != "player"
            and ai_hour == current_hour
            and not bool(getattr(self.state.daily, "boss_pua_executed", False))
        ):
            pua_exec = await self._execute_boss_pua(ai_target)
            if pua_exec.get("success"):
                self._pending_pua_interruption = {
                    "pua_active": True,
                    "mode": "summon",
                    "target_id": ai_target,
                    "target_name": str(pua_exec.get("target_name", ai_target)),
                    "target_is_player": False,
                    "message": f"⚠️ {str(pua_exec.get('target_name', ai_target))}被经理叫去了办公室。",
                }

        # 尝试新版骨架拼装
        force_target = ""
        if self._should_force_interaction_after_solo():
            force_target = self._pick_non_boss_roommate_for_forced_duo()
        if force_target:
            player_task = self._current_task_for_player()
            npc_task = self._current_task_for_npc(force_target)
            player_task_id = str(getattr(player_task, "id", "")).strip()
            npc_task_id = str(getattr(npc_task, "id", "")).strip()
            skeleton_event = self.manager.trigger_skeleton_event(
                force_mode="duo_any_roommate",
                interaction_target_npc_id=force_target,
            )
            if skeleton_event:
                skeleton_event["debug_choice_source"] = "solo_chain_force_duo"
                self._forced_duo_trigger_count += 1
                self._work_logger.info(
                    "[FORCED_DUO] day=%s hour=%s count=%s target=%s route=%s player_task=%s npc_task=%s mode=duo_any_roommate reason=last_route_solo",
                    self.state.current_day,
                    self.state.current_hour,
                    self._forced_duo_trigger_count,
                    force_target,
                    str(skeleton_event.get("event_route", "")),
                    player_task_id,
                    npc_task_id,
                )
            else:
                self._work_logger.warning(
                    "[FORCED_DUO_MISS] day=%s hour=%s target=%s player_task=%s npc_task=%s mode=duo_any_roommate fallback=normal_route",
                    self.state.current_day,
                    self.state.current_hour,
                    force_target,
                    player_task_id,
                    npc_task_id,
                )
                skeleton_event = self.manager.trigger_skeleton_event()
        else:
            skeleton_event = self.manager.trigger_skeleton_event()
        if skeleton_event and skeleton_event.get("event_route") == "choice_required":
            choice_variant = skeleton_event.get("choice_variant", "solo_or_interaction")
            blackmail_target = skeleton_event.get("blackmail_target", {})
            blackmail_target_id = str((blackmail_target or {}).get("id", "")).strip()
            blackmail_targets = skeleton_event.get("blackmail_targets", []) or []
            blackmail_room_npc_ids = skeleton_event.get("blackmail_room_npc_ids", []) or []
            if choice_variant in {"solo_or_blackmail_group", "duo_or_blackmail_group"}:
                blackmail_cards = self._available_blackmail_cards_for_room_npcs(blackmail_room_npc_ids)
            else:
                blackmail_cards = self._available_blackmail_cards_for_target(blackmail_target_id)
            self._pending_work_mode_choice = {
                "choice_variant": choice_variant,
                "candidates": skeleton_event.get("interaction_candidates", []),
                "duo_candidate": skeleton_event.get("duo_candidate", {}),
                "blackmail_target": blackmail_target,
                "blackmail_targets": blackmail_targets,
                "blackmail_room_npc_ids": blackmail_room_npc_ids,
                "blackmail_cards": blackmail_cards,
                "debug_scenario_code": skeleton_event.get("debug_scenario_code", ""),
                "debug_choice_source": skeleton_event.get("debug_choice_source", "choice_required"),
            }
            self._current_event_card_mode = "work_mode_choice"
            return self._build_work_mode_choice_event(
                candidates=self._pending_work_mode_choice["candidates"],
                choice_variant=str(self._pending_work_mode_choice.get("choice_variant", "solo_or_interaction")),
                duo_candidate=self._pending_work_mode_choice.get("duo_candidate", {}),
                blackmail_target=self._pending_work_mode_choice.get("blackmail_target", {}),
                blackmail_cards=self._pending_work_mode_choice.get("blackmail_cards", []),
                debug_scenario_code=str(self._pending_work_mode_choice.get("debug_scenario_code", "")),
                debug_choice_source=str(self._pending_work_mode_choice.get("debug_choice_source", "choice_required")),
            )

        if skeleton_event is None:
            # Fallback到旧版事件模板
            event = self.manager.trigger_event()
            if event is None:
                return None
            self._current_event_card_mode = "combo"
            # 保存旧版事件描述供play_cards_with_ai使用
            self._last_event_description = event.get("description", "")
            self._last_event_prompt = event.get("prompt", "")
            return event

        return await self._render_work_event_from_skeleton(skeleton_event)

    async def choose_work_mode(self, mode: str, target_npc_id: str = "", card_id: str = "") -> dict:
        """
        处理工作阶段的“单干/交流”选择。

        参数:
            mode: "solo" / "interaction" / "duo" / "blackmail_broadcast"
            target_npc_id: mode=interaction时必填
            card_id: mode=blackmail_broadcast时必填（已记录卡ID）
        """
        if self._current_event_card_mode != "work_mode_choice":
            return {"error": "当前没有待选择的互动事件"}
        if not self._pending_work_mode_choice:
            return {"error": "互动选择上下文不存在"}

        mode = str(mode or "").strip().lower()
        if mode not in {"solo", "interaction", "duo", "blackmail_broadcast", "report_boss"}:
            return {"error": "mode 仅支持 solo / interaction / duo / blackmail_broadcast / report_boss"}

        if mode == "interaction":
            candidates = self._pending_work_mode_choice.get("candidates", [])
            candidate_ids = {str(x.get("id", "")) for x in candidates}
            if not target_npc_id or target_npc_id not in candidate_ids:
                return {"error": "请选择一个可交流的同事"}
            if self.state.daily.social_energy_left <= 0:
                return {"error": "今日社交精力不足"}
            self.state.daily.social_energy_left -= 1
            skeleton_event = self.manager.trigger_skeleton_event(
                force_mode="interaction",
                interaction_target_npc_id=target_npc_id,
            )
            if skeleton_event is None:
                self.state.daily.social_energy_left += 1
        elif mode == "duo":
            duo_target = str(
                (self._pending_work_mode_choice.get("duo_candidate", {}) or {}).get("id", "")
            )
            skeleton_event = self.manager.trigger_skeleton_event(
                force_mode="duo",
                interaction_target_npc_id=duo_target,
            )
        elif mode in {"blackmail_broadcast", "report_boss"}:
            variant = str(self._pending_work_mode_choice.get("choice_variant", ""))
            if variant not in {"solo_or_blackmail", "solo_or_blackmail_group", "duo_or_blackmail_group", "solo_or_report_boss"}:
                return {"error": "当前不支持传播黑料"}
            if self.state.daily.social_energy_left <= 0:
                return {"error": "今日社交精力不足"}
            cards = self._pending_work_mode_choice.get("blackmail_cards", []) or []
            selected_id = str(card_id or "").strip()
            selected_card = next((x for x in cards if str(x.get("id", "")) == selected_id), None)
            if mode == "report_boss" and not selected_card and cards:
                # 兜底：若前端漏传card_id，自动选首张可用黑料，避免流程卡死在“无AI请求”。
                selected_card = dict(cards[0])
                selected_id = str(selected_card.get("id", "")).strip()
                self._work_logger.warning(
                    "[WORK_MODE] report_boss fallback selected card_id=%s variant=%s",
                    selected_id,
                    variant,
                )
            if not selected_card:
                self._work_logger.warning(
                    "[WORK_MODE] no blackmail card selected mode=%s variant=%s card_id=%s available=%s",
                    mode,
                    variant,
                    selected_id,
                    len(cards),
                )
                return {"error": "请选择1张可传播的黑料卡"}
            selected_card_obj = self._get_recorded_card_by_id(selected_id)
            if selected_card_obj is None:
                return {"error": "该黑料卡不存在或已被使用，请重新选择"}
            if str(getattr(selected_card_obj, "record_type", "")).strip().lower() != "blackmail":
                return {"error": "证据卡不能用于传播黑料"}
            self.state.daily.social_energy_left -= 1
            if variant == "solo_or_report_boss":
                target_id = "boss"
                target_name = self._npc_display_name("boss", "经理")
                subject_id = str(selected_card.get("subject_npc_id", "")).strip()
                subject_name = str(selected_card.get("subject_npc_name", "某同事")).strip() or "某同事"
                original_blackmail_summary = str(selected_card.get("summary_text", "")).strip() or str(selected_card.get("source", "一段旧录音")).strip()
                distorted_blackmail_summary = await self._generate_distorted_blackmail_summary(
                    subject_npc_name=subject_name,
                    original_summary=original_blackmail_summary,
                )
                card_payload = dict(selected_card)
                card_payload["distorted_summary"] = distorted_blackmail_summary
                story_payload = await self._generate_blackmail_broadcast_story(
                    target_npc_id=target_id,
                    npc_name=target_name,
                    card_payload=card_payload,
                )
                player_judgement = str(story_payload.get("player_judgement", "增加怀疑")).strip()
                subject_judgement = str(story_payload.get("subject_judgement", "增加怀疑")).strip()
                player_sus_delta, _ = self._apply_blackmail_broadcast_judgement_v2(
                    listener_id=target_id,
                    target_id="player",
                    judgement=player_judgement,
                    reason_text=f"{self.state.player.name}来向经理告密，内容指向{subject_name}。",
                )
                if subject_id:
                    subject_sus_delta = 0
                    # 经理权重更高：对黑料对象怀疑增幅 *1.5
                    if subject_judgement == "增加怀疑":
                        subject_sus_delta = 15
                    elif subject_judgement == "减少怀疑":
                        subject_sus_delta = -15
                    if subject_sus_delta:
                        self.manager.modify_suspicion("boss", subject_id, subject_sus_delta)
                        self.manager.append_relationship_reason("boss", subject_id, f"收到{self.state.player.name}提供的黑料：{distorted_blackmail_summary[:30]}")
                if self.memory:
                    self.memory.add_impression(
                        observer_id="boss",
                        target_id="player",
                        day=self.state.current_day,
                        impression_text=f"{self.state.player.name}主动来告密，试图影响我的判断。",
                    )
                    if subject_id:
                        self.memory.add_impression(
                            observer_id="boss",
                            target_id=subject_id,
                            day=self.state.current_day,
                            impression_text=f"收到关于{subject_name}的线索：{distorted_blackmail_summary[:50]}",
                        )
                if not self._consume_blackmail_record_card(selected_id):
                    self.state.daily.social_energy_left += 1
                    return {"error": "黑料卡已失效，请重新选择"}
                self._pending_work_mode_choice = None
                self._current_event_card_mode = ""
                self._set_hour_settlement_context(is_blackmail=False, participant_npc_ids=[])
                return {
                    "_response_type": "card_result",
                    "combination_type": "report_boss",
                    "emotion_name": "告密",
                    "action_name": "汇报黑料",
                    "result_text": "",
                    "dialogues": {target_name: str(story_payload.get("story", "")).strip()},
                    "narrator": "",
                    "impression": str(story_payload.get("memory_summary", "")).strip() or "你向经理递交了一条黑料。",
                    "reactions": {},
                    "npc_name_id_map": self._npc_name_id_map_for_result(),
                    "affinity_delta": 0,
                    "suspicion_delta": player_sus_delta,
                    "gold_delta": 0,
                    "can_record": False,
                    "is_evidence_task": False,
                    "current_evidence_tag": "",
                    "can_use_record_card": any(rc.status.value == "blank" for rc in self.state.player.record_cards),
                    "blank_cards_count": sum(1 for rc in self.state.player.record_cards if rc.status.value == "blank"),
                    "blame_cards_count": self.state.player.items.get("blame_card", 0),
                    "blame_used_today": self.state.daily.blame_card_used,
                    "player_gold": self.state.player.gold,
                    "gold": self.state.player.gold,
                    "battery": self.state.player.battery,
                    "valid_evidence_count": self._valid_evidence_count(),
                    "recorded_cards_count": self._recorded_cards_count(),
                    "recorded_cards": self._serialize_recorded_cards(),
                    "coworkers": self.manager.get_player_coworkers(),
                    "scout_available_rooms": self._get_scout_available_rooms(),
                    "message": "你向经理打了小报告。",
                }
            if variant == "solo_or_blackmail":
                target = self._pending_work_mode_choice.get("blackmail_target", {}) or {}
                target_id = str(target.get("id", "")).strip()
                target_name = str(target.get("name", "同事")).strip() or "同事"
                if not target_id:
                    self.state.daily.social_energy_left += 1
                    return {"error": "黑料传播对象不存在"}
                skeleton_event = self.manager.trigger_skeleton_event(
                    force_mode="interaction",
                    interaction_target_npc_id=target_id,
                )
            elif variant == "solo_or_blackmail_group":
                targets = self._pending_work_mode_choice.get("blackmail_targets", []) or []
                target_ids = [
                    str(x.get("id", "")).strip()
                    for x in targets
                    if str(x.get("id", "")).strip()
                ]
                if not target_ids:
                    self.state.daily.social_energy_left += 1
                    return {"error": "当前房间没有可接收黑料的同事"}
                skeleton_event = self.manager.trigger_skeleton_event(force_mode="solo")
            else:
                targets = self._pending_work_mode_choice.get("blackmail_targets", []) or []
                target_ids = [
                    str(x.get("id", "")).strip()
                    for x in targets
                    if str(x.get("id", "")).strip()
                ]
                if not target_ids:
                    self.state.daily.social_energy_left += 1
                    return {"error": "当前房间没有可接收黑料的同事"}
                duo_target = str(
                    (self._pending_work_mode_choice.get("duo_candidate", {}) or {}).get("id", "")
                ).strip()
                if not duo_target:
                    self.state.daily.social_energy_left += 1
                    return {"error": "双人工作对象不存在"}
                skeleton_event = self.manager.trigger_skeleton_event(
                    force_mode="duo",
                    interaction_target_npc_id=duo_target,
                )
            if skeleton_event is None:
                self.state.daily.social_energy_left += 1
                return {"error": "无法生成传播黑料事件"}
            subject_id = str(selected_card.get("subject_npc_id", "")).strip()
            subject_name = str(selected_card.get("subject_npc_name", "某同事")).strip() or "某同事"
            original_blackmail_summary = str(selected_card.get("summary_text", "")).strip() or str(selected_card.get("source", "一段旧录音")).strip()
            distorted_blackmail_summary = await self._generate_distorted_blackmail_summary(
                subject_npc_name=subject_name,
                original_summary=original_blackmail_summary,
            )
            selected_card_for_broadcast = dict(selected_card)
            selected_card_for_broadcast["distorted_summary"] = distorted_blackmail_summary
            player_name_for_reason = str(self.state.player.name).strip() or "调查员"
            distorted_short = (distorted_blackmail_summary or "")[:30]
            if variant == "solo_or_blackmail":
                story_payload = await self._generate_blackmail_broadcast_story(
                    target_npc_id=target_id,
                    npc_name=target_name,
                    card_payload=selected_card_for_broadcast,
                )
                player_judgement = str(story_payload.get("player_judgement", "无感")).strip()
                subject_judgement = str(story_payload.get("subject_judgement", "无感")).strip()
                player_sus_delta, player_aff_delta = self._apply_blackmail_broadcast_judgement_v2(
                    listener_id=target_id,
                    target_id="player",
                    judgement=player_judgement,
                    reason_text=f"{player_name_for_reason}传了{subject_name}的黑料：{distorted_short}（→{player_judgement}）",
                )
                subject_sus_delta, subject_aff_delta = (0, 0)
                if subject_id:
                    subject_sus_delta, subject_aff_delta = self._apply_blackmail_broadcast_judgement_v2(
                        listener_id=target_id,
                        target_id=subject_id,
                        judgement=subject_judgement,
                        reason_text=f"听{player_name_for_reason}说{subject_name}{distorted_short}（→{subject_judgement}）",
                    )
                player_delta = player_sus_delta
                subject_delta = subject_sus_delta
                story_text = str(story_payload.get("story", "")).strip()
                if story_text:
                    skeleton_event["prebuilt_act1_text"] = story_text
                memory_override = str(story_payload.get("memory_summary", "")).strip()
                if memory_override:
                    skeleton_event["memory_summary_override"] = memory_override
                skeleton_event["blackmail_broadcast_meta"] = {
                    "npc_name": target_name,
                    "subject_npc_id": subject_id,
                    "subject_npc_name": subject_name,
                    "player_judgement": player_judgement,
                    "subject_judgement": subject_judgement,
                    "subject_reaction_text": str(story_payload.get("subject_reaction_text", "")).strip(),
                    "player_suspicion_delta": player_delta,
                    "subject_suspicion_delta": subject_delta if subject_id else 0,
                }
                skeleton_event["debug_choice_source"] = "blackmail_broadcast"
                self._pending_work_mode_choice = None
                result = self._build_blackmail_broadcast_result(
                    skeleton_event=skeleton_event,
                    target_id=target_id,
                    target_name=target_name,
                    story_payload=story_payload,
                    selected_card=selected_card_for_broadcast,
                )
                if "error" in result:
                    return result
                result["scout_result"] = await self._consume_pending_scout_result()
                return result

            target_entries = self._pending_work_mode_choice.get("blackmail_targets", []) or []
            story_payloads: list[dict] = []
            dialogues: dict[str, str] = {}
            memory_parts: list[str] = []
            listener_meta: list[dict] = []
            target_name_list = [
                str(x.get("name", "同事")).strip() or "同事"
                for x in target_entries
            ]
            valid_listeners: list[tuple[str, str, list[str]]] = []
            for target in target_entries:
                listener_id = str(target.get("id", "")).strip()
                listener_name = str(target.get("name", "同事")).strip() or "同事"
                if not listener_id:
                    continue
                copresent = [n for n in target_name_list if n != listener_name]
                valid_listeners.append((listener_id, listener_name, copresent))

            payloads = await asyncio.gather(
                *[
                    self._generate_blackmail_broadcast_story(
                        target_npc_id=lid,
                        npc_name=lname,
                        card_payload=selected_card_for_broadcast,
                        co_present_names=cop,
                    )
                    for (lid, lname, cop) in valid_listeners
                ]
            ) if valid_listeners else []

            for (listener_id, listener_name, _cop), payload in zip(valid_listeners, payloads):
                story_payloads.append(payload)
                story_text = str(payload.get("story", "")).strip()
                if story_text:
                    dialogues[listener_name] = story_text
                memory_text = str(payload.get("memory_summary", "")).strip()
                if memory_text:
                    memory_parts.append(memory_text)
                player_judgement = str(payload.get("player_judgement", "无感")).strip()
                subject_judgement = str(payload.get("subject_judgement", "无感")).strip()
                player_sus_delta, _player_aff_delta = self._apply_blackmail_broadcast_judgement_v2(
                    listener_id=listener_id,
                    target_id="player",
                    judgement=player_judgement,
                    reason_text=f"{player_name_for_reason}传了{subject_name}的黑料：{distorted_short}（→{player_judgement}）",
                )
                subject_sus_delta = 0
                if subject_id:
                    subject_sus_delta, _subject_aff_delta = self._apply_blackmail_broadcast_judgement_v2(
                        listener_id=listener_id,
                        target_id=subject_id,
                        judgement=subject_judgement,
                        reason_text=f"听{player_name_for_reason}说{subject_name}{distorted_short}（→{subject_judgement}）",
                    )
                listener_meta.append(
                    {
                        "npc_id": listener_id,
                        "npc_name": listener_name,
                        "player_judgement": player_judgement,
                        "subject_judgement": subject_judgement,
                        "subject_reaction_text": str(payload.get("subject_reaction_text", "")).strip(),
                        "player_suspicion_delta": player_sus_delta,
                        "subject_suspicion_delta": subject_sus_delta if subject_id else 0,
                    }
                )

            if not story_payloads:
                self.state.daily.social_energy_left += 1
                return {"error": "群体传播黑料失败：没有可用听众"}
            group_memory_summary = "；".join(memory_parts[:3]) if memory_parts else ""
            skeleton_event["blackmail_broadcast_meta"] = {
                "subject_npc_id": subject_id,
                "subject_npc_name": subject_name,
                "listeners": listener_meta,
            }
            skeleton_event["debug_choice_source"] = "blackmail_broadcast_group"

            # ── 表现层优化：把多条独立回复整合为一段连贯群戏剧情 ──
            # 仅在听众 ≥ 2 时调用整合 AI；记忆/数值结算已在前面用各自判断完成，整合只动展示文本。
            merged_dialogues = dict(dialogues)
            try:
                if len(valid_listeners) >= 2:
                    listener_replies_for_merge: list[dict] = []
                    for (lid, lname, _cop), payload, lmeta in zip(
                        valid_listeners, payloads, listener_meta
                    ):
                        listener_replies_for_merge.append(
                            {
                                "npc_name": lname,
                                "story": str(payload.get("story", "") or "").strip(),
                                "player_judgement": str(lmeta.get("player_judgement", "无感") or "无感"),
                                "subject_judgement": str(lmeta.get("subject_judgement", "无感") or "无感"),
                            }
                        )
                    merged_text = await AIService.merge_blackmail_broadcast_replies_v2(
                        player_name=self.state.player.name,
                        subject_npc_name=subject_name,
                        room_name=EvidenceConverter.ROOM_NAMES.get(
                            self.state.player.current_room, "未知"
                        ),
                        distorted_summary=distorted_blackmail_summary,
                        listener_replies=listener_replies_for_merge,
                    )
                    if merged_text:
                        # 前端按 dict 顺序拼接文本但忽略 key，所以一条记录就是一整段连贯剧情
                        merged_dialogues = {"_merged_": merged_text}
            except Exception:
                merged_dialogues = dict(dialogues)

            self._pending_work_mode_choice = None
            result = self._build_blackmail_broadcast_group_result(
                skeleton_event=skeleton_event,
                listener_ids=[str(x.get("id", "")).strip() for x in target_entries if str(x.get("id", "")).strip()],
                selected_card=selected_card_for_broadcast,
                dialogues=merged_dialogues,
                memory_summary=group_memory_summary,
            )
            if "error" in result:
                return result
            result["scout_result"] = await self._consume_pending_scout_result()
            return result
        else:
            skeleton_event = self.manager.trigger_skeleton_event(force_mode="solo")

        self._pending_work_mode_choice = None
        if skeleton_event is None:
            return {"error": "无法生成事件"}
        return await self._render_work_event_from_skeleton(skeleton_event)

    def _build_blackmail_broadcast_result(
        self,
        skeleton_event: dict,
        target_id: str,
        target_name: str,
        story_payload: dict,
        selected_card: dict,
    ) -> dict:
        """
        黑料传播是“处理方式选择”的直接结算分支：
        选完黑料卡后立即给出Act2结果，不再要求玩家额外出牌。
        """
        current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
        room_name = EvidenceConverter.ROOM_NAMES.get(self.state.player.current_room, "未知")
        story_text = str(story_payload.get("story", "")).strip()
        if not story_text:
            story_text = f"{target_name}听完后眼神变了变，这条黑料在空气里发酵开来。"
        memory_summary = str(story_payload.get("memory_summary", "")).strip()
        if not memory_summary:
            memory_summary = f"你在{room_name}向{target_name}传播了黑料。"
        selected_card_id = str(selected_card.get("id", "")).strip()
        if not selected_card_id or not self._consume_blackmail_record_card(selected_card_id):
            return {"error": "黑料传播失败：该黑料卡已失效，请重新选择"}

        self._last_record_card_context = {
            "subject_npc_id": str(target_id),
            "subject_npc_name": str(target_name),
            "summary_text": memory_summary[:100],
            "is_evidence": bool(current_task.evidence_tag is not None),
        }
        meta = skeleton_event.get("blackmail_broadcast_meta", {}) or {}
        subject_npc_id = str(meta.get("subject_npc_id", "")).strip()
        subject_npc_name = str(meta.get("subject_npc_name", "某同事")).strip() or "某同事"
        subject_judgement = str(meta.get("subject_judgement", "无感")).strip() or "无感"
        subject_reaction_text = str(meta.get("subject_reaction_text", "")).strip()
        player_name = str(self.state.player.name).strip() or "调查员"
        blackmail_summary = str(selected_card.get("distorted_summary", "")).strip() or str(selected_card.get("summary_text", "")).strip() or memory_summary
        if self.memory:
            self.memory.add_impression(
                observer_id=str(target_id),
                target_id="player",
                day=self.state.current_day,
                impression_text=f"{player_name}在{room_name}分享了{subject_npc_name}的黑料，说{blackmail_summary}",
            )
            if subject_npc_id:
                self.memory.add_impression(
                    observer_id=str(target_id),
                    target_id=subject_npc_id,
                    day=self.state.current_day,
                    impression_text=self._build_blackmail_subject_impression_text(
                        listener_id=str(target_id),
                        player_name=player_name,
                        subject_npc_name=subject_npc_name,
                        blackmail_summary=blackmail_summary,
                        subject_judgement=subject_judgement,
                        ai_subject_reaction_text=subject_reaction_text,
                    ),
                )
        self._today_events_summary.append(memory_summary)
        self._set_hour_settlement_context(
            is_blackmail=True,
            participant_npc_ids=[str(x) for x in skeleton_event.get("participant_npc_ids", []) if str(x)],
            blackmail_listener_ids=[str(target_id)],
        )

        self._current_event_card_mode = ""
        self._current_skeleton_event = None
        self._current_event_context = {}

        result = {
            "_response_type": "card_result",
            "combination_type": "solo_action",
            "solo_action_mode": True,
            "emotion_name": "（黑料模式无情绪卡）",
            "action_name": "传播黑料",
            "result_text": "",
            "dialogues": {target_name: story_text},
            "narrator": "",
            "reactions": {},
            "npc_name_id_map": self._npc_name_id_map_for_result(),
            "affinity_delta": 0,
            "suspicion_delta": 0,
            "gold_delta": 0,
            "can_record": True,
            "is_evidence_task": bool(current_task.evidence_tag is not None),
            "current_evidence_tag": current_task.evidence_tag,
        }
        result.update(self._apply_task_reward(current_task))
        result["can_use_record_card"] = any(
            rc.status.value == "blank" for rc in self.state.player.record_cards
        )
        result["blank_cards_count"] = sum(
            1 for rc in self.state.player.record_cards if rc.status.value == "blank"
        )
        result["blame_cards_count"] = self.state.player.items.get("blame_card", 0)
        result["blame_used_today"] = self.state.daily.blame_card_used
        result["player_gold"] = self.state.player.gold
        result["gold"] = self.state.player.gold
        result["battery"] = self.state.player.battery
        result["valid_evidence_count"] = self._valid_evidence_count()
        result["recorded_cards_count"] = self._recorded_cards_count()
        result["recorded_cards"] = self._serialize_recorded_cards()
        result["coworkers"] = self.manager.get_player_coworkers()
        result["scout_available_rooms"] = self._get_scout_available_rooms()
        if self._pending_scout_result is not None:
            result["scout_result"] = self._pending_scout_result
            self._pending_scout_result = None
        else:
            result["scout_result"] = None
        self._finalize_hour_settlement_for_result(result)
        return result

    def _build_blackmail_broadcast_group_result(
        self,
        skeleton_event: dict,
        listener_ids: list[str],
        selected_card: dict,
        dialogues: dict[str, str],
        memory_summary: str,
    ) -> dict:
        """状况4：群体传播黑料后直接结算，不再进入二次出牌。"""
        current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
        room_name = EvidenceConverter.ROOM_NAMES.get(self.state.player.current_room, "未知")
        subject_npc_id = str(selected_card.get("subject_npc_id", "")).strip()
        subject_npc_name = str(selected_card.get("subject_npc_name", "某同事")).strip() or "某同事"
        if not memory_summary:
            memory_summary = f"你在{room_name}进行了一次群体黑料传播。"
        selected_card_id = str(selected_card.get("id", "")).strip()
        if not selected_card_id or not self._consume_blackmail_record_card(selected_card_id):
            return {"error": "群体传播失败：该黑料卡已失效，请重新选择"}

        self._last_record_card_context = {
            "subject_npc_id": subject_npc_id,
            "subject_npc_name": subject_npc_name,
            "summary_text": memory_summary[:100],
            "is_evidence": bool(current_task.evidence_tag is not None),
        }
        if self.memory and listener_ids:
            player_name = str(self.state.player.name).strip() or "调查员"
            summary_text = str(selected_card.get("distorted_summary", "")).strip() or str(selected_card.get("summary_text", "")).strip() or memory_summary
            listener_meta = skeleton_event.get("blackmail_broadcast_meta", {}).get("listeners", []) or []
            subject_judgement_map = {
                str(x.get("npc_id", "")).strip(): str(x.get("subject_judgement", "无感")).strip() or "无感"
                for x in listener_meta
                if str(x.get("npc_id", "")).strip()
            }
            subject_reaction_map = {
                str(x.get("npc_id", "")).strip(): str(x.get("subject_reaction_text", "")).strip()
                for x in listener_meta
                if str(x.get("npc_id", "")).strip()
            }
            for listener_id in listener_ids:
                self.memory.add_impression(
                    observer_id=listener_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=f"{player_name}在{room_name}分享了{subject_npc_name}的黑料，说{summary_text}",
                )
                if subject_npc_id:
                    self.memory.add_impression(
                        observer_id=listener_id,
                        target_id=subject_npc_id,
                        day=self.state.current_day,
                        impression_text=self._build_blackmail_subject_impression_text(
                            listener_id=listener_id,
                            player_name=player_name,
                            subject_npc_name=subject_npc_name,
                            blackmail_summary=summary_text,
                            subject_judgement=subject_judgement_map.get(listener_id, "无感"),
                            ai_subject_reaction_text=subject_reaction_map.get(listener_id, ""),
                        ),
                    )
        if subject_npc_id in self.state.npcs or subject_npc_id == "boss":
            self._increase_fear(subject_npc_id, 5, "被黑料威胁")
        self._today_events_summary.append(memory_summary)
        self._set_hour_settlement_context(
            is_blackmail=True,
            participant_npc_ids=[str(x) for x in skeleton_event.get("participant_npc_ids", []) if str(x)],
            blackmail_listener_ids=[str(x) for x in listener_ids if str(x)],
        )

        self._current_event_card_mode = ""
        self._current_skeleton_event = None
        self._current_event_context = {}

        if not dialogues:
            dialogues = {"同事们": "你把黑料抛了出去，空气里只剩下谨慎的沉默。"}
        result = {
            "_response_type": "card_result",
            "combination_type": "solo_action",
            "solo_action_mode": True,
            "emotion_name": "（黑料模式无情绪卡）",
            "action_name": "群体传播黑料",
            "result_text": "",
            "dialogues": dialogues,
            "narrator": "",
            "reactions": {},
            "npc_name_id_map": self._npc_name_id_map_for_result(),
            "affinity_delta": 0,
            "suspicion_delta": 0,
            "gold_delta": 0,
            "can_record": True,
            "is_evidence_task": bool(current_task.evidence_tag is not None),
            "current_evidence_tag": current_task.evidence_tag,
        }
        result.update(self._apply_task_reward(current_task))
        result["can_use_record_card"] = any(
            rc.status.value == "blank" for rc in self.state.player.record_cards
        )
        result["blank_cards_count"] = sum(
            1 for rc in self.state.player.record_cards if rc.status.value == "blank"
        )
        result["blame_cards_count"] = self.state.player.items.get("blame_card", 0)
        result["blame_used_today"] = self.state.daily.blame_card_used
        result["player_gold"] = self.state.player.gold
        result["gold"] = self.state.player.gold
        result["battery"] = self.state.player.battery
        result["valid_evidence_count"] = self._valid_evidence_count()
        result["recorded_cards_count"] = self._recorded_cards_count()
        result["recorded_cards"] = self._serialize_recorded_cards()
        result["coworkers"] = self.manager.get_player_coworkers()
        result["scout_available_rooms"] = self._get_scout_available_rooms()
        if self._pending_scout_result is not None:
            result["scout_result"] = self._pending_scout_result
            self._pending_scout_result = None
        else:
            result["scout_result"] = None
        self._finalize_hour_settlement_for_result(result)
        return result

    def _build_work_mode_choice_event(
        self,
        candidates: list[dict],
        choice_variant: str = "solo_or_interaction",
        duo_candidate: dict | None = None,
        blackmail_target: dict | None = None,
        blackmail_cards: list[dict] | None = None,
        debug_scenario_code: str = "",
        debug_choice_source: str = "choice_required",
    ) -> dict:
        """构建“单干/交流”选择事件。"""
        if choice_variant == "duo_or_blackmail_group":
            duo_name = str((duo_candidate or {}).get("name", "某同事"))
            blackmail_count = len(blackmail_cards or [])
            lines = [f"你与{duo_name}同做一项工作，同时房间里还有其他同事。要继续双人处理，还是群体传播一条黑料？"]
            lines.append(f"可传播黑料：{blackmail_count}条")
        elif choice_variant == "solo_or_blackmail":
            target_name = str((blackmail_target or {}).get("name", "某同事")).strip() or "某同事"
            blackmail_count = len(blackmail_cards or [])
            lines = [f"你和{target_name}在同房间处理不同任务。要继续自己干活，还是传播一条黑料？"]
            lines.append(f"可传播黑料：{blackmail_count}条")
        elif choice_variant == "solo_or_report_boss":
            blackmail_count = len(blackmail_cards or [])
            lines = ["经理就在你旁边。你要继续工作，还是趁机向经理打小报告？"]
            lines.append(f"可汇报黑料：{blackmail_count}条")
        elif choice_variant == "solo_or_blackmail_group":
            blackmail_count = len(blackmail_cards or [])
            lines = ["你和多名同事在同房间处理不同任务。要继续自己干活，还是群体传播一条黑料？"]
            lines.append(f"可传播黑料：{blackmail_count}条")
        else:
            lines = ["你和同房间同事的任务不同。要继续自己工作，还是临时去交流？"]
            if candidates:
                names = "、".join([str(c.get("name", "某同事")) for c in candidates[:4]])
                lines.append(f"可交流对象：{names}")
        lines.append(f"今日社交精力剩余：{self.state.daily.social_energy_left}")
        if choice_variant == "duo_or_blackmail_group":
            options = [
                {"id": "duo", "label": "继续双人处理"},
            ]
            if blackmail_cards:
                options.append({"id": "blackmail_broadcast", "label": "群体传播黑料"})
        elif choice_variant == "solo_or_blackmail":
            options = [
                {"id": "solo", "label": "自己干活"},
            ]
            if blackmail_cards:
                options.append({"id": "blackmail_broadcast", "label": "传播黑料"})
        elif choice_variant == "solo_or_blackmail_group":
            options = [
                {"id": "solo", "label": "自己干活"},
            ]
            if blackmail_cards:
                options.append({"id": "blackmail_broadcast", "label": "群体传播黑料"})
        elif choice_variant == "solo_or_report_boss":
            options = [
                {"id": "solo", "label": "继续工作"},
            ]
            if blackmail_cards:
                options.append({"id": "report_boss", "label": "🔪 向经理汇报黑料（打小报告）"})
        else:
            options = [
                {"id": "solo", "label": "自己干自己的"},
            ]
            if candidates:
                for c in candidates:
                    cid = str(c.get("id", "")).strip()
                    cname = str(c.get("name", "某同事")).strip() or "某同事"
                    if cid:
                        options.append({"id": f"interaction:{cid}", "label": f"与{cname}交流"})
            else:
                options.append({"id": "interaction", "label": "与同事交流"})

        return {
            "event_id": "WORK_MODE_CHOICE",
            "event_name": "工作抉择",
            "description": "\n".join(lines),
            "prompt": "",
            "emotion_cards": [],
            "action_cards": [],
            "has_evidence_hint": False,
            "evidence_hint": "",
            "choice_required": True,
            "choice_mode": "work_mode",
            "choice_variant": choice_variant,
            "social_energy_left": self.state.daily.social_energy_left,
            "options": options,
            "debug_scenario_code": debug_scenario_code,
            "debug_choice_source": debug_choice_source,
            "debug_route": "choice_required",
            "blackmail_target": blackmail_target or {},
            "blackmail_cards": blackmail_cards or [],
            "npc_options": [
                {"id": c.get("id", ""), "name": c.get("name", "")}
                for c in candidates
            ],
        }

    async def _render_work_event_from_skeleton(self, skeleton_event: dict) -> dict:
        """把已选定骨架事件渲染成前端展示数据。"""
        # 保存骨架事件数据（供play_cards_with_ai使用）
        self._current_skeleton_event = skeleton_event
        self._current_event_context = {
            "event_route": skeleton_event.get("event_route", "solo"),
            "participant_npc_ids": skeleton_event.get("participant_npc_ids", []),
            "observer_npc_ids": skeleton_event.get("observer_npc_ids", []),
        }
        self._last_player_event_route = str(skeleton_event.get("event_route", "")).strip()
        primary_npc_raw = skeleton_event.get("primary_npc")

        if primary_npc_raw is None:
            # 单人事件：Act1固定走CSV预设池（不请求AI）。
            from .event_system import EventSystem
            current_task = self.state.player.selected_tasks[
                self.state.player.current_task_index
            ]
            is_evidence = current_task.evidence_tag is not None
            # 证据任务：在 5 张单人行为牌中标记 2 张为"证据触发牌"。
            solo_actions = EventSystem.draw_solo_action_cards(
                5, is_evidence_task=is_evidence
            )
            self.state.player.hand_emotions = []
            self.state.player.hand_actions = [c["id"] for c in solo_actions]
            self._current_event_card_mode = "solo_action"
            # 把抽出的卡（含 evidence_marked）挂到 skeleton 上，供 Act 2 阶段查询
            skeleton_event["drawn_emotions"] = []
            skeleton_event["drawn_actions"] = solo_actions

            ev_type_val = current_task.evidence_type.value if current_task.evidence_type else None
            room_val = skeleton_event.get("room", "office")
            room_name = EvidenceConverter.ROOM_NAMES.get(
                Room(room_val) if isinstance(room_val, str) else room_val,
                str(room_val),
            )
            solo_act1_text = self._pick_room_element_text(
                room_key=str(room_val),
                pool="solo_act1",
                fallback=f"你独自来到{room_name}，准备执行{current_task.name}。",
            )
            display = EventSystem.build_solo_event(
                room_val,
                solo_actions,
                is_evidence,
                ev_type_val,
                scene_override=solo_act1_text,
                event_id=skeleton_event.get("skeleton_id"),
                event_name=skeleton_event.get("event_name", "工作突发事件"),
            )
            # 缓存单人事件元数据：play_solo_action_with_ai 在 Act 2 阶段需要
            # drawn_actions（判断 evidence_marked）和 evidence_hint。
            self._pending_solo_event_meta = {
                "drawn_actions": list(solo_actions),
                "is_evidence_task": bool(is_evidence),
                "evidence_hint": str(display.get("evidence_hint", "") or ""),
            }
            self._current_skeleton_event = None
            self._last_act1_text = display["description"]
            self._last_event_description = display["description"]
            self._last_event_prompt = display.get("prompt", "")
            self._last_npc_infos = []
            display["debug_scenario_code"] = str(skeleton_event.get("debug_scenario_code", ""))
            display["debug_choice_source"] = str(skeleton_event.get("debug_choice_source", "solo"))
            display["debug_route"] = str(skeleton_event.get("event_route", "solo"))
            return display

        self._current_event_card_mode = "combo"

        npc_infos = []
        primary_npc = skeleton_event.get("primary_npc")
        npc_candidates = [primary_npc] if primary_npc else []
        for npc_data in npc_candidates:
            npc_id = npc_data["id"]
            if npc_id == "boss":
                info = {
                    "id": "boss",
                    "name": self._npc_display_name("boss", "经理"),
                    "identity": MemorySystem.get_identity("boss"),
                    "aim": MemorySystem.get_aim("boss"),
                    "relationships": MemorySystem.build_relationship_text(
                        "boss", self.state.relationships, self.state.npcs
                    ),
                    "memories": self.memory.get_memories("boss") if self.memory else [],
                    "memory_and_relations": self.memory.build_memory_and_relations_text(
                        "boss",
                        self.state.relationships,
                        self.state.npcs,
                        player_name=self.state.player.name,
                    ) if self.memory else "",
                }
            elif npc_id in self.state.npcs:
                info = self.memory.build_npc_info_for_ai(
                    npc_id,
                    self.state.relationships,
                    self.state.npcs,
                    player_name=self.state.player.name,
                ) if self.memory else {
                    "id": npc_id,
                    "name": npc_data.get("name", npc_id),
                    "identity": "",
                    "relationships": "",
                    "memories": [],
                }
            else:
                continue
            npc_infos.append(info)

        room_name = EvidenceConverter.ROOM_NAMES.get(
            Room(skeleton_event["room"]),
            skeleton_event["room"]
        )
        primary_name = primary_npc["name"] if primary_npc else "某人"
        prebuilt_act1 = str(skeleton_event.get("prebuilt_act1_text", "")).strip()
        if prebuilt_act1:
            act1_text = prebuilt_act1
        else:
            dl = DataLoader()
            current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
            duo_task_text = str(current_task.name)
            primary_id = str((primary_npc or {}).get("id", "")).strip() or "npc"

            # 抽法 B: 把房间内 [玩家, primary NPC] 两人作为候选,
            # 系统按加权随机从 random_accidents.csv 抽一条,主角由 CSV 决定。
            random_accident = dl.pick_random_accident(
                location=str(skeleton_event["room"]),
                candidates=["player", primary_id],
                player_name=self.state.player.name,
            )

            if random_accident:
                accident_text = str(random_accident.get("text", "")).strip()
                accident_condition = str(random_accident.get("condition", "neutral")).strip().lower() or "neutral"
                accident_subject_id = str(random_accident.get("subject_id", "")).strip().lower()
            else:
                # 该房间该候选组合没有 CSV 数据,降级为通用兜底
                accident_text = f"{primary_name}与{self.state.player.name}在{duo_task_text}中出现了容易引发误会的突发状况。"
                accident_condition = "neutral"
                accident_subject_id = ""

            # 写入 skeleton_event(供日志/调试)和 _current_event_context(供 PostAct2 决策器使用)
            skeleton_event["random_accident"] = {
                "subject_id": accident_subject_id,
                "condition": accident_condition,
                "text": accident_text,
            }
            self._current_event_context["accident_meta"] = {
                "subject_id": accident_subject_id,
                "condition": accident_condition,
                "text": accident_text,
                "primary_npc_id": primary_id,
            }

            # Act 1 不再注入证据线索(规格: 证据线索仅在 Act 2 玩家选了标记卡时才出现)。
            # absurd_element 和 workplace_element 不再使用,完全由 random_accident 驱动剧情。
            act1_result = await AIService.generate_act1(
                assembled_seed=skeleton_event["assembled_seed"],
                npc_infos=npc_infos,
                primary_npc_name=primary_name,
                room_name=room_name,
                player_name=self.state.player.name,
                is_solo=(len(npc_infos) == 0),
                is_evidence_event=False,
                evidence_hint="",
                duo_task_text=duo_task_text,
                duo_random_accident=accident_text,
                duo_random_condition=accident_condition,
            )
            act1_text = act1_result["act1_text"]

        self._last_act1_text = act1_text
        self._last_event_description = act1_text
        self._last_event_prompt = ""
        self._last_npc_infos = npc_infos

        from .event_system import EventSystem
        display = EventSystem.build_event_display_v2(
            skeleton_event=skeleton_event,
            act1_text=act1_text,
            emotions=skeleton_event["drawn_emotions"],
            actions=skeleton_event["drawn_actions"],
            is_evidence_task=skeleton_event.get("is_evidence_task", False),
            evidence_type_value=skeleton_event.get("evidence_type_value"),
        )
        display["debug_scenario_code"] = str(skeleton_event.get("debug_scenario_code", ""))
        display["debug_choice_source"] = str(skeleton_event.get("debug_choice_source", skeleton_event.get("event_route", "")))
        display["debug_route"] = str(skeleton_event.get("event_route", ""))
        return display

    def _apply_observer_effects(
        self,
        observer_ids: list[str],
        memory_summary: str | None = None,
        source: str = "",
    ) -> None:
        """
        已废弃：旧旁观者入口只会写“旁观者 -> 玩家”。
        主流程统一使用 _resolve_hour_bystander_and_npc_pairs()，以支持同房全员互相目击。

        旁观者效果：
        1) 不调用AI，直接写入规则记忆；
        2) 不产生任何关系数值变化。
        """
        observers = [oid for oid in observer_ids if oid and oid in self.state.npcs]
        if not observers:
            return

        room_name = EvidenceConverter.ROOM_NAMES.get(
            self.state.player.current_room, "未知"
        )
        summary_text = str(memory_summary or "").strip()
        _ = str(source or "").strip()  # 预留：未来可按来源类型细分旁观记忆模板

        if self.memory:
            player_name = str(self.state.player.name).strip() or "调查员"
            dl = DataLoader()
            for observer_id in observers:
                if summary_text:
                    self.memory.add_impression(
                        observer_id=observer_id,
                        target_id="player",
                        day=self.state.current_day,
                        impression_text=summary_text,
                    )
                    continue
                witness_default = str(dl.get_npc_field(observer_id, "witness_default", "")).strip()
                if not witness_default:
                    witness_default = "我没怎么打过交道，先保持距离。"
                current_task_name = "当前工作"
                idx = int(self.state.player.current_task_index)
                if 0 <= idx < len(self.state.player.selected_tasks):
                    current_task_name = str(self.state.player.selected_tasks[idx].name).strip() or "当前工作"
                self.memory.add_impression(
                    observer_id=observer_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=f"我在{room_name}注意到{player_name}在{current_task_name}，{witness_default}",
                )

    async def play_cards_async(self, emotion_id: str, action_id: str) -> dict:
        """
        Legacy入口：已下线旧的多NPC XML导演链路。
        统一转发到 play_cards_with_ai_v2（单Agent化主流程）。
        """
        return await self.play_cards_with_ai_v2(emotion_id, action_id)

    async def play_cards_with_ai(self, emotion_id: str, action_id: str) -> dict:
        """旧命名兼容入口。"""
        return await self.play_cards_async(emotion_id, action_id)

    async def play_solo_action_with_ai(self, action_id: str) -> dict:
        """
        单人事件专用：只打1张行为牌，不走combo。
        """
        if self.state.game_over:
            return {"error": "游戏已结束"}
        if self._current_event_card_mode != "solo_action":
            return {"error": "当前不是单人事件出牌阶段"}
        if action_id not in self.state.player.hand_actions:
            return {"error": f"单人行为牌{action_id}不在手牌中"}

        solo_card = next((c for c in SOLO_ACTION_CARDS if c.id == action_id), None)
        if not solo_card:
            return {"error": "无效的单人行为牌ID"}

        current_task = self.state.player.selected_tasks[self.state.player.current_task_index]
        room_name = EvidenceConverter.ROOM_NAMES.get(self.state.player.current_room, "未知")
        act1_text = getattr(self, "_last_act1_text", "")

        # 证据触发判定：本次单人事件是证据任务，且玩家选中的行为牌被标记。
        # 注：_render_work_event_from_skeleton 在单人分支会把 _current_skeleton_event
        # 清空为 None，所以这里读 _pending_solo_event_meta（在该分支同一处赋值）。
        solo_meta = getattr(self, "_pending_solo_event_meta", None) or {}
        is_evidence = current_task.evidence_tag is not None
        evidence_triggered = False
        if is_evidence:
            drawn_actions = solo_meta.get("drawn_actions", []) or []
            picked_action = next(
                (c for c in drawn_actions if c.get("id") == action_id), None
            )
            evidence_triggered = bool(
                picked_action and picked_action.get("evidence_marked")
            )
        evidence_hint_for_act2 = (
            str(solo_meta.get("evidence_hint", "") or "").strip()
            if (is_evidence and evidence_triggered) else ""
        )

        room_key = str(self.state.player.current_room.value)
        act2_pool = self._solo_style_to_act2_pool(solo_card.style)
        fallback_act2 = (
            f"你选择了「{solo_card.name}」，在{room_name}里继续{current_task.name}。"
            f"这次行动的基调是「{solo_card.tone}」。"
        )
        act2_text = self._pick_room_element_text(
            room_key=room_key,
            pool=act2_pool,
            fallback=fallback_act2,
        )
        if evidence_hint_for_act2:
            act2_text = f"{act2_text}\n{evidence_hint_for_act2}".strip()
        solo_reward = self._resolve_solo_reward(room_key=room_key, current_task=current_task)

        self.state.player.hand_emotions = []
        self.state.player.hand_actions = []
        self._current_event_card_mode = ""

        summary = (
            f"玩家在{room_name}独自行动，选择了「{solo_card.name}」，"
            f"最终场面基调是「{solo_card.tone}」。"
        )
        reward_text = str(solo_reward.get("text", "")).strip()
        if reward_text:
            summary = f"{summary} {reward_text}"
        self._last_record_card_context = {
            "subject_npc_id": "",
            "subject_npc_name": "",
            "summary_text": summary[:100],
            "is_evidence": bool(is_evidence),
            "evidence_triggered": evidence_triggered,
            "use_ai_summary": False,
        }
        self._today_events_summary.append(summary)
        self._set_hour_settlement_context(
            is_blackmail=False,
            participant_npc_ids=[str(x) for x in self._current_event_context.get("participant_npc_ids", []) if str(x)],
        )

        room_case_id = int(self._active_front_case_id or 0)
        room_case_ctx = dict(self._active_front_case_ctx or {})
        if room_case_id in {3, 10} and self.memory:
            npc_ids = [str(x).strip() for x in room_case_ctx.get("npc_ids", []) if str(x).strip()]
            for witness_id in npc_ids:
                if witness_id == "boss":
                    continue
                witness_reaction = DataLoader().get_npc_witness_reaction(witness_id)
                if not witness_reaction:
                    witness_reaction = "我没多说什么，只是把细节记在了心里。"
                witness_text = (
                    f"我在{room_name}里看到{self.state.player.name}在旁边{current_task.name}，{witness_reaction}"
                )
                self.memory.add_impression(
                    observer_id=witness_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=witness_text,
                )
                self._log_witness_event(
                    source="case3or10_player_solo_bystander",
                    observer_id=witness_id,
                    target_id="player",
                    room_key=self.state.player.current_room.value,
                    text=witness_text,
                    extra={"case_id": room_case_id},
                )
                self.manager.append_relationship_reason(witness_id, "player", "同房各做各的，旁观到玩家行动。")

        result = {
            "combination_type": "solo_action",
            "emotion_name": "（单人事件无情绪卡）",
            "action_name": solo_card.name,
            "result_text": act2_text,
            "dialogues": {},
            "narrator": act2_text,
            "reactions": {},
            "affinity_delta": 0,
            "suspicion_delta": 0,
            "gold_delta": int(solo_reward.get("gold_delta", 0) or 0),
            "can_record": True,
            "is_evidence_task": is_evidence,
            "current_evidence_tag": current_task.evidence_tag,
            "solo_action_mode": True,
            "solo_action_tone": solo_card.tone,
            "solo_reward": solo_reward,
            "solo_future_hook": {
                "peek_applied": False,
                "peek_risk": solo_card.peek_risk,
                "peek_affinity_bias": solo_card.peek_affinity_bias,
                "peek_suspicion_bias": solo_card.peek_suspicion_bias,
                "note": "预留字段：未来可接入“被经理/同事偷窥”后修正好感与怀疑。",
            },
            "npc_name_id_map": self._npc_name_id_map_for_result(),
        }
        result.update(self._apply_task_reward(current_task))
        if reward_text:
            existing_append = str(result.get("settlement_append_text", "")).strip()
            if existing_append:
                result["settlement_append_text"] = f"{existing_append}\n🎁 {reward_text}"
            else:
                result["settlement_append_text"] = f"🎁 {reward_text}"

        result["can_use_record_card"] = any(
            rc.status.value == "blank" for rc in self.state.player.record_cards
        )
        result["blank_cards_count"] = sum(
            1 for rc in self.state.player.record_cards if rc.status.value == "blank"
        )
        result["blame_cards_count"] = self.state.player.items.get("blame_card", 0)
        result["blame_used_today"] = self.state.daily.blame_card_used
        result["player_gold"] = self.state.player.gold
        result["gold"] = self.state.player.gold
        result["battery"] = self.state.player.battery
        result["valid_evidence_count"] = self._valid_evidence_count()
        result["recorded_cards_count"] = self._recorded_cards_count()
        result["recorded_cards"] = self._serialize_recorded_cards()
        result["coworkers"] = self.manager.get_player_coworkers()
        result["scout_available_rooms"] = self._get_scout_available_rooms()
        result["scout_result"] = await self._consume_pending_scout_result()
        self._finalize_hour_settlement_for_result(result)
        self._current_event_context = {}
        return result

    async def play_cards_with_ai_v2(self, emotion_id: str, action_id: str) -> dict:
        """
        新版出牌流程：
        1. 系统判定combo
        2. 查NPC反应档案获取tone和数值
        3. 系统直接结算数值（不由AI判断）
        4. AI基于预设tone生成Act 2对话

        返回: 和旧版play_cards_with_ai兼容的结果dict
        """
        from .event_system import EventSystem

        if self._current_event_card_mode == "solo_action":
            return await self.play_solo_action_with_ai(action_id)

        # 获取卡牌信息
        emotion_card = None
        for card in EMOTION_CARDS:
            if card.id == emotion_id:
                emotion_card = card
                break
        action_card = None
        for card in ACTION_CARDS:
            if card.id == action_id:
                action_card = card
                break
        if not emotion_card or not action_card:
            return {"error": "无效的卡牌ID"}

        # 5档combo判定
        combo_type = EventSystem.classify_combo(emotion_id, action_id)

        # 获取骨架事件数据
        skeleton_event = getattr(self, "_current_skeleton_event", None)
        if skeleton_event is None:
            # 旧模板事件或异常上下文：降级到本地结算，避免递归调用。
            return self.play_cards(emotion_id, action_id)

        primary_npc = skeleton_event.get("primary_npc")
        event_context = dict(self._current_event_context or {})
        room_case_id = int(self._active_front_case_id or event_context.get("room_case_id", 0) or 0)
        room_case_ctx = dict(self._active_front_case_ctx or event_context.get("room_case_ctx", {}) or {})
        is_pua_event = bool(skeleton_event) and (
            skeleton_event.get("room", "") == "pua"
        )

        # 查NPC反应档案，获取tone和数值
        primary_id = primary_npc["id"] if primary_npc else ""
        reactions = EventSystem.resolve_npc_reactions(combo_type, primary_id)

        room_name = EvidenceConverter.ROOM_NAMES.get(self.state.player.current_room, "未知")
        event_summary = str(skeleton_event.get("memory_summary_override", "")).strip()
        if not event_summary:
            event_summary = MemorySystem.generate_event_summary(
                emotion_card.name, action_card.name, combo_type, room_name
            )
        self._today_events_summary.append(event_summary)
        self._set_hour_settlement_context(
            is_blackmail=False,
            participant_npc_ids=[str(x) for x in event_context.get("participant_npc_ids", []) if str(x)],
        )

        # === 调用AI生成Act 2 ===
        current_task = self.state.player.selected_tasks[
            self.state.player.current_task_index
        ]
        npc_infos = getattr(self, "_last_npc_infos", [])
        act1_text = getattr(self, "_last_act1_text", "")
        subject_npc_name = self._npc_display_name(primary_id, primary_id) if primary_id else ""

        # 证据触发判定：本次事件是证据任务，且玩家选中的情绪卡或行动卡之一被标记。
        is_evidence_task = bool(skeleton_event.get("is_evidence_task", False))
        evidence_triggered = False
        if is_evidence_task:
            drawn_emotions = skeleton_event.get("drawn_emotions", []) or []
            drawn_actions = skeleton_event.get("drawn_actions", []) or []
            picked_emotion = next(
                (c for c in drawn_emotions if c.get("id") == emotion_id), None
            )
            picked_action = next(
                (c for c in drawn_actions if c.get("id") == action_id), None
            )
            evidence_triggered = bool(
                (picked_emotion and picked_emotion.get("evidence_marked"))
                or (picked_action and picked_action.get("evidence_marked"))
            )
        evidence_hint_for_act2 = (
            str(skeleton_event.get("evidence_hint", "") or "").strip()
            if (is_evidence_task and evidence_triggered) else ""
        )

        self._last_record_card_context = {
            "subject_npc_id": str(primary_id or ""),
            "subject_npc_name": subject_npc_name,
            "summary_text": str(event_summary)[:100],
            "is_evidence": bool(current_task.evidence_tag is not None),
            "evidence_triggered": evidence_triggered,
            "use_ai_summary": bool(primary_id),
            "room_name": room_name,
            "task_name": str(current_task.name),
            "player_name": self.state.player.name,
            "act1_text": act1_text,
        }

        # 给reactions附上NPC名字（AI需要名字不需要ID）
        for npc_info in npc_infos:
            if npc_info.get("id") == primary_id:
                reactions["primary"]["name"] = npc_info["name"]

        # ===== 协商决策器(Batch 6 修订): 先判定是否走协商 Act2 =====
        _accident_meta = dict((event_context or {}).get("accident_meta", {}) or {})
        _act1_text_for_nego = str(act1_text or "")
        _task_text_for_nego = str(current_task.name) if current_task else ""

        negotiation_payload: dict | None = None
        if not is_pua_event:
            try:
                negotiation_payload = await self._check_post_act2_negotiation(
                    primary_npc_id=primary_id,
                    accident_meta=_accident_meta,
                    act1_text=_act1_text_for_nego,
                    room_name=room_name,
                    task_text=_task_text_for_nego,
                )
            except Exception as e:
                self._work_logger.warning(f"[NEGOTIATION] decision error: {e}")
                negotiation_payload = None

        # 如果决策器返回了 payload,Act2 文本就是 AI 返回的 story,跳过 generate_act2
        if negotiation_payload is not None:
            act2_text = str(negotiation_payload.get("story_text", "")).strip()
            self._last_act1_text = _act1_text_for_nego
            self._work_logger.info(
                "[NEGOTIATION] act2 replaced by negotiation: type=%s npc=%s",
                negotiation_payload.get("type"),
                negotiation_payload.get("npc_id"),
            )
            ai_result = {
                "success": True,
                "act2_text": act2_text,
                "narrator": act2_text,
                "dialogues": {},
                "impression": str(negotiation_payload.get("impression", "")).strip(),
                "memory_text": str(negotiation_payload.get("memory_text", "")).strip(),
                "raw_response": "",
            }
        else:
            if is_pua_event:
                boss_thought = str(reactions.get("primary", {}).get("thought", "")).strip()
                ai_result = await AIService.generate_pua_player_act2(
                    act1_text=act1_text,
                    emotion_card_name=emotion_card.name,
                    emotion_card_tone=emotion_card.tone,
                    action_card_name=action_card.name,
                    action_card_effect=action_card.effect,
                    combo_type=combo_type,
                    boss_thought=boss_thought,
                    player_name=self.state.player.name,
                )
            else:
                # ===== 走原 generate_act2 路径(完全不动) =====
                ai_result = await AIService.generate_act2(
                    npc_infos=npc_infos,
                    act1_text=act1_text,
                    room_name=room_name,
                    task_text=str(current_task.name),
                    emotion_card_name=emotion_card.name,
                    emotion_card_tone=emotion_card.tone,
                    action_card_name=action_card.name,
                    action_card_effect=action_card.effect,
                    combo_type=combo_type,
                    npc_reactions=reactions,
                    player_name=self.state.player.name,
                    is_solo=(len(npc_infos) == 0),
                    evidence_hint=evidence_hint_for_act2,
                )
        memory_text = str(ai_result.get("memory_text", "")).strip()
        impression_text = str(ai_result.get("impression", "")).strip()
        fallback_impression = str(reactions.get("primary", {}).get("thought", "")).strip()
        if not memory_text:
            memory_text = impression_text
        if not impression_text:
            impression_text = fallback_impression
        if not impression_text:
            impression_text = f"在{room_name}里看到{self.state.player.name}的表现，暂时看不透。"
        if not memory_text:
            memory_text = f"在{room_name}里和{self.state.player.name}共事了一阵，他的做法让我有点在意。"
        ai_result["memory_text"] = memory_text
        ai_result["impression"] = impression_text
        self._last_record_card_context["act2_text"] = str(ai_result.get("act2_text", ""))
        AILogger.log_call(
            call_type="ACT2_IMPRESSION",
            context={"primary": primary_id, "room": room_name},
            system_prompt="",
            user_prompt="",
            raw_reply=str(ai_result.get("raw_response", ""))[:200],
            final_output=f"{memory_text} | {impression_text}",
            status="success",
            elapsed_ms=0,
        )

        if primary_id and (memory_text or impression_text):
            if self.memory:
                self.memory.add_impression(
                    observer_id=primary_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=memory_text,
                )
                self._log_witness_event(
                    source="act2_primary_impression",
                    observer_id=primary_id,
                    target_id="player",
                    room_key=self.state.player.current_room.value,
                    text=memory_text,
                    extra={"case_id": room_case_id, "impression": impression_text},
                )
            aff_delta = int(reactions["primary"].get("affinity_delta", 0))
            sus_delta = int(reactions["primary"].get("suspicion_delta", 0))
            if primary_id != "boss":
                self.manager.modify_affinity(primary_id, "player", aff_delta)
                self.manager.modify_suspicion(primary_id, "player", sus_delta)
                self.manager.append_relationship_reason(primary_id, "player", impression_text)
                aff_after = self.manager.get_affinity(primary_id, "player")
                sus_after = self.manager.get_suspicion(primary_id, "player")
            else:
                # 经理分支：仅维护对玩家的怀疑，不维护好感（PUA/审讯语义）。
                self.manager.modify_suspicion("boss", "player", sus_delta)
                self.manager.append_relationship_reason("boss", "player", impression_text)
                aff_after = "n/a"
                sus_after = self.manager.get_suspicion("boss", "player")
            AILogger.log_call(
                call_type="SETTLEMENT",
                context={
                    "combo": combo_type,
                    "primary": primary_id,
                    "affinity_delta": aff_delta,
                    "suspicion_delta": sus_delta,
                    "affinity_after": aff_after,
                    "suspicion_after": sus_after,
                    "memory_text": memory_text,
                    "impression": impression_text,
                },
                system_prompt="",
                user_prompt="",
                raw_reply=str(reactions["primary"].get("thought", "")),
                final_output="applied_with_impression",
                status="success",
                elapsed_ms=0,
            )

        if room_case_id == 3:
            npc_ids = list(room_case_ctx.get("npc_ids", []) or [])
            witness_id = str(npc_ids[0]).strip() if npc_ids else ""
            if witness_id and self.memory:
                npc_task = self._current_task_for_npc(witness_id)
                task_name = str(getattr(npc_task, "name", "")).strip() or "忙自己的活"
                witness_text = (
                    f"在{room_name}，{self.state.player.name}在旁边{task_name}，没有直接交流。"
                )
                self.memory.add_impression(
                    observer_id=witness_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=witness_text,
                )
                self.manager.append_relationship_reason(witness_id, "player", "看到了对方在旁边做事，但没有交流。")

        # PUA事件的额外文案兜底（优先使用手写库）
        if is_pua_event and not ai_result.get("success", True):
            pua_segments = DataLoader().pick_pua_segments("player") or {}
            pua_text = str(pua_segments.get("ending_text", "")).strip()
            if not pua_text:
                pua_text = DataLoader().get_fallback(
                    "f07_pua_act2",
                    combo=combo_type,
                    default="经理盯着你看了很久，最后挥挥触手让你离开了会议室。",
                )
            ai_result["success"] = True
            ai_result["act2_text"] = pua_text
            ai_result["dialogues"] = {self._npc_display_name("boss", "经理"): pua_text}
            ai_result["narrator"] = ""

        # 清空手牌
        self.state.player.hand_emotions = []
        self.state.player.hand_actions = []
        self._current_event_card_mode = ""

        # 清除骨架缓存
        self._current_skeleton_event = None
        self._current_event_context = {}

        # 构建返回数据（兼容旧格式）
        is_evidence = current_task.evidence_tag is not None

        result = {
            "combination_type": combo_type,
            "emotion_name": emotion_card.name,
            "action_name": action_card.name,
            "result_text": ai_result.get("narrator", ""),
            "dialogues": ai_result.get("dialogues", {}),
            "narrator": ai_result.get("narrator", ""),
            "impression": ai_result.get("impression", ""),
            "reactions": {},  # 不再由AI判断，此字段留空
            "npc_name_id_map": self._npc_name_id_map_for_result(),
            "affinity_delta": 0,  # 兼容旧格式
            "suspicion_delta": 0,
            "gold_delta": 0,
            "can_record": True,
            "is_evidence_task": is_evidence,
            "current_evidence_tag": current_task.evidence_tag,
        }

        # 任务奖励
        result.update(self._apply_task_reward(current_task))

        # Act 2结算完成后，先落地同房旁观/NPC-NPC互动记忆，再开放记录卡等道具操作。
        self._finalize_hour_settlement_for_result(result)

        # 记录卡信息
        result["can_use_record_card"] = self._record_card_available_for_event()
        result["blank_cards_count"] = sum(
            1 for rc in self.state.player.record_cards if rc.status.value == "blank"
        )
        result["blame_cards_count"] = self.state.player.items.get("blame_card", 0)
        result["blame_used_today"] = self.state.daily.blame_card_used
        result["player_gold"] = self.state.player.gold
        result["gold"] = self.state.player.gold
        result["battery"] = self.state.player.battery
        result["valid_evidence_count"] = self._valid_evidence_count()
        result["recorded_cards_count"] = self._recorded_cards_count()
        result["recorded_cards"] = self._serialize_recorded_cards()
        coworkers = self.manager.get_player_coworkers()
        result["coworkers"] = coworkers
        result["scout_available_rooms"] = self._get_scout_available_rooms()
        result["scout_result"] = await self._consume_pending_scout_result()
        result["economy_snapshot"] = self._build_economy_snapshot()

        # ===== 协商系统(Batch 6 修订): 把 negotiation_payload 写入 result =====
        # negotiation_payload 是 Act2 之前由决策器生成的(见上方代码)
        if negotiation_payload is not None:
            result["negotiation"] = negotiation_payload
            self._pending_negotiation = {
                "negotiation": negotiation_payload,
                "accident_meta": _accident_meta,
                "primary_npc_id": primary_id,
                "current_day": int(self.state.current_day),
                "room_name": room_name,
            }
            self._work_logger.info(
                "[NEGOTIATION] payload attached to result: type=%s method=%s amount=%s",
                negotiation_payload.get("type"),
                negotiation_payload.get("offer", {}).get("method"),
                negotiation_payload.get("offer", {}).get("amount"),
            )
        else:
            self._pending_negotiation = None

        return result

    async def use_record_card(self, card_id: str, record_type: str = "evidence") -> dict:
        """
        事件结束后使用记录卡。

        参数:
            card_id: 空白记录卡ID
        """
        normalized_type = str(record_type or "").strip().lower()
        if normalized_type not in {"evidence", "blackmail"}:
            return {"success": False, "message": "record_type 仅支持 evidence 或 blackmail"}
        ctx = self._last_record_card_context or {}
        summary_text = str(ctx.get("summary_text", "") or "")
        use_ai_summary = bool(ctx.get("use_ai_summary", False))
        # 黑料记录保存原始客观内容，扭曲发生在传播阶段，不在记录阶段做AI改写。
        if use_ai_summary and normalized_type == "evidence":
            summary_text = await AIService.generate_record_card_summary(
                act1_text=str(ctx.get("act1_text", "") or ""),
                act2_text=str(ctx.get("act2_text", "") or ""),
                room_name=str(ctx.get("room_name", "") or ""),
                task_name=str(ctx.get("task_name", "") or ""),
                npc_name=str(ctx.get("subject_npc_name", "") or "某同事"),
                player_name=str(ctx.get("player_name", self.state.player.name) or self.state.player.name),
            )
            self._last_record_card_context["summary_text"] = summary_text
        return self.manager.use_record_card_on_event(
            card_id,
            record_type=normalized_type,
            subject_npc_id=str(ctx.get("subject_npc_id", "") or ""),
            subject_npc_name=str(ctx.get("subject_npc_name", "") or ""),
            summary_text=summary_text,
            is_evidence=bool(ctx.get("is_evidence", False)) if normalized_type == "evidence" else False,
            evidence_triggered=bool(ctx.get("evidence_triggered", True)),
        )

    def use_blame_card(self, blame_target_npc_id: str) -> dict:
        """
        使用嫁祸卡：将本次事件的负面影响转嫁给目标NPC。

        参数:
            blame_target_npc_id: 替罪羊NPC的ID

        返回:
            {"success": bool, "message": str}
        """
        player = self.state.player

        # 检查是否有嫁祸卡
        if player.items.get("blame_card", 0) <= 0:
            return {"success": False, "message": "你没有嫁祸卡"}

        # 检查今日是否已使用
        if self.state.daily.blame_card_used:
            return {"success": False, "message": "今天已经甩过一次锅了，再甩就穿帮了"}

        # 检查目标是否合法
        if blame_target_npc_id not in self.state.npcs:
            return {"success": False, "message": "目标不存在"}
        if not self.state.npcs[blame_target_npc_id].alive:
            return {"success": False, "message": "不能甩锅给已经出局的人"}

        target_npc = self.state.npcs[blame_target_npc_id]

        # 消耗嫁祸卡
        player.items["blame_card"] -= 1
        self.state.daily.blame_card_used = True

        # 核心逻辑：撤销玩家身上的负面影响，转嫁给目标NPC
        # 获取同房间所有NPC
        coworkers = self.manager.get_player_coworkers()
        for npc_id in coworkers["npc_ids"]:
            # 降低NPC对玩家的怀疑（刚才的事不是玩家干的）
            self.manager.modify_suspicion(npc_id, "player", -8)
            # 提升NPC对替罪羊的怀疑
            self.manager.modify_suspicion(npc_id, blame_target_npc_id, 10)
            # 降低NPC对替罪羊的好感
            self.manager.modify_affinity(npc_id, blame_target_npc_id, -5)

        # 经理在场也受影响
        if coworkers["boss_present"]:
            self.manager.modify_suspicion("boss", "player", -5)
            self.manager.modify_suspicion("boss", blame_target_npc_id, 8)

        # 写入记忆
        if self.memory:
            room_name = EvidenceConverter.ROOM_NAMES.get(
                self.state.player.current_room, "未知"
            )
            summary = f"玩家把黑锅甩给了{target_npc.name}，所有人都以为是{target_npc.name}干的"
            witness_ids = list(coworkers["npc_ids"])
            if coworkers["boss_present"]:
                witness_ids.append("boss")
            for witness_id in witness_ids:
                self.memory.add_impression(
                    observer_id=witness_id,
                    target_id=blame_target_npc_id,
                    day=self.state.current_day,
                    impression_text=f"在{room_name}，{summary}",
                )

        return {
            "success": True,
            "message": f"你熟练地把锅甩到了{target_npc.name}头上。所有人的目光都转向了{target_npc.name}——{target_npc.name}一脸懵逼。",
            "target_name": target_npc.name,
            "blame_cards_remaining": player.items.get("blame_card", 0),
        }

    def buy_item(self, item_key: str) -> dict:
        """
        商城购买道具。

        参数:
            item_key: "battery" / "record_card" / "blame_card"
        """
        from .constants import SHOP_ITEMS
        player = self.state.player

        if item_key not in SHOP_ITEMS:
            return {"success": False, "message": "商品不存在"}

        item = SHOP_ITEMS[item_key]
        price = item["price"]

        if player.gold < price:
            return {
                "success": False,
                "message": f"金币不足！需要{price}，你只有{player.gold}",
            }

        # 扣钱
        self.manager.modify_gold(-price)

        # 发货
        if item_key == "battery":
            self.manager.modify_battery(100)  # 充满电
            effect_msg = "电池已充满（100%）"
        elif item_key == "record_card":
            self.manager.add_record_card()
            effect_msg = "获得1张空白记录卡"
        elif item_key == "blame_card":
            player.items["blame_card"] = player.items.get("blame_card", 0) + 1
            effect_msg = f"获得1张嫁祸卡（当前{player.items['blame_card']}张）"
        else:
            effect_msg = "???"

        return {
            "success": True,
            "message": f"购买成功！{effect_msg}",
            "gold_remaining": player.gold,
            "player_gold": player.gold,
            "gold": player.gold,
            "item_key": item_key,
        }

    def get_shop_data(self) -> dict:
        """获取商城数据供前端显示"""
        from .constants import SHOP_ITEMS
        player = self.state.player

        items = []
        for key, item in SHOP_ITEMS.items():
            items.append({
                "key": key,
                "name": item["name"],
                "price": item["price"],
                "description": item["description"],
                "affordable": player.gold >= item["price"],
            })

        return {
            "gold": player.gold,
            "items": items,
            "battery": player.battery,
            "blank_cards": sum(1 for rc in player.record_cards if rc.status.value == "blank"),
            "blame_cards": player.items.get("blame_card", 0),
        }

    async def _consume_pending_scout_result(self) -> dict | None:
        """
        取出小助理结果。

        如果后台侦察还没写入缓存，Act 2结算会在这里等它收尾，避免结果在本小时返回后才生成却没有
        WebSocket消息可送达前端。
        """
        if self._pending_scout_result is None and self._pending_scout_task is not None:
            try:
                # 侦察结果通常会在 Act 2 前后返回，给稍长等待窗口避免“本小时丢结果”。
                await asyncio.wait_for(asyncio.shield(self._pending_scout_task), timeout=25)
            except asyncio.TimeoutError:
                self._work_logger.warning("[SCOUT] pending scout did not finish before Act 2 result")
            except Exception as e:
                self._pending_scout_result = {
                    "success": False,
                    "message": f"小助理回传失败。（{str(e)[:50]}）",
                }

        if self._pending_scout_task is not None and self._pending_scout_task.done():
            self._pending_scout_task = None

        if self._pending_scout_result is None:
            return None
        result = self._pending_scout_result
        self._pending_scout_result = None
        return result

    async def dispatch_scout(self, target_room_value: str, target_npc_id: str = "") -> dict:
        """派出小助理（异步，不等待结果）。"""
        from .constants import SCOUT_BATTERY_COST
        from .room_system import RoomSystem

        player = self.state.player

        try:
            target_room = Room(target_room_value)
        except ValueError:
            return {"success": False, "message": "无效的房间"}

        if target_room == player.current_room:
            return {"success": False, "message": "不能侦察自己所在的房间！"}

        room_info = RoomSystem.get_room_occupants(
            player, self.state.npcs, self.state.boss, target_room
        )
        room_npc_ids = [str(x).strip() for x in room_info.get("npcs", []) if str(x).strip()]
        if not room_npc_ids:
            return {"success": False, "message": "房间里没有人，不值得侦察"}

        chosen_target_id = str(target_npc_id or "").strip()
        if not chosen_target_id:
            if len(room_npc_ids) == 1:
                chosen_target_id = room_npc_ids[0]
            else:
                return {"success": False, "message": "请选择要盯梢的目标"}
        elif chosen_target_id not in room_npc_ids:
            return {"success": False, "message": "目标NPC不在该房间"}

        if player.battery < SCOUT_BATTERY_COST:
            return {
                "success": False,
                "message": f"电量不足！需要{SCOUT_BATTERY_COST}%，当前{player.battery}%",
            }

        self.manager.modify_battery(-SCOUT_BATTERY_COST)
        self._pending_scout_result = None
        if self._pending_scout_task and not self._pending_scout_task.done():
            self._pending_scout_task.cancel()
        self._pending_scout_task = asyncio.create_task(
            self._generate_scout_async(target_room_value, chosen_target_id)
        )

        return {
            "success": True,
            "message": "小助理已出发！它会在你处理完当前事件后带回消息。",
            "battery_remaining": player.battery,
            "dispatched": True,
            "target_npc_id": chosen_target_id,
        }

    async def _generate_scout_async(self, target_room_value: str, target_npc_id: str) -> dict:
        """后台生成侦察结果并缓存。"""
        try:
            result = await self.scout_room(
                target_room_value,
                target_npc_id=target_npc_id,
                consume_battery=False,
            )
            self._pending_scout_result = result
            return result
        except Exception as e:
            self._pending_scout_result = {
                "success": False,
                "message": f"小助理在通风管道里迷路了。（{str(e)[:50]}）",
            }
            return self._pending_scout_result

    async def scout_room(self, target_room_value: str, target_npc_id: str = "", consume_battery: bool = True) -> dict:
        """
        派小助理侦察目标房间。

        参数:
            target_room_value: 目标房间的value（如 "warehouse"）

        返回:
            {
                "success": bool,
                "message": str,
                "accident": bool,          # 是否遭遇意外
                "accident_text": str,      # 意外描述
                "room_name": str,          # 目标房间中文名
                "npcs_in_room": list,      # 房间里的NPC名字
                "observation": str,        # AI生成的观察描述
                "has_evidence": bool,      # 是否发现证据线索
                "evidence_tag": str,       # 证据标签
                "can_record": bool,        # 是否可以记录
                "battery_remaining": int,
            }
        """
        from .constants import (
            SCOUT_ACCIDENT_RATE_BOSS,
            SCOUT_ACCIDENT_RATE_NORMAL,
            SCOUT_BATTERY_COST,
        )
        from .room_system import RoomSystem
        import random

        player = self.state.player

        # 检查目标房间
        try:
            target_room = Room(target_room_value)
        except ValueError:
            return {"success": False, "message": "无效的房间"}

        if target_room == player.current_room:
            return {"success": False, "message": "不能侦察自己所在的房间！"}

        # 消耗电量
        if consume_battery:
            self.manager.modify_battery(-SCOUT_BATTERY_COST)

        # 获取目标房间人员
        room_info = RoomSystem.get_room_occupants(
            player, self.state.npcs, self.state.boss, target_room
        )
        npc_names = [d["name"] for d in room_info["npc_details"]]
        npc_ids = room_info["npcs"]
        boss_here = room_info["boss_present"]
        if not npc_ids and not boss_here:
            idle_text = DataLoader().get_room_idle(target_room_value)
            return {
                "success": True,
                "accident": False,
                "accident_text": "",
                "room_name": EvidenceConverter.ROOM_NAMES.get(target_room, target_room_value),
                "npcs_in_room": [],
                "observation": idle_text or "房间里很安静，暂时没有值得记录的信息。",
                "has_evidence": False,
                "evidence_tag": None,
                "subject_npc_id": "",
                "subject_npc_name": "",
                "can_record": False,
                "battery_remaining": player.battery,
                "message": "侦察完成。",
                "boss_in_room": False,
            }

        npc_id_name_map = {
            str(detail.get("id", "")).strip(): str(detail.get("name", "")).strip()
            for detail in room_info.get("npc_details", [])
            if str(detail.get("id", "")).strip()
        }

        chosen_target_id = str(target_npc_id or "").strip()
        if chosen_target_id == "boss" and not boss_here:
            return {"success": False, "message": "经理不在该房间"}
        if not chosen_target_id:
            if boss_here and target_room == Room.BOSS_OFFICE:
                chosen_target_id = "boss"
            elif len(npc_ids) == 1:
                chosen_target_id = str(npc_ids[0]).strip()
            else:
                return {"success": False, "message": "请选择要盯梢的目标"}
        if chosen_target_id != "boss" and chosen_target_id not in npc_ids:
            return {"success": False, "message": "目标NPC不在该房间"}
        target_npc_name = self._npc_display_name("boss", "经理") if chosen_target_id == "boss" else npc_id_name_map.get(
            chosen_target_id,
            self._npc_display_name(chosen_target_id, chosen_target_id),
        )

        # 检查电量（仅在即将实际执行侦察时扣前校验）
        if consume_battery and player.battery < SCOUT_BATTERY_COST:
            return {
                "success": False,
                "message": f"电量不足！需要{SCOUT_BATTERY_COST}%，当前{player.battery}%",
            }

        # 判断意外概率
        if boss_here:
            accident_rate = SCOUT_ACCIDENT_RATE_BOSS
        else:
            accident_rate = SCOUT_ACCIDENT_RATE_NORMAL

        accident = random.random() < accident_rate

        room_name = EvidenceConverter.ROOM_NAMES.get(target_room, target_room_value)

        if accident:
            # 遭遇意外
            accident_texts = [
                "小助理在通风管道里撞到了墙，发出了巨大的声响！所有人都朝天花板看去。",
                "小助理的摄像头被蜘蛛网糊住了，什么都看不清。然后它撞翻了一个杯子。",
                "经理的八条触手中有一条突然伸进了通风口，差点抓住你的小助理！",
                "小助理在爬行途中踩到了老鼠夹。'嘭'的一声响彻了整层楼。",
                "有人在通风口里喷了杀虫剂，小助理被熏得信号中断了。",
            ]
            accident_text = random.choice(accident_texts)

            # 意外后果：在场NPC对玩家怀疑度上升
            for npc_id in npc_ids:
                self.manager.modify_suspicion(npc_id, "player", 8)
            if boss_here:
                self.manager.modify_suspicion("boss", "player", 12)

            return {
                "success": True,
                "accident": True,
                "accident_text": accident_text,
                "room_name": room_name,
                "npcs_in_room": npc_names,
                "observation": "",
                "has_evidence": False,
                "evidence_tag": None,
                "subject_npc_id": chosen_target_id,
                "subject_npc_name": target_npc_name,
                "can_record": False,
                "battery_remaining": player.battery,
                "message": "侦察失败！小助理遭遇了意外。",
                "is_manager_pua_related": False,
            }

        # 侦察成功：检查是否有证据
        has_evidence = False
        evidence_tag = None
        evidence_category = ""
        evidence_keywords = []
        evidence_hint = ""
        target_task_name = ""
        target_public_impression = str(DataLoader().get_npc_field(chosen_target_id, "public_impression", "")).strip()

        target_npc = self.state.npcs.get(chosen_target_id)
        if chosen_target_id != "boss" and target_npc and target_npc.current_task_index < len(target_npc.selected_tasks):
            task = target_npc.selected_tasks[target_npc.current_task_index]
            target_task_name = str(getattr(task, "name", "")).strip()
            if task.evidence_tag and task.room == target_room:
                has_evidence = True
                evidence_tag = task.evidence_tag
                if task.evidence_type:
                    evidence_category = EvidenceConverter.TYPE_NAMES.get(task.evidence_type, "")
                    evidence_keywords = EvidenceConverter.TYPE_KEYWORDS.get(task.evidence_type, [])
                evidence_hint = str(getattr(task, "evidence_hint", "")).strip()

        active_pua_full_text = self._get_active_pua_full_text_for_scout(target_room_value, chosen_target_id)
        is_manager_pua_related = bool(active_pua_full_text) or self._is_cached_room_manager_pua(target_room_value, chosen_target_id)
        observation = active_pua_full_text if active_pua_full_text else self._get_cached_room_scout_text(target_room_value, chosen_target_id)
        if not observation:
            # AI生成观察描述（仅在本小时缓存没有命中时兜底）
            if chosen_target_id == "boss" and target_room == Room.BOSS_OFFICE:
                observation = DataLoader().get_room_idle("boss_office") or "经理办公室里光线昏暗，文件堆得像一堵墙。"
            else:
                observation = await self._generate_scout_observation(
                    room_name=room_name,
                    target_npc_name=target_npc_name,
                    target_npc_public_impression=target_public_impression,
                    target_task_name=target_task_name,
                    has_evidence=has_evidence,
                    evidence_category=evidence_category,
                    evidence_keywords=evidence_keywords,
                    evidence_hint=evidence_hint,
                )

        has_blank = any(rc.status.value == "blank" for rc in player.record_cards)
        self._last_scout_record_context = {
            "subject_npc_id": chosen_target_id,
            "subject_npc_name": target_npc_name,
            "summary_text": str(observation or "").strip(),
            "evidence_tag": str(evidence_tag or ""),
        }

        return {
            "success": True,
            "accident": False,
            "accident_text": "",
            "room_name": room_name,
            "npcs_in_room": npc_names,
            "observation": observation,
            "has_evidence": has_evidence,
            "evidence_tag": evidence_tag,
            "subject_npc_id": chosen_target_id,
            "subject_npc_name": target_npc_name,
            "can_record": has_blank and str(observation or "").strip() != "",
            "battery_remaining": player.battery,
            "message": "侦察成功！",
            "boss_in_room": boss_here,
            "is_manager_pua_related": is_manager_pua_related,
        }

    async def _generate_boss_pua_scout_dialogue(self, target_npc_id: str) -> str:
        """玩家侦察到经理PUA NPC时的专用对话生成。"""
        npc_name = self._npc_display_name(target_npc_id, target_npc_id)
        boss_name = self._npc_display_name("boss", "经理")
        boss_personality = self._npc_personality("boss", "高压而多疑")
        npc_personality = self._npc_personality(target_npc_id, "谨慎保守")
        prompt = (
            f"你正在写一段监控里偷看到的职场对话。\n"
            f"场景：{boss_name}正在对{npc_name}进行职场PUA，语气压迫且荒诞。\n"
            f"{boss_name}性格：{boss_personality}\n"
            f"{npc_name}性格：{npc_personality}\n"
            "要求：\n"
            "1. 只输出3-5句中文对话/旁白。\n"
            "2. 每句单独一行，允许“人物名：台词”格式。\n"
            "3. 要体现经理在套话、试探可疑点。\n"
            "4. 风格荒诞黑色幽默，但不要出现额外人物。\n"
        )
        try:
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.85,
                max_tokens=260,
                timeout=8,
            )
            text = str(response.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception:
            pass
        return (
            f"{boss_name}把文件拍在桌上：“解释一下你今天这几个动作，为什么每次都刚好绕开关键节点？”\n"
            f"{npc_name}喉结滚了一下：“我只是按流程走……”\n"
            f"{boss_name}触手轻轻敲着桌沿：“流程？我看你更像在给自己留后路。”"
        )

    async def _generate_scout_observation(
        self,
        *,
        room_name: str,
        target_npc_name: str,
        target_npc_public_impression: str,
        target_task_name: str,
        has_evidence: bool,
        evidence_category: str,
        evidence_keywords: list,
        evidence_hint: str = "",
    ) -> str:
        """AI生成侦察观察描述"""
        public_text = target_npc_public_impression or "平时看起来规矩又老实"
        task_text = target_task_name or "手头那份工作"
        evidence_block = ""
        if has_evidence:
            hint = str(evidence_hint or "").strip()
            if not hint and evidence_category:
                kw = "、".join(evidence_keywords[:2])
                hint = f"与「{evidence_category}」相关（关键词：{kw}）"
            if hint:
                evidence_block = f"\n6. 该任务涉及证据线索，请自然融入这条提示：{hint}"

        prompt = PromptRegistry.render(
            "scout_observe_prompt",
            room_name=room_name,
            target_npc_name=target_npc_name,
            public_text=public_text,
            task_text=task_text,
            evidence_block=evidence_block,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=300,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="SCOUT",
                context={
                    "room": room_name,
                    "target_npc": target_npc_name,
                    "task_name": task_text,
                    "has_evidence": has_evidence,
                },
                system_prompt="",
                user_prompt=prompt,
                raw_reply=raw,
                final_output=raw,
                status="success",
                elapsed_ms=_elapsed,
            )
            return raw
        except Exception as e:
            fallback = (
                f"小助理盯着{target_npc_name}在{room_name}里处理“{task_text}”。"
                f"TA手上动作看着挺熟练，但总有几秒会突然停住，像在偷偷改掉什么不该改的东西。"
            )
            AILogger.log_call(
                call_type="SCOUT",
                context={
                    "room": room_name,
                    "target_npc": target_npc_name,
                    "task_name": task_text,
                    "has_evidence": has_evidence,
                },
                system_prompt="",
                user_prompt=prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback,
                status="fallback",
                elapsed_ms=0,
            )
            return fallback

    def _apply_task_reward(self, task) -> dict:
        """
        结算任务本身奖励。
        说明：事件卡牌结算与任务奖励是两套系统，需分别结算。
        """
        reward_type = task.reward_type
        reward_value = int(getattr(task, "reward_value", 0) or 0)

        info = {
            "task_reward_type": reward_type.value if hasattr(reward_type, "value") else str(reward_type),
            "task_reward_value": reward_value,
        }

        if reward_type == RewardType.GOLD and reward_value > 0:
            self.manager.modify_gold(reward_value)
            info["task_reward_message"] = f"完成任务奖励：+{reward_value} 金币"
            info["gold_after_task_reward"] = self.state.player.gold
            return info

        # 非金币奖励先保留信息，数值影响后续可按需扩展
        info["task_reward_message"] = ""
        info["gold_after_task_reward"] = self.state.player.gold
        return info

    def record_scout_evidence(self, evidence_tag: str) -> dict:
        """用记录卡记录小助理带回的信息（有证据则记为有效证据，无证据则记普通记录）。

        已废弃：仅作"记录为证据"的快捷入口保留以便回滚。
        新逻辑请走 record_scout_evidence_v2()，支持 record_type 二选一。
        """
        ctx = dict(self._last_scout_record_context or {})
        subject_npc_id = str(ctx.get("subject_npc_id", "")).strip()
        subject_npc_name = str(ctx.get("subject_npc_name", "")).strip()
        summary_text = str(ctx.get("summary_text", "")).strip()
        tag = str(evidence_tag or ctx.get("evidence_tag", "") or "")

        for rc in self.state.player.record_cards:
            if rc.status.value == "blank":
                source = (
                    f"侦察记录-第{self.state.current_day}天"
                    if tag == ""
                    else f"侦察记录-第{self.state.current_day}天-{tag}"
                )
                result = self.manager.record_evidence(
                    rc.id,
                    tag,
                    source,
                    subject_npc_id=subject_npc_id,
                    subject_npc_name=subject_npc_name,
                    summary_text=summary_text,
                    is_evidence=tag.startswith("evidence_"),
                )
                if result:
                    remaining = sum(1 for c in self.state.player.record_cards if c.status.value == "blank")
                    return {
                        "success": True,
                        "message": "小助理把带回的信息记进了录音笔。",
                        "remaining_blank": remaining,
                        "evidence_count": len(self.state.evidence_collected),
                    }
        return {"success": False, "message": "没有空白记录卡了"}

    def record_scout_evidence_v2(self, evidence_tag: str, record_type: str = "evidence") -> dict:
        """
        用记录卡记录小助理带回的信息，支持「证据 / 黑料」二选一。

        参数:
            evidence_tag: 侦察命中的证据标签（前端可不传，自动取最近一次侦察上下文）
            record_type: "evidence" 或 "blackmail"
              - evidence：保留 evidence_tag，仅当 tag 以 "evidence_" 开头时计入有效证据
              - blackmail：丢弃 evidence_tag，作为可传播黑料卡（必须有 subject_npc_id）

        返回与旧 record_scout_evidence 兼容的结构，并多带 record_type 字段。
        """
        ctx = dict(self._last_scout_record_context or {})
        subject_npc_id = str(ctx.get("subject_npc_id", "")).strip()
        subject_npc_name = str(ctx.get("subject_npc_name", "")).strip()
        summary_text = str(ctx.get("summary_text", "")).strip()
        raw_tag = str(evidence_tag or ctx.get("evidence_tag", "") or "")

        normalized_type = str(record_type or "").strip().lower()
        if normalized_type not in {"evidence", "blackmail"}:
            normalized_type = "evidence"

        if normalized_type == "blackmail" and not subject_npc_id:
            return {"success": False, "message": "无法记录为黑料：没有可标记的目标NPC。"}

        tag_for_record = raw_tag if normalized_type == "evidence" else ""
        is_evidence = normalized_type == "evidence" and tag_for_record.startswith("evidence_")

        for rc in self.state.player.record_cards:
            if rc.status.value != "blank":
                continue
            if normalized_type == "blackmail":
                source = f"侦察黑料-第{self.state.current_day}天-{subject_npc_name or subject_npc_id}"
            elif tag_for_record == "":
                source = f"侦察记录-第{self.state.current_day}天"
            else:
                source = f"侦察记录-第{self.state.current_day}天-{tag_for_record}"

            result = self.manager.record_evidence(
                rc.id,
                tag_for_record,
                source,
                record_type=normalized_type,
                subject_npc_id=subject_npc_id,
                subject_npc_name=subject_npc_name,
                summary_text=summary_text,
                is_evidence=is_evidence,
            )
            if result:
                remaining = sum(1 for c in self.state.player.record_cards if c.status.value == "blank")
                if normalized_type == "blackmail":
                    msg = f"小助理把关于{subject_npc_name or subject_npc_id}的传闻标记成了黑料。"
                else:
                    msg = "小助理把带回的信息记进了录音笔。"
                return {
                    "success": True,
                    "message": msg,
                    "remaining_blank": remaining,
                    "evidence_count": len(self.state.evidence_collected),
                    "record_type": normalized_type,
                }
        return {"success": False, "message": "没有空白记录卡了"}

    async def use_card_as_blackmail(self, card_id: str, target_npc_id: str) -> dict:
        """
        使用已记录的记录卡威胁NPC（致命小黑历）。

        参数:
            card_id: 已记录的记录卡ID
            target_npc_id: 威胁目标NPC的ID

        返回:
            {
                "success": bool,
                "message": str,
                "dialogue": str,        # AI生成的NPC反应
                "effect": str,          # "scared"/"angry"/"neutral"
                "affinity_delta": int,
                "suspicion_delta": int,
            }
        """
        player = self.state.player

        # 找到记录卡
        target_card = None
        for rc in player.record_cards:
            if rc.id == card_id and rc.status.value == "recorded":
                target_card = rc
                break
        if not target_card:
            return {"success": False, "message": "找不到这张已记录的记录卡"}
        if str(getattr(target_card, "record_type", "")).strip().lower() != "blackmail":
            return {"success": False, "message": "证据卡不能用于传播黑料"}

        # 检查目标NPC
        if target_npc_id not in self.state.npcs:
            return {"success": False, "message": "目标不存在"}
        npc = self.state.npcs[target_npc_id]
        if not npc.alive:
            return {"success": False, "message": f"{npc.name}已经出局了"}

        # 消耗记录卡（从玩家手中移除，也从证据列表移除）
        player.record_cards.remove(target_card)
        if target_card in self.state.evidence_collected:
            self.state.evidence_collected.remove(target_card)

        # AI生成NPC反应
        npc_reaction = await self._generate_blackmail_reaction(
            npc, target_card.source_description
        )

        # 应用效果
        effect = npc_reaction.get("effect", "neutral")
        aff_delta = 0
        sus_delta = 0

        if effect == "scared":
            aff_delta = 5
            sus_delta = -15
        elif effect == "angry":
            aff_delta = -15
            sus_delta = 10
        else:
            aff_delta = 0
            sus_delta = -5

        self.manager.modify_affinity(target_npc_id, "player", aff_delta)
        self.manager.modify_suspicion(target_npc_id, "player", sus_delta)

        # 写入记忆
        if self.memory:
            self.memory.add_impression(
                observer_id=target_npc_id,
                target_id="player",
                day=self.state.current_day,
                impression_text=f"玩家用黑历史威胁了{npc.name}，内容是关于{target_card.source_description}",
            )

        return {
            "success": True,
            "message": f"你掏出录音笔，按下播放键，对准了{npc.name}……",
            "dialogue": npc_reaction.get("dialogue", ""),
            "effect": effect,
            "effect_text": {
                "scared": "😨 害怕了",
                "angry": "😡 被激怒了",
                "neutral": "😐 无动于衷",
            }.get(effect, ""),
            "affinity_delta": aff_delta,
            "suspicion_delta": sus_delta,
            "card_source": target_card.source_description,
        }

    async def _generate_blackmail_reaction(self, npc, evidence_source: str) -> dict:
        """AI生成NPC被威胁时的反应"""
        import random
        import re

        prompt = PromptRegistry.render(
            "blackmail_reaction_prompt",
            npc_name=npc.name,
            npc_personality=npc.personality,
            evidence_source=evidence_source,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=300,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()

            dialogue_match = re.search(r"<dialogue>(.*?)</dialogue>", raw, re.DOTALL)
            effect_match = re.search(r"<effect>(.*?)</effect>", raw)

            dialogue = dialogue_match.group(1).strip() if dialogue_match else raw[:100]
            dialogue = re.sub(r"</?dialogue>", "", dialogue).strip()
            effect = effect_match.group(1).strip() if effect_match else "neutral"
            if effect not in ("scared", "angry", "neutral"):
                effect = "neutral"
            _elapsed = AILogger.elapsed_since(_start)
            result = {"dialogue": dialogue, "effect": effect}
            AILogger.log_call(
                call_type="BLACKMAIL",
                context={"npc": npc.name},
                system_prompt="",
                user_prompt=prompt,
                raw_reply=raw,
                final_output=str(result),
                status="success",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            dl = DataLoader()
            row = dl.get_fallback_row(
                "f10_blackmail_reaction",
                npc_id=npc.id,
            )
            if not row:
                random_attitude = random.choice(["afraid", "angry", "ignore"])
                row = dl.get_fallback_row(
                    "f10_blackmail_reaction",
                    npc_id="default",
                    attitude=random_attitude,
                )
            attitude = str(row.get("attitude", "")).strip().lower()
            text = str(row.get("text", "")).strip()

            effect_map = {
                "afraid": "scared",
                "angry": "angry",
                "ignore": "neutral",
            }
            fallback_effect = effect_map.get(attitude, random.choice(["scared", "angry", "neutral"]))
            if not text:
                text = "（沉默）"
            result = {"dialogue": text, "effect": fallback_effect}
            AILogger.log_call(
                call_type="BLACKMAIL",
                context={"npc": npc.name},
                system_prompt="",
                user_prompt=prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=str(result),
                status="fallback",
                elapsed_ms=0,
            )
            return result

    async def _generate_blackmail_broadcast_story(
        self,
        target_npc_id: str,
        npc_name: str,
        card_payload: dict,
        co_present_names: list[str] | None = None,
    ) -> dict:
        """状况3：向唯一同房NPC传播黑料，生成Act1文本与记忆摘要。"""
        import re

        npc = self.state.npcs.get(target_npc_id)
        personality = npc.personality if npc else "谨慎"
        subject_npc_name = str(card_payload.get("subject_npc_name", "某同事")).strip() or "某同事"
        summary = str(card_payload.get("distorted_summary", "")).strip() or str(card_payload.get("summary_text", "")).strip() or str(card_payload.get("source", "一段旧录音")).strip()
        room_name = EvidenceConverter.ROOM_NAMES.get(self.state.player.current_room, "未知")
        player_name = self.state.player.name
        npc_identity = self.memory.get_identity(target_npc_id) if self.memory else "（未知身份）"
        npc_aim = self.memory.get_aim(target_npc_id) if self.memory else ""
        memory_rel_text = (
            self.memory.build_memory_and_relations_text(
                target_npc_id,
                self.state.relationships,
                self.state.npcs,
                player_name=self.state.player.name,
                alive_only=True,
            )
            if self.memory else ""
        )
        copresent_text = ""
        if co_present_names:
            cleaned = [str(x).strip() for x in co_present_names if str(x).strip()]
            if cleaned:
                copresent_text = f"同时在场的还有：{'、'.join(cleaned)}。"

        prompt = PromptRegistry.render(
            "blackmail_broadcast_story_prompt",
            npc_name=npc_name,
            npc_identity=npc_identity,
            npc_aim=npc_aim if npc_aim else "（暂无明确目标）",
            memory_rel_text=(
                memory_rel_text
                if memory_rel_text
                else f"{npc_name}的记忆与对其他同事的看法：\n（暂无）"
            ),
            current_day=self.state.current_day,
            player_name=player_name,
            copresent_text=copresent_text,
            subject_npc_name=subject_npc_name,
            summary=summary,
        )
        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.85,
                max_tokens=420,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            normalized = re.sub(r"<[^>]+>", "", raw).replace("\r\n", "\n").replace("\r", "\n").strip()
            lines = [ln.strip() for ln in normalized.split("\n") if ln.strip()]
            allowed = {"增加怀疑", "减少怀疑", "无感"}
            player_judgement = "无感"
            subject_judgement = "无感"
            subject_reaction_text = ""
            story_lines = list(lines)
            if story_lines and story_lines[0].startswith(f"对玩家（{player_name}）的反应："):
                value = story_lines[0].split("：", 1)[1].strip() if "：" in story_lines[0] else ""
                if value in allowed:
                    player_judgement = value
                story_lines = story_lines[1:]
            elif story_lines and story_lines[0] in allowed:
                player_judgement = story_lines[0]
                story_lines = story_lines[1:]
            if story_lines and story_lines[0].startswith(f"对黑料NPC（{subject_npc_name}）的反应："):
                value = story_lines[0].split("：", 1)[1].strip() if "：" in story_lines[0] else ""
                if value in allowed:
                    subject_judgement = value
                story_lines = story_lines[1:]
            elif story_lines and story_lines[0] in allowed:
                subject_judgement = story_lines[0]
                story_lines = story_lines[1:]
            if story_lines and story_lines[0].startswith("对此事的反应看法："):
                subject_reaction_text = story_lines[0].split("：", 1)[1].strip() if "：" in story_lines[0] else ""
                story_lines = story_lines[1:]
            story = "\n".join(story_lines).strip()
            if not story:
                story = f"你把关于{subject_npc_name}的黑料悄悄递给了{npc_name}，对方神色一变，低声说“这事别让别人先听见”。空气里多了一层互相提防的味道。"
            if not subject_reaction_text:
                subject_reaction_text = self._blackmail_subject_reaction_text(target_npc_id, subject_judgement)
            memory_summary = f"玩家向{npc_name}传播了关于{subject_npc_name}的黑料：{summary[:48]}"
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="BLACKMAIL_BROADCAST",
                context={
                    "target": npc_name,
                    "subject": subject_npc_name,
                    "player_judgement": player_judgement,
                    "subject_judgement": subject_judgement,
                    "subject_reaction_text": subject_reaction_text,
                },
                system_prompt="",
                user_prompt=prompt,
                raw_reply=raw,
                final_output=story,
                status="success",
                elapsed_ms=_elapsed,
            )
            return {
                "story": story,
                "memory_summary": memory_summary,
                "player_judgement": player_judgement,
                "subject_judgement": subject_judgement,
                "subject_reaction_text": subject_reaction_text,
            }
        except Exception as e:
            fallback_story = f"你压低声音，把关于{subject_npc_name}的旧事讲给了{npc_name}。{npc_name}没立刻表态，只是把这条消息记在心里，像在等一个更合适的时机。"
            memory_summary = f"玩家向{npc_name}传播了关于{subject_npc_name}的黑料：{summary[:48]}"
            fallback_reaction = self._blackmail_subject_reaction_text(target_npc_id, "无感")
            AILogger.log_call(
                call_type="BLACKMAIL_BROADCAST",
                context={
                    "target": npc_name,
                    "subject": subject_npc_name,
                    "player_judgement": "无感",
                    "subject_judgement": "无感",
                    "subject_reaction_text": fallback_reaction,
                },
                system_prompt="",
                user_prompt=prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback_story,
                status="fallback",
                elapsed_ms=0,
            )
            return {
                "story": fallback_story,
                "memory_summary": memory_summary,
                "player_judgement": "无感",
                "subject_judgement": "无感",
                "subject_reaction_text": fallback_reaction,
            }

    def _get_scout_available_rooms(self) -> list[str]:
        """返回可侦察房间：排除当前房间和无人房间。"""
        from .room_system import RoomSystem

        snapshot = RoomSystem.get_all_room_occupants(
            self.state.player, self.state.npcs, self.state.boss
        )
        current_room = self.state.player.current_room.value
        ordered_rooms = ["office", "meeting", "warehouse", "pantry", "reception", "boss_office"]

        available = []
        for room in ordered_rooms:
            if room == current_room:
                continue
            occupants = snapshot.get(room, {})
            npc_count = len(occupants.get("npc_details", []) or [])
            boss_present = bool(occupants.get("boss_present", False))
            if npc_count > 0 or boss_present:
                available.append(room)
        return available

    async def skip_record_card(self) -> dict:
        """
        事件结束后跳过记录卡，直接进入下一小时。
        """
        return await self.advance_to_next_hour()

    async def advance_to_next_hour(self) -> dict:
        """
        推进到下一个小时。

        返回:
            下一小时的状态：
            - 如果还有任务：返回新事件
            - 如果一天结束：返回投票阶段提示
        """
        settlement_payload: dict = {}
        self._finalize_hour_settlement_for_result(settlement_payload)
        anomaly_payload = self._maybe_trigger_case3_anomaly()
        self._active_front_case_id = 0
        self._active_front_case_ctx = {}
        self._apply_npc_hourly_income()

        hour_result = self.manager.advance_hour()

        if hour_result["day_ended"]:
            result = await self._enter_voting_phase()
            if settlement_payload.get("settlement_append_text"):
                result["settlement_append_text"] = settlement_payload["settlement_append_text"]
            if anomaly_payload.get("triggered"):
                result["anomaly_event_text"] = str(anomaly_payload.get("text", "")).strip()
                result["anomaly_subject_npc_id"] = str(anomaly_payload.get("subject_npc_id", "")).strip()
                result["anomaly_subject_npc_name"] = str(anomaly_payload.get("subject_npc_name", "")).strip()
                result["anomaly_card"] = dict(anomaly_payload.get("card", {}) or {})
            result["economy_snapshot"] = self._build_economy_snapshot()
            return result

        next_event = await self._dispatch_current_hour_rooms(generate_player_event=True)

        boss_alert = None
        boss_action = hour_result.get("boss_action", {})
        if boss_action.get("behavior") == "patrol":
            boss_alert = boss_action.get("alert_hint")

        pua_info = dict(self._pending_pua_interruption or {})
        self._pending_pua_interruption = None
        pua_event = next_event if (pua_info and pua_info.get("target_id") == "player") else None

        # 缓存事件描述供AI使用
        if next_event and not pua_event:
            self._last_event_description = next_event.get("description", "")
            self._last_event_prompt = next_event.get("prompt", "")

        result = {
            "phase": "working",
            "day": self.state.current_day,
            "hour": self.state.current_hour,
            "event": next_event if not pua_event else {},
            "player_gold": self.state.player.gold,
            "gold": self.state.player.gold,
            "player_battery": self.state.player.battery,
            "battery": self.state.player.battery,
            "positions": self.manager.get_all_positions(),
            "player_room": self.state.player.current_room.value,
            "coworkers": self.manager.get_player_coworkers(),
            "boss_alert": boss_alert,
            "pua_interruption": pua_info,
            "pua_event": pua_event,
            "social_energy_left": self.state.daily.social_energy_left,
            "player_blank_cards": sum(1 for rc in self.state.player.record_cards if rc.status.value == "blank"),
        }
        if self._pending_npc_pua_notification:
            result["npc_pua_notification"] = str(self._pending_npc_pua_notification)
            self._pending_npc_pua_notification = ""
        if settlement_payload.get("settlement_append_text"):
            result["settlement_append_text"] = settlement_payload["settlement_append_text"]
        if anomaly_payload.get("triggered"):
            result["anomaly_event_text"] = str(anomaly_payload.get("text", "")).strip()
            result["anomaly_subject_npc_id"] = str(anomaly_payload.get("subject_npc_id", "")).strip()
            result["anomaly_subject_npc_name"] = str(anomaly_payload.get("subject_npc_name", "")).strip()
            result["anomaly_card"] = dict(anomaly_payload.get("card", {}) or {})
        result["economy_snapshot"] = self._build_economy_snapshot()
        return result

    def _select_boss_execution_target(self) -> dict:
        """投票前检查经理是否直接处决（阈值80）。"""
        candidates = []
        player_sus = self._boss_suspicion_to("player")
        if player_sus >= 80:
            candidates.append({"target_id": "player", "target_name": self.state.player.name, "suspicion": player_sus})
        for npc_id, npc in self.state.npcs.items():
            if not npc.alive:
                continue
            sus = self._boss_suspicion_to(npc_id)
            if sus >= 80:
                candidates.append({"target_id": npc_id, "target_name": npc.name, "suspicion": sus})
        if not candidates:
            return {}
        candidates.sort(key=lambda x: (-int(x.get("suspicion", 0)), str(x.get("target_id", ""))))
        return candidates[0]

    def _apply_boss_execution_aftermath(self, executed_id: str) -> None:
        """经理独裁处决后的群体影响：NPC对经理好感-10；NPC间怀疑-5。"""
        alive_npc_ids = [nid for nid, npc in self.state.npcs.items() if npc.alive]
        for observer_id in alive_npc_ids:
            rels = self.state.relationships.get(observer_id, {})
            if "boss" in rels:
                self.manager.modify_affinity(observer_id, "boss", -10)
                self.manager.append_relationship_reason(observer_id, "boss", "经理今天绕过投票直接处决了同事，太专断了。")
            for target_id in alive_npc_ids:
                if target_id == observer_id:
                    continue
                if target_id in rels:
                    self.manager.modify_suspicion(observer_id, target_id, -5)

        if not self.memory:
            return
        executed_name = self.state.player.name if executed_id == "player" else self._npc_display_name(executed_id, executed_id)
        memory_text = f"经理今天直接处决了{executed_name}，没有经过投票。"
        for observer_id in alive_npc_ids:
            if observer_id == executed_id:
                continue
            self.memory.add_impression(
                observer_id=observer_id,
                target_id=executed_id,
                day=self.state.current_day,
                impression_text=memory_text,
            )

    async def _enter_voting_phase(self) -> dict:
        """
        进入投票阶段。
        """
        self.state.current_phase = GamePhase.VOTING

        execution_target = self._select_boss_execution_target()
        if execution_target:
            target_id = str(execution_target.get("target_id", "")).strip()
            target_name = str(execution_target.get("target_name", target_id)).strip() or target_id
            if target_id == "player":
                self.state.game_over = True
                self.state.game_result = "fail_boss_executed"
                game_over_info = self._build_game_over_response()
                outcome = (
                    "经理缓缓站起来，八条触手在空中展开。"
                    "“不用投了。”"
                    "他的声音很轻，但整个办公室都安静下来了。"
                    "他走到你面前：“我查过了，调查员先生。跟我来吧。”"
                    "你的卧底生涯到此结束。"
                )
                return {
                    "phase": "voting",
                    "day": self.state.current_day,
                    "message": "今天的投票取消了。",
                    "candidates": [],
                    "vote_cancelled_by_boss": True,
                    "game_over": True,
                    "game_result": "fail_boss_executed",
                    "outcome_text": outcome,
                    "evidence_collected": game_over_info.get("evidence_collected", []),
                    "evidence_types_count": game_over_info.get("evidence_types_count", 0),
                }

            self.manager.eliminate_npc(target_id)
            self._apply_boss_execution_aftermath(target_id)
            outcome = (
                f"经理站起来，所有触手同时指向{target_name}："
                f"“不用投了。{target_name}，跟我来。”"
                f"在所有人惊恐的目光中，{target_name}被拖出了办公室。今天的投票取消了。"
            )
            return {
                "phase": "voting",
                "day": self.state.current_day,
                "message": "今天的投票取消了。",
                "candidates": [],
                "vote_cancelled_by_boss": True,
                "game_over": False,
                "can_proceed_to_night": True,
                "outcome_text": outcome,
            }

        candidates = self.manager.get_vote_candidates_for_frontend()

        return {
            "phase": "voting",
            "day": self.state.current_day,
            "message": "一天的工作结束了。经理敲了敲桌子：“投票时间到！你们每人选一个最可疑的人，匿名投票。”",
            "candidates": candidates,
            "forced_vote_target_id": str(getattr(self.state.daily, "forced_vote_target_id", "") or ""),
        }

    def submit_vote(self, target_npc_id: str) -> dict:
        """
        玩家提交投票。

        参数:
            target_npc_id: 玩家投票的NPC ID

        返回:
            投票结果（含唱票详情和结局文案）
        """
        result = self.manager.execute_vote(target_npc_id)
        if "error" in result:
            return result

        if self.state.game_over:
            result["game_over"] = True
            result["game_result"] = self.state.game_result
            game_over_info = self._build_game_over_response()
            result["evidence_collected"] = game_over_info.get("evidence_collected", [])
            result["evidence_types_count"] = game_over_info.get("evidence_types_count", 0)
            return result

        result["game_over"] = False
        result["can_proceed_to_night"] = True
        return result

    async def submit_vote_v2(self, player_vote_target: str) -> dict:
        """
        新版投票：Agent推理 + 玩家手动投票。
        """
        player_vote_target = str(player_vote_target or "").strip()

        # ===== 强制投票校验(Batch 7) =====
        # 如果当天有 NPC 勒索成功并强制了投票目标,玩家必须投该目标
        forced_target = str(getattr(self.state.daily, "forced_vote_target_id", "") or "").strip()
        if forced_target and player_vote_target != forced_target:
            forced_name = self._npc_display_name(forced_target, forced_target)
            self._work_logger.warning(
                "[VOTE] forced_vote bypass attempt: forced=%s player_chose=%s",
                forced_target, player_vote_target,
            )
            return {
                "success": False,
                "error": "forced_vote_violation",
                "message": f"你被胁迫了,今晚必须投给{forced_name}。",
                "forced_vote_target_id": forced_target,
                "forced_vote_target_name": forced_name,
            }

        # 校验玩家投票
        is_valid, error = self.manager.validate_player_vote(player_vote_target)
        if not is_valid:
            return {"error": error}

        # 构建存活名单（不含经理，经理不作为可投目标）
        alive_names = [self.state.player.name]
        alive_target_ids = ["player"]
        for npc_id, npc in self.state.npcs.items():
            if npc.alive:
                alive_names.append(npc.name)
                alive_target_ids.append(npc_id)

        # 6个Agent并行投票（5同事+1经理）
        agent_votes = await AgentService.all_agents_vote(
            self.state.npcs, self.state.boss,
            self.state.current_day,
            self.state.relationships, self.memory,
            alive_names, self.state.player.name,
        )

        # 名字→ID映射
        name_to_id = {self.state.player.name: "player"}
        name_to_id.update(DataLoader().get_npc_name_to_id_map())
        for npc_id, npc in self.state.npcs.items():
            name_to_id[npc.name] = npc_id

        # 构建vote_record（兼容旧格式）
        vote_record = {"player": player_vote_target}
        vote_reasons = {}

        for agent_id, vote_data in agent_votes.items():
            target_name = vote_data.get("target_name", "")
            target_id = name_to_id.get(target_name, "")
            raw_target_id = target_id
            if not target_id:
                # 模糊匹配
                for name, nid in name_to_id.items():
                    if name in target_name or target_name in name:
                        target_id = nid
                        raw_target_id = target_id
                        break

            # NPC/经理不能投给自己
            if target_id == agent_id:
                target_id = ""

            # 仅允许投给玩家或存活NPC，经理不应成为可投目标
            if target_id not in alive_target_ids:
                candidates = [nid for nid in alive_target_ids if nid != agent_id]
                target_id = random.choice(candidates) if candidates else "player"

            vote_record[agent_id] = target_id
            default_reason = DataLoader().get_fallback(
                "f08_vote_reason",
                npc_id=agent_id,
                default="（沉默）",
            )
            reason = str(vote_data.get("reason", "")).strip()
            # 若最终投票目标与Agent原始目标不一致（被规则修正/兜底改票），统一回退默认理由。
            if not reason or raw_target_id != target_id:
                reason = default_reason
            vote_reasons[agent_id] = reason

        # 第1天保护
        from .vote_system import VoteSystem
        if self.state.current_day == 1:
            original_vote_record = dict(vote_record)
            vote_record = VoteSystem._apply_day1_protection(vote_record, alive_target_ids)
            # 若因新手保护发生改票，则理由改用该投票人默认理由，避免“票改了但理由还指向旧目标”。
            for voter_id, new_target_id in vote_record.items():
                if voter_id == "player":
                    continue
                old_target_id = original_vote_record.get(voter_id, "")
                if old_target_id == new_target_id:
                    continue
                vote_reasons[voter_id] = DataLoader().get_fallback(
                    "f08_vote_reason",
                    npc_id=voter_id,
                    default="（沉默）",
                )

        # 唱票
        tally = {}
        for _, target_id in vote_record.items():
            tally[target_id] = tally.get(target_id, 0) + 1
        for target_id, cnt in tally.items():
            tid = str(target_id or "").strip()
            if cnt <= 0:
                continue
            if tid in self.state.npcs:
                self._increase_fear(tid, 5 * int(cnt), "被投票")
            elif tid == "boss":
                self._increase_fear("boss", 5 * int(cnt), "被投票")

        highest_votes = max(tally.values()) if tally else 0
        top = [cid for cid, cnt in tally.items() if cnt == highest_votes]
        is_tie = len(top) > 1

        # 结算
        result = VoteSystem._build_result_from_record(
            vote_record, tally, self.state.npcs, self.state.boss, is_tie
        )
        result["vote_reasons"] = vote_reasons  # 新增：每人的投票理由

        # 将理由合并到唱票详情（前端可直接展示）
        reason_by_voter = {"player": "（你亲手投下了这一票）"}
        reason_by_voter.update(vote_reasons)
        for detail in result.get("vote_details", []):
            detail["reason"] = reason_by_voter.get(detail.get("voter_id", ""), "（沉默）")

        # 投票记忆回写：每个NPC记录“我投给了谁、为什么、最终结果”
        if self.memory:
            outcome_name = ""
            if result.get("is_tie"):
                outcome_name = "平票"
            else:
                outcome_target = str(result.get("target", "") or "").strip()
                if outcome_target == "player":
                    outcome_name = self.state.player.name
                elif outcome_target:
                    outcome_name = self._npc_display_name(outcome_target, "某人")
            for voter_id, target_id in vote_record.items():
                if voter_id == "player":
                    continue
                target = str(target_id or "").strip()
                if not target:
                    continue
                if target == "player":
                    target_name = self.state.player.name
                else:
                    target_name = self._npc_display_name(target, target)
                reason = str(vote_reasons.get(voter_id, "（沉默）") or "（沉默）").strip()
                if result.get("is_tie"):
                    memory_text = f"投票日：我投了{target_name}，因为{reason}。最终平票，没人被投出。"
                else:
                    final_name = outcome_name or "某人"
                    memory_text = f"投票日：我投了{target_name}，因为{reason}。最终{final_name}被投出局了。"
                self.memory.add_impression(
                    observer_id=voter_id,
                    target_id=target,
                    day=self.state.current_day,
                    impression_text=memory_text,
                )

        self.state.daily.vote_record = result["vote_record"]
        self.state.daily.vote_result = result["target"]
        # ===== 投票完成后清空胁迫(Batch 7) =====
        if forced_target:
            self.state.daily.forced_vote_target_id = ""
            self._work_logger.info("[VOTE] forced_vote consumed: %s", forced_target)
        self._apply_alliance_betrayal_penalty(vote_record, self._alliances_to_enforce)
        self._alliances_to_enforce = []
        result["contract_settlement"] = []
        result["blackmail_vote_binding"] = {
            "active": False,
            "fulfilled": True,
            "breach_penalty_applied": False,
        }

        # 处理出局与文案（保持与旧投票流程一致）
        if result["is_tie"]:
            result["outcome_text"] = (
                "票数持平！经理不耐烦地挥了挥触手：“今天算你们走运，滚回去睡觉！明天给我投出个结果来！”"
            )
        elif result.get("player_eliminated"):
            self.manager.eliminate_player()
            result["outcome_text"] = (
                "所有人的目光都聚焦在你身上。经理缓缓站起来，八条触手在空中舞动：“看来大家的眼睛是雪亮的。来吧，我们去会议室好好聊聊……”你的调查员生涯到此结束了。"
            )
        elif result.get("target"):
            self.manager.eliminate_npc(result["target"])
            target_name = result.get("target_name", "某人")
            result["outcome_text"] = (
                f"所有人的手指都指向了{target_name}。"
                f"经理露出了满意的微笑：“很好，{target_name}，跟我来办公室坐坐。”"
                f"在{target_name}被拖走的时候，你看到他/她的眼神里写满了不甘……"
                f"但你现在没空同情，因为明天还得继续活下去。"
            )

        if self.state.game_over:
            result["game_over"] = True
            result["game_result"] = self.state.game_result
            game_over_info = self._build_game_over_response()
            result["evidence_collected"] = game_over_info.get("evidence_collected", [])
            result["evidence_types_count"] = game_over_info.get("evidence_types_count", 0)
            return result

        result["game_over"] = False
        result["can_proceed_to_night"] = True
        result["economy_snapshot"] = self._build_economy_snapshot()
        # 投票结算完成后，立即预加载夜间结盟（不阻塞返回）
        if not result.get("game_over", False) and not result.get("player_eliminated", False):
            self._pending_night_alliance = asyncio.create_task(self._prepare_night_alliance_data())
        return result

    def enter_night_phase(self) -> dict:
        """
        进入夜间阶段。
        MVP阶段：夜间仅展示过渡文案，不实现群聊监听。
        """
        self.state.current_phase = GamePhase.NIGHT

        day = self.state.current_day
        if day >= TOTAL_DAYS:
            return self._end_game()

        return {
            "phase": "night",
            "day": day,
            "message": (
                f"第{day}天结束了。你回到宿舍，躺在硬邦邦的铁架床上。"
                f"隔壁传来同事们窃窃私语的声音——他们在讨论今天的事。"
                f"你翻了个身，提醒自己：还剩{TOTAL_DAYS - day}天。"
            ),
            "can_proceed_to_next_day": True,
        }

    async def _prepare_night_alliance_data(self) -> dict:
        calc = NightAllianceSystem.calculate_alliances(
            self.state.npcs,
            self.state.relationships,
            self.state.player.name,
        )
        alliances = list(calc.get("alliances", []))
        visitors = list(calc.get("visitors", []))
        alive_npc_ids = [nid for nid, npc in self.state.npcs.items() if getattr(npc, "alive", False)]
        if len(alive_npc_ids) <= 1:
            # 仅剩玩家+1名NPC时，不触发夜间串门/结盟
            alliances = []
            visitors = []
        self.state.daily.night_alliances = alliances
        self.state.daily.night_visitors = visitors
        self.state.daily.night_visitor_proposals = {}
        self.state.daily.player_opened_door = False
        self.state.daily.player_alliance_done = False
        self.state.daily.player_scout_done = False
        self.state.daily.player_alliance_partner = ""
        self.state.daily.player_alliance_target = ""
        self._active_night_visitor_id = ""

        print(
            f"[NightAlliance] day={self.state.current_day} alliances={alliances} visitors={visitors}"
        )
        self._write_npc_npc_alliance_memories(alliances)
        proposals = await NightAllianceSystem.generate_all_visitor_proposals(
            visitors=visitors,
            npcs=self.state.npcs,
            relationships=self.state.relationships,
            memory=self.memory,
            day=self.state.current_day,
            player_name=self.state.player.name,
        )
        self.state.daily.night_visitor_proposals = proposals
        return {
            "alliances": alliances,
            "visitors": visitors,
            "proposals": proposals,
        }

    def _write_npc_npc_alliance_memories(self, alliances: list[tuple[str, str, str]]) -> None:
        if not self.memory:
            return
        for a, b, target in alliances:
            b_name = self._npc_display_name(b, b)
            a_name = self._npc_display_name(a, a)
            target_name = self.state.player.name if target == "player" else self._npc_display_name(target, target)
            self.memory.add_impression(
                observer_id=a,
                target_id=b,
                day=self.state.current_day,
                impression_text=f"我和{b_name}达成共识，明天一起投{target_name}！",
            )
            self.memory.add_impression(
                observer_id=b,
                target_id=a,
                day=self.state.current_day,
                impression_text=f"我和{a_name}达成共识，明天一起投{target_name}！",
            )

    def _apply_alliance_betrayal_penalty(
        self,
        vote_record: dict[str, str],
        alliances: list[tuple[str, str, str]],
    ) -> None:
        alliances = list(alliances or [])
        if not alliances:
            return
        for a, b, target in alliances:
            a_vote = str(vote_record.get(a, "") or "").strip()
            b_vote = str(vote_record.get(b, "") or "").strip()
            target_name = self.state.player.name if target == "player" else self._npc_display_name(target, target)
            if a_vote and a_vote != target:
                if self.memory:
                    self.memory.add_impression(
                        observer_id=b,
                        target_id=a,
                        day=self.state.current_day,
                        impression_text=f"{self._npc_display_name(a, a)}背叛了我们的约定，说好一起投{target_name}，结果他根本没投。",
                    )
                self.manager.modify_affinity(
                    b,
                    a,
                    -18,
                    reason=f"对方背叛了与你共同投{target_name}的约定",
                )
            if b_vote and b_vote != target:
                if self.memory:
                    self.memory.add_impression(
                        observer_id=a,
                        target_id=b,
                        day=self.state.current_day,
                        impression_text=f"{self._npc_display_name(b, b)}背叛了我们的约定，说好一起投{target_name}，结果他根本没投。",
                    )
                self.manager.modify_affinity(
                    a,
                    b,
                    -18,
                    reason=f"对方背叛了与你共同投{target_name}的约定",
                )

    async def enter_night_phase_v2(self) -> dict:
        """进入夜间阶段（拉帮结伙版本）。"""
        self.state.current_phase = GamePhase.NIGHT
        day = self.state.current_day

        if day >= TOTAL_DAYS:
            return self._end_game()

        if self._pending_night_alliance:
            try:
                await self._pending_night_alliance
            except Exception:
                await self._prepare_night_alliance_data()
            self._pending_night_alliance = None
        else:
            await self._prepare_night_alliance_data()

        return {
            "phase": "night_phase_data",
            "day": day,
            "message": f"第{day}天夜幕降临。走廊偶尔响起脚步声，像是谁在门外犹豫。",
            "alive_npcs": [
                {"npc_id": nid, "npc_name": self._npc_display_name(nid, nid)}
                for nid, npc in self.state.npcs.items()
                if npc.alive
            ],
            "night_alliances": self.state.daily.night_alliances,
            "night_visitors": [
                {
                    "npc_id": nid,
                    "npc_name": self._npc_display_name(nid, nid),
                }
                for nid in self.state.daily.night_visitors
            ],
            "night_visitor_proposals": self.state.daily.night_visitor_proposals,
            "player_opened_door": self.state.daily.player_opened_door,
            "player_alliance_done": self.state.daily.player_alliance_done,
            "player_scout_done": self.state.daily.player_scout_done,
            "player_alliance_partner": self.state.daily.player_alliance_partner,
            "player_alliance_target": self.state.daily.player_alliance_target,
            "battery": self.state.player.battery,
            "economy_snapshot": self._build_economy_snapshot(),
            "contract_snapshot": [
                {
                    "contract_id": str(c.get("contract_id", "")),
                    "contract_type": str(c.get("contract_type", "")),
                    "status": str(c.get("status", "")),
                    "due_phase": str(c.get("due_phase", "")),
                    "proposer_id": str(c.get("proposer_id", "")),
                    "target_id": str(c.get("target_id", "")),
                    "terms": dict(c.get("terms", {}) or {}),
                }
                for c in (self._active_contracts or [])
            ],
            "can_proceed_to_next_day": True,
        }

    def night_open_door(self, visitor_npc_id: str, open_door: bool) -> dict:
        visitors = list(self.state.daily.night_visitors or [])
        if not visitors:
            return {"success": False, "message": "今晚没有访客。"}
        visitor_npc_id = str(visitor_npc_id or "").strip()
        if not open_door and not visitor_npc_id:
            visitor_npc_id = visitors[0]
        if open_door and visitor_npc_id not in visitors:
            return {"success": False, "message": "这个访客并没有来敲门。"}
        if self.state.daily.player_opened_door:
            return {"success": False, "message": "你今晚已经开过门了。"}

        if not open_door:
            if self.memory:
                for nid in visitors:
                    self.memory.add_impression(
                        observer_id=nid,
                        target_id="player",
                        day=self.state.current_day,
                        impression_text=f"我想找{self.state.player.name}结盟，但他没有开门。",
                    )
            self.state.daily.night_visitors = []
            return {
                "success": True,
                "opened": False,
                "message": "你屏住呼吸没有开门。门外脚步声慢慢远去。",
            }

        # 开门：被选中者进入对话，其余来访者写“被无视”记忆
        chosen_name = self._npc_display_name(visitor_npc_id, visitor_npc_id)
        if self.memory:
            for nid in visitors:
                if nid == visitor_npc_id:
                    continue
                self.memory.add_impression(
                    observer_id=nid,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=f"我想找{self.state.player.name}结盟，但他给{chosen_name}开了门，根本没理我。",
                )
        self.state.daily.player_opened_door = True
        self.state.daily.player_alliance_done = True  # 开门后不可再主动找人
        self._active_night_visitor_id = visitor_npc_id
        proposal = self.state.daily.night_visitor_proposals.get(visitor_npc_id, {})
        return {
            "success": True,
            "opened": True,
            "visitor_npc_id": visitor_npc_id,
            "visitor_npc_name": chosen_name,
            "story_text": str(proposal.get("story_text", "") or ""),
            "target_id": str(proposal.get("target_id", "") or ""),
            "target_name": self.state.player.name
            if str(proposal.get("target_id", "") or "") == "player"
            else self._npc_display_name(str(proposal.get("target_id", "") or ""), "某人"),
        }

    def night_respond(self, visitor_npc_id: str = "", agree: bool = False) -> dict:
        active_id = str(getattr(self, "_active_night_visitor_id", "") or "")
        if not active_id:
            return {"success": False, "message": "当前没有可回应的结盟提议。"}
        visitor_npc_id = str(visitor_npc_id or "").strip() or active_id
        if visitor_npc_id != active_id:
            return {"success": False, "message": "你正在回应另一位访客。"}

        proposal = self.state.daily.night_visitor_proposals.get(visitor_npc_id, {})
        target_id = str(proposal.get("target_id", "") or "")
        target_name = self.state.player.name if target_id == "player" else self._npc_display_name(target_id, "某人")

        if self.memory:
            if agree:
                self.memory.add_impression(
                    observer_id=visitor_npc_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=f"{self.state.player.name}同意跟我结盟，明天一起投{target_name}。",
                )
            else:
                self.memory.add_impression(
                    observer_id=visitor_npc_id,
                    target_id="player",
                    day=self.state.current_day,
                    impression_text=f"{self.state.player.name}开了门但拒绝了我的提议，真不知道他在想什么。",
                )

        if agree:
            self.state.daily.player_alliance_partner = visitor_npc_id
            self.state.daily.player_alliance_target = target_id

        self.state.daily.night_visitors = []
        self._active_night_visitor_id = ""
        return {
            "success": True,
            "agreed": bool(agree),
            "partner_id": visitor_npc_id if agree else "",
            "target_id": target_id if agree else "",
            "target_name": target_name if agree else "",
            "message": "你点头同意了这场交易。" if agree else "你摇了摇头，把话题掐断了。",
        }

    async def night_seek_alliance(self, target_npc_id: str, vote_target_id: str) -> dict:
        if self.state.daily.player_alliance_done or self.state.daily.player_opened_door:
            return {"success": False, "message": "你今晚已经没有再结盟的机会了。"}

        self.state.daily.player_alliance_done = True  # 主动发起会消耗机会（无论结果）
        result = await NightAllianceSystem.handle_player_seeks_alliance(
            target_npc_id=target_npc_id,
            vote_target_id=vote_target_id,
            npc_alliances=self.state.daily.night_alliances,
            relationships=self.state.relationships,
            memory=self.memory,
            day=self.state.current_day,
            player_name=self.state.player.name,
            npcs=self.state.npcs,
        )
        if result.get("success") and result.get("agreed"):
            self.state.daily.player_alliance_partner = target_npc_id
            self.state.daily.player_alliance_target = vote_target_id
        return result

    async def night_scout(self, target_npc_id: str) -> dict:
        """夜间巡视NPC房间。

        发现结盟时调一次AI生成"密谋对话"，把模板文本替换成真正能透露
        "投谁/为什么投"的现场段落；AI失败 fallback 到含 target_name 的兜底文本。
        没结盟则照旧用模板"似乎已经睡了"。
        """
        if self.state.daily.player_scout_done:
            return {"success": False, "message": "今晚你已经巡视过一次了。"}
        if self.state.player.battery < SCOUT_BATTERY_COST:
            return {
                "success": False,
                "message": f"电量不足！巡视需要{SCOUT_BATTERY_COST}%，当前{self.state.player.battery}%",
            }

        self.state.daily.player_scout_done = True
        self.manager.modify_battery(-SCOUT_BATTERY_COST)
        target_name = self._npc_display_name(target_npc_id, target_npc_id)
        partner_id = ""
        vote_target_id = ""
        for a, b, t in self.state.daily.night_alliances:
            if target_npc_id == a:
                partner_id = b
                vote_target_id = t
                break
            if target_npc_id == b:
                partner_id = a
                vote_target_id = t
                break

        if not partner_id:
            text = (
                f"你的小助理趴在通风管道上看了半天，{target_name}的房间里只有他/她一个人，"
                "似乎已经睡了。"
            )
            return {
                "success": True,
                "message": text,
                "battery_remaining": self.state.player.battery,
                "target_npc_id": target_npc_id,
                "found_alliance": False,
                "partner_id": "",
            }

        partner_name = self._npc_display_name(partner_id, partner_id)
        if vote_target_id == "player":
            vote_target_name = self.state.player.name
        elif vote_target_id:
            vote_target_name = self._npc_display_name(vote_target_id, vote_target_id)
        else:
            vote_target_name = "某人"

        # 召唤 AI 生成密谋对话；失败 fallback 到含 target_name 的兜底文本。
        intro_line = (
            f"你的小助理从通风管道偷偷看了一眼{target_name}的房间——"
        )
        try:
            dl = DataLoader()
            target_npc_state = self.state.npcs.get(target_npc_id)
            partner_npc_state = self.state.npcs.get(partner_id)
            target_personality = (target_npc_state.personality if target_npc_state else "") or ""
            partner_personality = (partner_npc_state.personality if partner_npc_state else "") or ""
            target_public = str(dl.get_npc_field(target_npc_id, "public_impression", "")).strip()
            partner_public = str(dl.get_npc_field(partner_id, "public_impression", "")).strip()
            room_label = f"{target_name}的房间"
            dialogue_text = await AIService.generate_alliance_conspiracy_dialogue_v2(
                npc_a_name=target_name,
                npc_a_personality=target_personality,
                npc_a_public_impression=target_public,
                npc_b_name=partner_name,
                npc_b_personality=partner_personality,
                npc_b_public_impression=partner_public,
                target_name=vote_target_name,
                room_name=room_label,
                alliance_reason="",
            )
        except Exception:
            dialogue_text = ""

        if dialogue_text:
            text = f"{intro_line}\n\n{dialogue_text}"
        else:
            text = (
                f"{intro_line}\n"
                f"你的小助理看到{partner_name}在{target_name}房间里，两人压低声音说着什么，"
                f"但隔着管道实在听不清……不过你注意到他们提到了{vote_target_name}的名字。"
            )
        return {
            "success": True,
            "message": text,
            "battery_remaining": self.state.player.battery,
            "target_npc_id": target_npc_id,
            "found_alliance": True,
            "partner_id": partner_id,
            "vote_target_id": vote_target_id,
            "vote_target_name": vote_target_name,
        }

    def proceed_to_next_day(self) -> dict:
        """
        夜间结束，进入下一天。

        返回:
            下一天的任务选择阶段数据
        """
        # 夜里发生的NPC-NPC结盟在“次日投票”生效，先缓存再跨天重置daily
        self._alliances_to_enforce = list(getattr(self.state.daily, "night_alliances", []) or [])
        self.manager.advance_phase()
        if not self.state.game_over:
            self._apply_daily_fear_decay()
        self._today_events_summary = []
        self._active_night_visitor_id = ""
        if self._pending_night_alliance and not self._pending_night_alliance.done():
            self._pending_night_alliance.cancel()
        self._pending_night_alliance = None

        if self.state.game_over:
            return self._build_game_over_response()

        return self.start_task_selection()

    def _end_game(self) -> dict:
        """
        第5天结束，进行最终结局判定。
        """
        self.manager._end_game()
        return self._build_game_over_response()

    def _build_game_over_response(self) -> dict:
        """构建游戏结束响应（从CSV读取剧情）。"""
        result = self.state.game_result
        player_name = self.state.player.name
        dl = DataLoader()

        evidence_types = set()
        evidence_details = []
        for card in self.state.evidence_collected:
            if card.linked_evidence_tag and card.linked_evidence_tag.startswith("evidence_"):
                parts = card.linked_evidence_tag.split("_", 3)
                if len(parts) >= 4:
                    evidence_type = parts[3]
                    evidence_types.add(evidence_type)
                    evidence_details.append(
                        {
                            "card_id": card.id,
                            "type": evidence_type,
                            "source": card.source_description,
                            "day": card.day_recorded,
                        }
                    )

        if result == "win":
            message = dl.pick_random_element("endings", "win")
        elif result == "fail_voted_out":
            message = dl.pick_random_element("endings", "fail_voted")
        elif result == "fail_no_evidence":
            message = dl.pick_random_element("endings", "fail_evidence")
        elif result == "fail_boss_executed":
            message = dl.pick_random_element("endings", "fail_boss_executed")
        else:
            message = ""

        if message:
            message = message.replace("{player_name}", player_name)
        else:
            message = "游戏结束。"

        return {
            "phase": "game_over",
            "game_result": result,
            "message": message,
            "evidence_collected": evidence_details,
            "evidence_types_count": len(evidence_types),
            "evidence_count": len(self.state.evidence_collected),
            "valid_evidence_count": self._valid_evidence_count(),
            "recorded_cards_count": self._recorded_cards_count(),
            "battery": self.state.player.battery,
            "total_days_survived": self.state.current_day,
            "player_name": player_name,
        }

    def _build_opening(self) -> dict:
        """从CSV构建开场剧情(三幕:背景旁白 / 经理发言 / 任务说明)。"""
        dl = DataLoader()
        narration = dl.pick_random_element("opening", "opening_narration")
        boss_speech = dl.pick_random_element("opening", "boss_speech")
        mission_brief = dl.pick_random_element("opening", "mission_brief")
        player_name = self.state.player.name if self.state and self.state.player else "调查员"

        narration = (narration or "你来到了救世主集团,调查开始了。").replace("{player_name}", player_name)
        boss_speech = (boss_speech or "有卧底混进来了。每天投票,找出来。").replace("{player_name}", player_name)
        mission_brief = (mission_brief or
            f"你是末日调查局的卧底调查员。\n代号:{player_name}\n任务:5天内收集5份证据\n规则:不被投票淘汰,不被经理识破。"
        ).replace("{player_name}", player_name)

        return {
            "narration": narration,
            "boss_speech": boss_speech,
            "mission_brief": mission_brief,
            "player_name": player_name,
        }

    def _build_phase_response(self, message: str) -> dict:
        """构建通用的阶段响应。"""
        return {
            "phase": self.state.current_phase.value,
            "day": self.state.current_day,
            "message": message,
            "game_over": self.state.game_over,
        }

    @staticmethod
    def _clone_task_by_id(task_id: str):
        for task in TASK_DEFINITIONS:
            if task.id == task_id:
                return copy.deepcopy(task)
        return None

    def _preview_route_without_side_effect(self) -> dict:
        """
        调试预览：调用一次 trigger_skeleton_event() 后回滚关键状态。
        用于返回 route/choice，不污染正常流程。
        """
        snapshot_events = list(self.state.daily.events_triggered)
        snapshot_social_used = bool(self.state.daily.social_event_used)
        snapshot_emotions = list(self.state.player.hand_emotions)
        snapshot_actions = list(self.state.player.hand_actions)

        preview_event = self.manager.trigger_skeleton_event()

        # 回滚可见副作用
        self.state.daily.events_triggered = snapshot_events
        self.state.daily.social_event_used = snapshot_social_used
        self.state.player.hand_emotions = snapshot_emotions
        self.state.player.hand_actions = snapshot_actions

        if not preview_event:
            return {
                "event_route": "none",
                "choice_variant": "",
                "participant_npc_ids": [],
                "observer_npc_ids": [],
                "debug_scenario_code": "",
                "debug_choice_source": "",
            }
        if preview_event.get("event_route") == "choice_required":
            return {
                "event_route": "choice_required",
                "choice_variant": str(preview_event.get("choice_variant", "")),
                "participant_npc_ids": [],
                "observer_npc_ids": [],
                "debug_scenario_code": str(preview_event.get("debug_scenario_code", "")),
                "debug_choice_source": str(preview_event.get("debug_choice_source", "choice_required")),
            }
        return {
            "event_route": str(preview_event.get("event_route", "")),
            "choice_variant": "",
            "participant_npc_ids": [str(x) for x in preview_event.get("participant_npc_ids", []) if str(x)],
            "observer_npc_ids": [str(x) for x in preview_event.get("observer_npc_ids", []) if str(x)],
            "debug_scenario_code": str(preview_event.get("debug_scenario_code", "")),
            "debug_choice_source": str(preview_event.get("debug_choice_source", "")),
        }

    def debug_seed_work_snapshot(self, payload: dict) -> dict:
        """
        Debug入口：强制布置当前小时的玩家/NPC任务与房间，便于稳定复测五种状况。
        """
        if self.state is None or self.manager is None:
            self.new_game()
        if self.state.current_phase == GamePhase.TASK_SELECTION:
            self.start_task_selection()

        player_task_id = str(payload.get("player_task_id", "")).strip()
        npc_task_ids = payload.get("npc_task_ids", {})
        if not player_task_id:
            return {"error": "player_task_id 不能为空"}
        if not isinstance(npc_task_ids, dict):
            return {"error": "npc_task_ids 必须是对象字典"}

        repeat_task_count = int(payload.get("repeat_task_count", 5))
        repeat_task_count = max(1, min(5, repeat_task_count))
        hour = int(payload.get("hour", 0))
        hour = max(0, min(repeat_task_count - 1, hour))
        strict = bool(payload.get("strict", True))

        player_task = self._clone_task_by_id(player_task_id)
        if player_task is None:
            return {"error": f"未知任务ID: {player_task_id}"}

        alive_ids = [nid for nid, npc in self.state.npcs.items() if npc.alive]
        missing_npcs = [nid for nid in alive_ids if nid not in npc_task_ids]
        if strict and missing_npcs:
            return {"error": f"缺少NPC任务映射: {', '.join(missing_npcs)}"}

        # 切到工作态并构造固定任务队列（每人同一任务重复N小时，保证可复现）
        self.state.current_phase = GamePhase.WORKING
        self.state.current_hour = hour
        self.state.player.selected_tasks = [copy.deepcopy(player_task) for _ in range(repeat_task_count)]
        self.state.player.current_task_index = hour
        self.state.player.current_room = self.state.player.selected_tasks[hour].room

        for npc_id, npc in self.state.npcs.items():
            if not npc.alive:
                continue
            npc_tid = str(npc_task_ids.get(npc_id, player_task_id)).strip()
            npc_task = self._clone_task_by_id(npc_tid)
            if npc_task is None:
                return {"error": f"NPC[{npc_id}] 任务ID不存在: {npc_tid}"}
            npc.selected_tasks = [copy.deepcopy(npc_task) for _ in range(repeat_task_count)]
            npc.current_task_index = hour
            npc.current_room = npc.selected_tasks[hour].room

        self.state.daily.social_energy_left = max(0, int(payload.get("social_energy_left", 1)))
        self.state.daily.social_event_used = bool(payload.get("social_event_used", False))
        self.state.daily.events_triggered = []
        self.state.player.hand_emotions = []
        self.state.player.hand_actions = []
        self._pending_work_mode_choice = None
        self._current_event_context = {}
        self._current_skeleton_event = None
        self._current_event_card_mode = "combo"

        # 经理位置可选覆盖，默认保持原位
        boss_room = str(payload.get("boss_room", "")).strip()
        if boss_room:
            try:
                self.state.boss.current_room = Room(boss_room)
            except ValueError:
                return {"error": f"boss_room 无效: {boss_room}"}

        preview = self._preview_route_without_side_effect()
        player_room = self.state.player.current_room.value if self.state.player.current_room else "office"
        coworkers = self.manager.get_player_coworkers()
        npc_rooms = {
            npc_id: (npc.current_room.value if npc.current_room else "")
            for npc_id, npc in self.state.npcs.items() if npc.alive
        }
        return {
            "ok": True,
            "phase": self.state.current_phase.value,
            "day": self.state.current_day,
            "hour": self.state.current_hour,
            "player_task_id": player_task_id,
            "player_room": player_room,
            "social_energy_left": self.state.daily.social_energy_left,
            "social_event_used": self.state.daily.social_event_used,
            "npc_rooms": npc_rooms,
            "coworkers": coworkers,
            "route_preview": preview,
        }

    def get_game_status(self) -> dict:
        """
        获取当前游戏完整状态概览（调试用）。
        """
        alive_npcs = [npc.name for npc in self.state.npcs.values() if npc.alive]
        npc_status_list: list[dict] = []
        for npc_id, npc in self.state.npcs.items():
            if not npc.alive:
                continue
            rel = self.state.relationships.get(npc_id, {}).get("player")
            idx = int(getattr(npc, "current_task_index", -1))
            tasks = list(getattr(npc, "selected_tasks", []) or [])
            task_name = str(tasks[idx].name).strip() if 0 <= idx < len(tasks) else "-"
            npc_status_list.append({
                "id": str(npc_id),
                "name": str(npc.name),
                "is_boss": False,
                "gold": int(self._npc_wallets.get(npc_id, 0) or 0),
                "fear": int(getattr(npc, "fear", 30) or 0),
                "affinity_to_player": int(getattr(rel, "affinity", 0) or 0) if rel else 0,
                "suspicion_to_player": int(getattr(rel, "suspicion", 0) or 0) if rel else 0,
                "current_room": str(getattr(npc.current_room, "value", npc.current_room)),
                "current_task": task_name,
            })
        boss_rel = self.state.relationships.get("boss", {}).get("player")
        npc_status_list.append({
            "id": "boss",
            "name": self._npc_display_name("boss", "经理"),
            "is_boss": True,
            "gold": int(self._npc_wallets.get("boss", 0) or 0),
            "fear": int(getattr(self.state.boss, "fear", 30) or 0),
            "affinity_to_player": int(getattr(boss_rel, "affinity", 0) or 0) if boss_rel else 0,
            "suspicion_to_player": int(getattr(boss_rel, "suspicion", 0) or 0) if boss_rel else 0,
            "current_room": str(getattr(self.state.boss.current_room, "value", self.state.boss.current_room)),
            "current_task": str(getattr(self.state.boss, "current_behavior", "boss_logic")),
        })
        return {
            "day": self.state.current_day,
            "phase": self.state.current_phase.value,
            "hour": self.state.current_hour,
            "game_over": self.state.game_over,
            "game_result": self.state.game_result,
            "player_gold": self.state.player.gold,
            "player_battery": self.state.player.battery,
            "social_energy_left": self.state.daily.social_energy_left,
            "player_room": self.state.player.current_room.value,
            "forced_duo_trigger_count": int(self._forced_duo_trigger_count),
            "alive_npcs": alive_npcs,
            "npc_status_list": npc_status_list,
            "evidence_count": len(self.state.evidence_collected),
            "valid_evidence_count": self._valid_evidence_count(),
            "recorded_cards_count": self._recorded_cards_count(),
            "blank_cards": sum(
                1 for rc in self.state.player.record_cards if rc.status.value == "blank"
            ),
            "economy_snapshot": self._build_economy_snapshot(),
            "contract_snapshot": [
                {
                    "contract_id": str(c.get("contract_id", "")),
                    "contract_type": str(c.get("contract_type", "")),
                    "status": str(c.get("status", "")),
                    "due_phase": str(c.get("due_phase", "")),
                    "terms": dict(c.get("terms", {}) or {}),
                }
                for c in (self._active_contracts or [])
            ],
            "npc_ledger_recent": {
                str(k): list(v)[-5:]
                for k, v in sorted((self._npc_ledger or {}).items(), key=lambda x: str(x[0]))
            },
        }
