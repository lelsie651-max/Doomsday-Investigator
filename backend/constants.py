import csv
from pathlib import Path

from .config_loader import GAME_NUMBERS_CONFIG, PLAYER_NAMES_CONFIG, SHOP_ITEMS_CONFIG
from .models import ActionCard, EmotionCard, SoloActionCard, Task
from .enums import EvidenceType, RewardType, Room

TASK_DEFINITIONS: list[Task] = [
    Task(
        id="task_office_001",
        name="处理客户询盘",
        room=Room.OFFICE,
        reward_type=RewardType.GOLD,
        reward_value=10,
        risk_tag="无内部消息",
    ),
    Task(
        id="task_office_002",
        name="整理文件归档",
        room=Room.OFFICE,
        reward_type=RewardType.NONE,
        risk_tag="枯燥",
        evidence_type=EvidenceType.FINANCE_FAKE,
    ),
    Task(
        id="task_office_003",
        name="回复客户邮件",
        room=Room.OFFICE,
        reward_type=RewardType.GOLD,
        reward_value=10,
        risk_tag="可能被投诉",
    ),
    Task(
        id="task_office_004",
        name="制作销售报表",
        room=Room.OFFICE,
        reward_type=RewardType.AFFINITY_BOSS,
        reward_value=5,
        risk_tag="数据敏感",
        evidence_type=EvidenceType.FINANCE_FAKE,
    ),
    Task(
        id="task_office_005",
        name="更新产品目录",
        room=Room.OFFICE,
        reward_type=RewardType.INFO,
        risk_tag="可能被同事嘲讽",
        evidence_type=EvidenceType.PRODUCT_FAKE,
    ),
    Task(
        id="task_office_006",
        name="接听客户电话",
        room=Room.OFFICE,
        reward_type=RewardType.GOLD,
        reward_value=10,
        risk_tag="无直接收益",
    ),
    Task(
        id="task_office_007",
        name="校对合同文本",
        room=Room.OFFICE,
        reward_type=RewardType.NONE,
        risk_tag="枯燥",
        evidence_type=EvidenceType.CORRUPTION,
    ),
    Task(
        id="task_office_008",
        name="录入客户信息",
        room=Room.OFFICE,
        reward_type=RewardType.GOLD,
        reward_value=10,
        risk_tag="枯燥",
    ),
    Task(
        id="task_meeting_001",
        name="参加经理会议",
        room=Room.MEETING,
        reward_type=RewardType.INFO,
        risk_tag="怀疑度风险",
        evidence_type=EvidenceType.CORRUPTION,
    ),
    Task(
        id="task_meeting_002",
        name="做会议记录",
        room=Room.MEETING,
        reward_type=RewardType.NONE,
        risk_tag="经理注意到你",
        evidence_type=EvidenceType.FINANCE_FAKE,
    ),
    Task(
        id="task_meeting_003",
        name="参加业务培训",
        room=Room.MEETING,
        reward_type=RewardType.SUSPICION_DOWN,
        reward_value=5,
        risk_tag="无直接收益",
    ),
    Task(
        id="task_meeting_004",
        name="汇报工作进度",
        room=Room.MEETING,
        reward_type=RewardType.AFFINITY_BOSS,
        reward_value=5,
        risk_tag="被追问",
    ),
    Task(
        id="task_meeting_005",
        name="参与部门讨论",
        room=Room.MEETING,
        reward_type=RewardType.INFO,
        risk_tag="被迫站队",
        evidence_type=EvidenceType.EMPLOYEE_ABUSE,
    ),
    Task(
        id="task_warehouse_001",
        name="查看罐头库存",
        room=Room.WAREHOUSE,
        reward_type=RewardType.NONE,
        risk_tag="怀疑度风险",
        evidence_type=EvidenceType.PRODUCT_FAKE,
    ),
    Task(
        id="task_warehouse_002",
        name="整理货架",
        room=Room.WAREHOUSE,
        reward_type=RewardType.SUSPICION_DOWN,
        reward_value=5,
        risk_tag="经理注意到你",
    ),
    Task(
        id="task_warehouse_003",
        name="清点过期产品",
        room=Room.WAREHOUSE,
        reward_type=RewardType.NONE,
        risk_tag="无直接收益",
        evidence_type=EvidenceType.PRODUCT_FAKE,
    ),
    Task(
        id="task_warehouse_004",
        name="搬运新货",
        room=Room.WAREHOUSE,
        reward_type=RewardType.AFFINITY_COLLEAGUE,
        reward_value=5,
        risk_tag="被追问",
    ),
    Task(
        id="task_warehouse_005",
        name="检查仓库安全",
        room=Room.WAREHOUSE,
        reward_type=RewardType.NONE,
        risk_tag="被迫站队",
        evidence_type=EvidenceType.SAFETY_HAZARD,
    ),
    Task(
        id="task_warehouse_006",
        name="处理退货",
        room=Room.WAREHOUSE,
        reward_type=RewardType.NONE,
        risk_tag="客户闹事",
        evidence_type=EvidenceType.PRODUCT_FAKE,
    ),
    Task(
        id="task_pantry_001",
        name="为经理冲咖啡",
        room=Room.PANTRY,
        reward_type=RewardType.AFFINITY_BOSS,
        reward_value=5,
        risk_tag="被嘲讽",
    ),
    Task(
        id="task_pantry_002",
        name="补充茶水间物资",
        room=Room.PANTRY,
        reward_type=RewardType.AFFINITY_COLLEAGUE,
        reward_value=5,
        risk_tag="无直接收益",
    ),
    Task(
        id="task_pantry_003",
        name="清洁茶水间",
        room=Room.PANTRY,
        reward_type=RewardType.SUSPICION_DOWN,
        reward_value=5,
        risk_tag="无直接收益",
    ),
    Task(
        id="task_pantry_004",
        name="准备会议茶点",
        room=Room.PANTRY,
        reward_type=RewardType.AFFINITY_BOSS,
        reward_value=5,
        risk_tag="可能出错",
    ),
    Task(
        id="task_pantry_005",
        name="加热午餐",
        room=Room.PANTRY,
        reward_type=RewardType.INFO,
        risk_tag="被拉入派系",
        evidence_type=EvidenceType.EMPLOYEE_ABUSE,
    ),
    Task(
        id="task_reception_001",
        name="接待访客",
        room=Room.RECEPTION,
        reward_type=RewardType.INFO,
        risk_tag="可能遇到调查员",
    ),
    Task(
        id="task_reception_002",
        name="签收快递",
        room=Room.RECEPTION,
        reward_type=RewardType.NONE,
        risk_tag="无直接收益",
        evidence_type=EvidenceType.PRODUCT_FAKE,
    ),
    Task(
        id="task_reception_003",
        name="接听前台电话",
        room=Room.RECEPTION,
        reward_type=RewardType.INFO,
        risk_tag="可能听到不该听的",
        evidence_type=EvidenceType.CORRUPTION,
    ),
    Task(
        id="task_reception_004",
        name="引导客户参观",
        room=Room.RECEPTION,
        reward_type=RewardType.AFFINITY_BOSS,
        reward_value=5,
        risk_tag="客户问尴尬问题",
    ),
    Task(
        id="task_reception_005",
        name="整理前台资料",
        room=Room.RECEPTION,
        reward_type=RewardType.NONE,
        risk_tag="枯燥",
    ),
]

def _to_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def _to_int(v: str, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _raise_cards_config_error(path: Path, message: str) -> None:
    raise RuntimeError(f"[cards-config] {path.name}: {message}")


def _validate_required_columns(path: Path, fieldnames: list[str] | None, required: set[str]) -> None:
    if not fieldnames:
        _raise_cards_config_error(path, "CSV没有表头")
    missing = required.difference({(f or "").strip() for f in fieldnames})
    if missing:
        _raise_cards_config_error(path, f"缺少必填列: {', '.join(sorted(missing))}")


def _load_emotion_cards_from_csv_or_raise() -> list[EmotionCard]:
    path = Path(__file__).resolve().parent / "data" / "elements" / "emotion_cards.csv"
    if not path.exists():
        _raise_cards_config_error(path, "文件不存在")
    cards: list[EmotionCard] = []
    seen_ids: set[str] = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        _validate_required_columns(path, reader.fieldnames, {"id", "name", "tone", "is_normal", "style"})
        for row in reader:
            card_id = str(row.get("id", "")).strip()
            if not card_id:
                _raise_cards_config_error(path, "存在空id行")
            if card_id in seen_ids:
                _raise_cards_config_error(path, f"存在重复id: {card_id}")
            seen_ids.add(card_id)
            name = str(row.get("name", "")).strip()
            tone = str(row.get("tone", "")).strip()
            style = str(row.get("style", "")).strip()
            if not name:
                _raise_cards_config_error(path, f"{card_id} 的name为空")
            if not tone:
                _raise_cards_config_error(path, f"{card_id} 的tone为空")
            if not style:
                _raise_cards_config_error(path, f"{card_id} 的style为空")
            cards.append(
                EmotionCard(
                    id=card_id,
                    name=name,
                    tone=tone,
                    is_normal=_to_bool(str(row.get("is_normal", "true"))),
                    style=style,
                )
            )
    if not cards:
        _raise_cards_config_error(path, "文件为空（没有任何卡牌行）")
    return cards


def _load_action_cards_from_csv_or_raise() -> list[ActionCard]:
    path = Path(__file__).resolve().parent / "data" / "elements" / "action_cards.csv"
    if not path.exists():
        _raise_cards_config_error(path, "文件不存在")
    cards: list[ActionCard] = []
    seen_ids: set[str] = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        _validate_required_columns(path, reader.fieldnames, {"id", "name", "effect", "is_normal", "style"})
        for row in reader:
            card_id = str(row.get("id", "")).strip()
            if not card_id:
                _raise_cards_config_error(path, "存在空id行")
            if card_id in seen_ids:
                _raise_cards_config_error(path, f"存在重复id: {card_id}")
            seen_ids.add(card_id)
            name = str(row.get("name", "")).strip()
            effect = str(row.get("effect", "")).strip()
            style = str(row.get("style", "")).strip()
            if not name:
                _raise_cards_config_error(path, f"{card_id} 的name为空")
            if not effect:
                _raise_cards_config_error(path, f"{card_id} 的effect为空")
            if not style:
                _raise_cards_config_error(path, f"{card_id} 的style为空")
            cards.append(
                ActionCard(
                    id=card_id,
                    name=name,
                    effect=effect,
                    is_normal=_to_bool(str(row.get("is_normal", "true"))),
                    style=style,
                )
            )
    if not cards:
        _raise_cards_config_error(path, "文件为空（没有任何卡牌行）")
    return cards


def _load_solo_action_cards_from_csv_or_raise() -> list[SoloActionCard]:
    path = Path(__file__).resolve().parent / "data" / "elements" / "solo_action_cards.csv"
    if not path.exists():
        _raise_cards_config_error(path, "文件不存在")
    cards: list[SoloActionCard] = []
    seen_ids: set[str] = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        _validate_required_columns(
            path,
            reader.fieldnames,
            {
                "id",
                "name",
                "effect",
                "tone",
                "is_normal",
                "style",
                "peek_risk",
                "peek_affinity_bias",
                "peek_suspicion_bias",
            },
        )
        for row in reader:
            card_id = str(row.get("id", "")).strip()
            if not card_id:
                _raise_cards_config_error(path, "存在空id行")
            if card_id in seen_ids:
                _raise_cards_config_error(path, f"存在重复id: {card_id}")
            seen_ids.add(card_id)

            name = str(row.get("name", "")).strip()
            effect = str(row.get("effect", "")).strip()
            tone = str(row.get("tone", "")).strip()
            style = str(row.get("style", "")).strip()
            if not name:
                _raise_cards_config_error(path, f"{card_id} 的name为空")
            if not effect:
                _raise_cards_config_error(path, f"{card_id} 的effect为空")
            if not tone:
                _raise_cards_config_error(path, f"{card_id} 的tone为空")
            if not style:
                _raise_cards_config_error(path, f"{card_id} 的style为空")

            cards.append(
                SoloActionCard(
                    id=card_id,
                    name=name,
                    effect=effect,
                    tone=tone,
                    is_normal=_to_bool(str(row.get("is_normal", "true"))),
                    style=style,
                    peek_risk=_to_int(row.get("peek_risk", "0"), 0),
                    peek_affinity_bias=_to_int(row.get("peek_affinity_bias", "0"), 0),
                    peek_suspicion_bias=_to_int(row.get("peek_suspicion_bias", "0"), 0),
                )
            )
    if not cards:
        _raise_cards_config_error(path, "文件为空（没有任何卡牌行）")
    return cards


# 仅使用CSV配置：启动即强校验，缺列/空文件/空字段直接抛错
EMOTION_CARDS: list[EmotionCard] = _load_emotion_cards_from_csv_or_raise()
ACTION_CARDS: list[ActionCard] = _load_action_cards_from_csv_or_raise()
SOLO_ACTION_CARDS: list[SoloActionCard] = _load_solo_action_cards_from_csv_or_raise()

SHOP_ITEMS = SHOP_ITEMS_CONFIG

DEFAULT_AFFINITY = int(GAME_NUMBERS_CONFIG["default_affinity"])
DEFAULT_SUSPICION = int(GAME_NUMBERS_CONFIG["default_suspicion"])
TOTAL_DAYS = int(GAME_NUMBERS_CONFIG["total_days"])
DAILY_ACTION_POINTS = int(GAME_NUMBERS_CONFIG["daily_action_points"])
DAILY_TASK_POOL_HOURS = int(GAME_NUMBERS_CONFIG["daily_task_pool_hours"])
EVIDENCE_TASKS_PER_DAY_MIN = int(GAME_NUMBERS_CONFIG["evidence_tasks_per_day_min"])
EVIDENCE_TASKS_PER_DAY_MAX = int(GAME_NUMBERS_CONFIG["evidence_tasks_per_day_max"])
WINNING_EVIDENCE_COUNT = int(GAME_NUMBERS_CONFIG["winning_evidence_count"])
INITIAL_GOLD = int(GAME_NUMBERS_CONFIG["initial_gold"])
INITIAL_BLANK_RECORD_CARDS = int(GAME_NUMBERS_CONFIG["initial_blank_record_cards"])
INITIAL_BATTERY = int(GAME_NUMBERS_CONFIG["initial_battery"])
SCOUT_BATTERY_COST = int(GAME_NUMBERS_CONFIG["scout_battery_cost"])
CHAT_MONITOR_BATTERY_COST = int(GAME_NUMBERS_CONFIG["chat_monitor_battery_cost"])
SCOUT_ACCIDENT_RATE_NORMAL = float(GAME_NUMBERS_CONFIG["scout_accident_rate_normal"])
SCOUT_ACCIDENT_RATE_BOSS = float(GAME_NUMBERS_CONFIG["scout_accident_rate_boss"])
BOSS_PATROL_ROOMS = [Room.OFFICE, Room.WAREHOUSE, Room.PANTRY, Room.RECEPTION]
BOSS_SHADY_ROOM = Room.BOSS_OFFICE
BOSS_PUA_ROOM = Room.MEETING
BOSS_DEFAULT_ROOM = Room.BOSS_OFFICE
ACCESSIBLE_ROOMS = [
    Room.OFFICE,
    Room.MEETING,
    Room.WAREHOUSE,
    Room.PANTRY,
    Room.RECEPTION,
]

# 玩家随机名字池（可配置，支持weight展开）
PLAYER_NAMES = PLAYER_NAMES_CONFIG
