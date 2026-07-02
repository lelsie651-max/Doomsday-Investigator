from dataclasses import dataclass, field
from typing import Optional

from .enums import *


@dataclass
class Task:
    id: str
    name: str
    room: Room
    duration: int = 1
    reward_type: RewardType = RewardType.NONE
    reward_value: int = 0
    risk_tag: str = ""
    evidence_tag: Optional[str] = None
    evidence_type: Optional[EvidenceType] = None


@dataclass
class RecordCard:
    id: str
    status: RecordCardStatus = RecordCardStatus.BLANK
    record_type: str = ""  # "evidence" / "blackmail"
    linked_evidence_tag: Optional[str] = None
    source_description: str = ""
    day_recorded: Optional[int] = None
    subject_npc_id: str = ""
    subject_npc_name: str = ""
    summary_text: str = ""
    is_evidence: bool = False


@dataclass
class Relationship:
    affinity: int = 0
    suspicion: int = 0
    reason: str = ""


@dataclass
class EmotionCard:
    id: str
    name: str
    tone: str
    is_normal: bool = True
    style: str = "normal"  # normal/corporate/rebel/chaotic


@dataclass
class ActionCard:
    id: str
    name: str
    effect: str
    is_normal: bool = True
    style: str = "normal"  # normal/corporate/rebel/chaotic


@dataclass
class SoloActionCard:
    id: str
    name: str
    effect: str
    tone: str
    is_normal: bool = True
    style: str = "normal"  # normal/corporate/rebel/chaotic
    peek_risk: int = 0  # 预留：未来被偷窥触发概率权重
    peek_affinity_bias: int = 0  # 预留：未来被偷窥时好感度偏置
    peek_suspicion_bias: int = 0  # 预留：未来被偷窥时怀疑度偏置


@dataclass
class NPCState:
    id: str
    name: str
    species: str
    personality: str
    vote_tendency: str
    hidden_goal: str
    current_room: Room = Room.OFFICE
    selected_tasks: list[Task] = field(default_factory=list)
    current_task_index: int = 0
    alive: bool = True
    task_preferences: dict[str, float] = field(default_factory=dict)
    fear: int = 75


@dataclass
class BossState:
    id: str = "boss"
    name: str = "经理"
    species: str = "未知物种"
    current_behavior: BossBehavior = BossBehavior.SHADY_BUSINESS
    current_room: Room = Room.BOSS_OFFICE
    target_npc: Optional[str] = None
    shady_evidence_tag: Optional[str] = None
    patrol_rooms: list[Room] = field(default_factory=list)
    fear: int = 75
    patrol_weights: dict[int, dict[str, int]] = field(
        default_factory=lambda: {
            1: {"patrol": 30, "pua": 35, "shady": 35},
            2: {"patrol": 35, "pua": 35, "shady": 30},
            3: {"patrol": 40, "pua": 30, "shady": 30},
            4: {"patrol": 50, "pua": 30, "shady": 20},
            5: {"patrol": 55, "pua": 30, "shady": 15},
        }
    )


@dataclass
class PlayerState:
    id: str = "player"
    name: str = "调查员"
    action_points: int = 5
    gold: int = 50
    current_room: Room = Room.OFFICE
    selected_tasks: list[Task] = field(default_factory=list)
    current_task_index: int = 0
    hand_emotions: list[str] = field(default_factory=list)
    hand_actions: list[str] = field(default_factory=list)
    record_cards: list[RecordCard] = field(default_factory=list)
    items: dict[str, int] = field(default_factory=lambda: {"blame_card": 0, "battery": 0})
    battery: int = 100


@dataclass
class DailyState:
    task_pool: list[Task] = field(default_factory=list)
    evidence_task_ids: list[str] = field(default_factory=list)
    vote_record: dict[str, str] = field(default_factory=dict)
    vote_result: Optional[str] = None
    events_triggered: list[str] = field(default_factory=list)
    boss_hourly_plan: list[BossBehavior] = field(default_factory=list)
    pua_triggered: bool = False
    boss_player_warning_shown: bool = False
    blame_card_used: bool = False
    social_energy_left: int = 1
    social_event_used: bool = False
    night_alliances: list[tuple[str, str, str]] = field(default_factory=list)
    night_visitors: list[str] = field(default_factory=list)
    night_visitor_proposals: dict[str, dict[str, str]] = field(default_factory=dict)
    player_opened_door: bool = False
    player_alliance_done: bool = False
    player_scout_done: bool = False
    player_alliance_partner: str = ""
    player_alliance_target: str = ""
    # 协商系统(勒索成功时由 game_controller 写入,投票路由检测此字段强制锁定目标)
    # 每天 next_day 时重置为空字符串
    forced_vote_target_id: str = ""
    # 一日内玩家是否已被勒索成功(防多个 NPC 同日重复勒索)
    # 玩家同意勒索时设为 True;next_day 时重置为 False
    # 只针对"勒索同意",祈求和拒绝勒索都不计数
    player_already_extorted_today: bool = False
    # ===== 经理 PUA Agent 决策(Batch 8) =====
    # 每天早上由经理 AI 决策,boss_pua_target_id 为空表示今天不 PUA(AI 也可选放过一天)
    boss_pua_target_id: str = ""        # 今日 PUA 目标 ID(NPC ID 或 "player" 或 "")
    boss_pua_hour: int = -1             # 第几小时 PUA(0-4 对应 5 个小时,-1 表示无)
    boss_pua_decision_reason: str = ""  # AI 决策理由(仅日志用,不展示)
    boss_pua_executed: bool = False     # 今天是否已经执行过 PUA(用于防重复)
