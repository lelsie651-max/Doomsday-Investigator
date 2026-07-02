import json
import csv
from pathlib import Path


CONFIG_DIR = Path(__file__).resolve().parent / "data" / "config"


def _raise_config_error(file_name: str, message: str) -> None:
    raise RuntimeError(f"[config] {file_name}: {message}")


def _load_json_or_raise(file_name: str) -> dict:
    path = CONFIG_DIR / file_name
    if not path.exists():
        _raise_config_error(file_name, "文件不存在")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        _raise_config_error(file_name, f"JSON格式错误: {e.msg}")
    if not isinstance(data, dict) or not data:
        _raise_config_error(file_name, "配置必须是非空JSON对象")
    return data


def _load_csv_rows_or_raise(file_name: str) -> list[dict[str, str]]:
    path = CONFIG_DIR / file_name
    if not path.exists():
        _raise_config_error(file_name, "文件不存在")
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            _raise_config_error(file_name, "CSV没有表头")
        for row in reader:
            normalized = {
                str(k).strip(): str(v).strip()
                for k, v in row.items()
                if k is not None and v is not None
            }
            if normalized:
                rows.append(normalized)
    if not rows:
        _raise_config_error(file_name, "文件为空（没有任何有效行）")
    return rows


def _to_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def _to_float_or_raise(file_name: str, field_name: str, raw: str) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        _raise_config_error(file_name, f"{field_name} 必须是数字")


def _to_int_or_raise(file_name: str, field_name: str, raw: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        _raise_config_error(file_name, f"{field_name} 必须是整数")


def _validate_combo_tone(data: dict) -> dict[str, str]:
    required = {"steady", "comply", "rebel", "contrast", "crazy"}
    missing = required.difference(data.keys())
    if missing:
        _raise_config_error("combo_tone.json", f"缺少键: {', '.join(sorted(missing))}")
    result: dict[str, str] = {}
    for k in required:
        v = str(data.get(k, "")).strip()
        if not v:
            _raise_config_error("combo_tone.json", f"{k} 不能为空")
        result[k] = v
    return result


def _validate_reaction_map(data: dict) -> dict[str, dict[str, tuple[int, int]]]:
    required = {"好感上升", "好感下降", "怀疑加深", "怀疑减轻", "无变化"}
    missing = required.difference(data.keys())
    if missing:
        _raise_config_error("reaction_map.json", f"缺少键: {', '.join(sorted(missing))}")
    result: dict[str, dict[str, tuple[int, int]]] = {}
    for key in required:
        entry = data.get(key)
        if not isinstance(entry, dict):
            _raise_config_error("reaction_map.json", f"{key} 必须是对象")
        aff = entry.get("affinity_delta")
        sus = entry.get("suspicion_delta")
        if (
            not isinstance(aff, list) or len(aff) != 2
            or not isinstance(sus, list) or len(sus) != 2
        ):
            _raise_config_error("reaction_map.json", f"{key} 的delta必须是长度为2的数组")
        try:
            aff_pair = (int(aff[0]), int(aff[1]))
            sus_pair = (int(sus[0]), int(sus[1]))
        except (TypeError, ValueError):
            _raise_config_error("reaction_map.json", f"{key} 的delta必须是整数")
        result[key] = {
            "affinity_delta": aff_pair,
            "suspicion_delta": sus_pair,
        }
    return result


def _validate_room_aliases(data: dict) -> dict[str, str]:
    aliases = data.get("aliases")
    if not isinstance(aliases, dict) or not aliases:
        _raise_config_error("room_aliases.json", "aliases 必须是非空对象")
    allowed_targets = {"office", "meeting", "warehouse", "pantry", "reception", "boss_office", "pua"}
    result: dict[str, str] = {}
    for raw_key, raw_target in aliases.items():
        key = str(raw_key).strip().lower()
        target = str(raw_target).strip().lower()
        if not key:
            _raise_config_error("room_aliases.json", "存在空key")
        if target not in allowed_targets:
            _raise_config_error("room_aliases.json", f"{raw_key} 指向非法房间: {raw_target}")
        result[key] = target
    return result


def _validate_pua_events(rows: list[dict[str, str]]) -> list[dict]:
    file_name = "pua_events.csv"
    required = {"id", "name", "description", "prompt", "intensity", "is_active"}
    seen_ids: set[str] = set()
    result: list[dict] = []
    for row in rows:
        missing = required.difference(row.keys())
        if missing:
            _raise_config_error(file_name, f"缺少列: {', '.join(sorted(missing))}")

        event_id = str(row.get("id", "")).strip()
        name = str(row.get("name", "")).strip()
        description = str(row.get("description", "")).strip()
        prompt = str(row.get("prompt", "")).strip()
        if not event_id:
            _raise_config_error(file_name, "存在空id行")
        if event_id in seen_ids:
            _raise_config_error(file_name, f"存在重复id: {event_id}")
        seen_ids.add(event_id)
        if not name:
            _raise_config_error(file_name, f"{event_id} 的name为空")
        if not description:
            _raise_config_error(file_name, f"{event_id} 的description为空")
        if not prompt:
            _raise_config_error(file_name, f"{event_id} 的prompt为空")
        intensity = _to_float_or_raise(file_name, f"{event_id}.intensity", row.get("intensity", ""))
        if intensity <= 0:
            _raise_config_error(file_name, f"{event_id}.intensity 必须大于0")
        is_active = _to_bool(row.get("is_active", "true"))
        if not is_active:
            continue
        result.append(
            {
                "id": event_id,
                "name": name,
                "description": description,
                "prompt": prompt,
                "intensity": intensity,
            }
        )
    if not result:
        _raise_config_error(file_name, "没有启用的PUA事件（is_active=true）")
    return result


def _validate_player_names(rows: list[dict[str, str]]) -> list[str]:
    file_name = "player_names.csv"
    required = {"id", "name", "is_active", "weight"}
    seen_ids: set[str] = set()
    expanded_names: list[str] = []
    for row in rows:
        missing = required.difference(row.keys())
        if missing:
            _raise_config_error(file_name, f"缺少列: {', '.join(sorted(missing))}")

        row_id = str(row.get("id", "")).strip()
        name = str(row.get("name", "")).strip()
        if not row_id:
            _raise_config_error(file_name, "存在空id行")
        if row_id in seen_ids:
            _raise_config_error(file_name, f"存在重复id: {row_id}")
        seen_ids.add(row_id)
        if not name:
            _raise_config_error(file_name, f"{row_id} 的name为空")
        if not _to_bool(row.get("is_active", "true")):
            continue
        weight = _to_int_or_raise(file_name, f"{row_id}.weight", row.get("weight", "1"))
        if weight <= 0:
            _raise_config_error(file_name, f"{row_id}.weight 必须大于0")
        expanded_names.extend([name] * weight)

    if not expanded_names:
        _raise_config_error(file_name, "没有启用的玩家名（is_active=true）")
    return expanded_names


def _validate_shop_items(rows: list[dict[str, str]]) -> dict[str, dict]:
    file_name = "shop_items.csv"
    required = {"item_key", "name", "price", "description", "is_active"}
    result: dict[str, dict] = {}
    for row in rows:
        missing = required.difference(row.keys())
        if missing:
            _raise_config_error(file_name, f"缺少列: {', '.join(sorted(missing))}")
        item_key = str(row.get("item_key", "")).strip()
        name = str(row.get("name", "")).strip()
        description = str(row.get("description", "")).strip()
        if not item_key:
            _raise_config_error(file_name, "存在空item_key行")
        if item_key in result:
            _raise_config_error(file_name, f"存在重复item_key: {item_key}")
        if not name:
            _raise_config_error(file_name, f"{item_key} 的name为空")
        if not description:
            _raise_config_error(file_name, f"{item_key} 的description为空")
        price = _to_int_or_raise(file_name, f"{item_key}.price", row.get("price", "0"))
        if price < 0:
            _raise_config_error(file_name, f"{item_key}.price 不能小于0")
        if not _to_bool(row.get("is_active", "true")):
            continue
        result[item_key] = {
            "name": name,
            "price": price,
            "description": description,
        }
    if not result:
        _raise_config_error(file_name, "没有启用的商品（is_active=true）")
    return result


def _validate_game_numbers(data: dict) -> dict[str, int | float]:
    required_int = {
        "default_affinity",
        "default_suspicion",
        "total_days",
        "daily_action_points",
        "daily_task_pool_hours",
        "evidence_tasks_per_day_min",
        "evidence_tasks_per_day_max",
        "winning_evidence_count",
        "initial_gold",
        "initial_blank_record_cards",
        "initial_battery",
        "scout_battery_cost",
        "chat_monitor_battery_cost",
    }
    required_float = {"scout_accident_rate_normal", "scout_accident_rate_boss"}
    missing = required_int.union(required_float).difference(data.keys())
    if missing:
        _raise_config_error("game_numbers.json", f"缺少键: {', '.join(sorted(missing))}")

    result: dict[str, int | float] = {}
    for key in required_int:
        value = _to_int_or_raise("game_numbers.json", key, data.get(key))
        result[key] = value
    for key in required_float:
        value = _to_float_or_raise("game_numbers.json", key, data.get(key))
        result[key] = value

    if result["total_days"] <= 0:
        _raise_config_error("game_numbers.json", "total_days 必须大于0")
    if result["daily_action_points"] <= 0:
        _raise_config_error("game_numbers.json", "daily_action_points 必须大于0")
    if result["evidence_tasks_per_day_min"] < 0 or result["evidence_tasks_per_day_max"] < 0:
        _raise_config_error("game_numbers.json", "evidence_tasks_per_day_* 不能为负数")
    if result["evidence_tasks_per_day_min"] > result["evidence_tasks_per_day_max"]:
        _raise_config_error("game_numbers.json", "evidence_tasks_per_day_min 不能大于 max")
    for key in ("scout_accident_rate_normal", "scout_accident_rate_boss"):
        v = float(result[key])
        if v < 0 or v > 1:
            _raise_config_error("game_numbers.json", f"{key} 必须在[0,1]之间")
    return result


COMBO_TONE_CONFIG = _validate_combo_tone(_load_json_or_raise("combo_tone.json"))
REACTION_MAP_CONFIG = _validate_reaction_map(_load_json_or_raise("reaction_map.json"))
ROOM_ALIASES_CONFIG = _validate_room_aliases(_load_json_or_raise("room_aliases.json"))
PUA_EVENTS_CONFIG = _validate_pua_events(_load_csv_rows_or_raise("pua_events.csv"))
PLAYER_NAMES_CONFIG = _validate_player_names(_load_csv_rows_or_raise("player_names.csv"))
SHOP_ITEMS_CONFIG = _validate_shop_items(_load_csv_rows_or_raise("shop_items.csv"))
GAME_NUMBERS_CONFIG = _validate_game_numbers(_load_json_or_raise("game_numbers.json"))


def normalize_room_key(room: str | None) -> str:
    if not room:
        return ""
    raw = str(room).strip().lower()
    if raw in ROOM_ALIASES_CONFIG:
        return ROOM_ALIASES_CONFIG[raw]
    compact = raw.replace(" ", "").replace("-", "_")
    return ROOM_ALIASES_CONFIG.get(compact, compact)
