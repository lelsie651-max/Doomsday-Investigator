from enum import Enum


class GamePhase(Enum):
    TASK_SELECTION = "task_selection"
    WORKING = "working"
    VOTING = "voting"
    NIGHT = "night"


class BossBehavior(Enum):
    PATROL = "patrol"  # 死亡巡视
    PUA = "pua"  # 职场 PUA 小课堂
    SHADY_BUSINESS = "shady"  # 关门干坏事


class RecordCardStatus(Enum):
    BLANK = "blank"  # 空白记录卡（带血的录音笔）
    RECORDED = "recorded"  # 已记录（致命小黑历）


class Room(Enum):
    OFFICE = "office"  # 主办公区
    MEETING = "meeting"  # 会议室
    WAREHOUSE = "warehouse"  # 仓库
    PANTRY = "pantry"  # 茶水间
    RECEPTION = "reception"  # 接待区
    BOSS_OFFICE = "boss_office"  # 经理办公室


class EvidenceType(Enum):
    PRODUCT_FAKE = "product_fake"  # 产品造假
    FINANCE_FAKE = "finance_fake"  # 财务造假
    EMPLOYEE_ABUSE = "employee_abuse"  # 员工压榨
    SAFETY_HAZARD = "safety_hazard"  # 安全隐患
    CORRUPTION = "corruption"  # 高层腐败


class RewardType(Enum):
    GOLD = "gold"
    AFFINITY_BOSS = "affinity_boss"
    AFFINITY_COLLEAGUE = "affinity_colleague"
    SUSPICION_DOWN = "suspicion_down"
    INFO = "info"
    NONE = "none"
