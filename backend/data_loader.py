"""
数据加载器 - 从JSON/CSV文件加载游戏内容数据

所有游戏内容（骨架、元素池、NPC档案、卡牌style）
都存放在 backend/data/ 目录下的独立文件中。
本模块负责加载和缓存这些数据。
"""

import csv
import json
import random
from pathlib import Path
from .config_loader import normalize_room_key

DATA_DIR = Path(__file__).resolve().parent / "data"


class DataLoader:
    """游戏数据加载器（单例模式）"""

    _instance = None
    _act1_examples_cache: list[str] | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self):
        if not self._loaded:
            self._skeletons: dict[str, object] = {}
            self._elements: dict[str, dict[str, list[str]]] = {}
            self._element_rows: dict[str, dict[str, list[dict[str, object]]]] = {}
            self._solo_prompt_elements: dict[str, list[dict[str, object]]] = {}
            self._npc_profiles: dict = {}
            self._card_styles: dict = {}
            self._room_distances: dict[tuple[str, str], float] = {}
            self._fallbacks: dict[str, list[dict[str, str]]] = {}
            self._pua_templates: dict[str, object] = {
                "opening": [],
                "reaction": {},
                "ending": [],
            }
            self._boss_observations: dict[str, dict[str, list[dict[str, str]]]] = {}
            self._room_idle_descriptions: dict[str, list[str]] = {}
            self._npc_anomaly_events: dict[str, list[dict[str, object]]] = {}
            self._npc_gossip_templates: dict[str, list[str]] = {}
            self._random_accidents: list[dict[str, object]] = []
            self._load_all()
            self._loaded = True

    def _load_all(self):
        """一次性加载所有数据文件"""
        self._load_card_styles()
        self._load_npc_profiles()
        self._load_pua_templates()
        self.load_boss_observations()
        self.load_room_idle()
        self.load_npc_anomaly_events()
        self.load_npc_gossip_templates()
        self._load_all_skeletons()
        self._load_all_elements()
        self._load_solo_prompt_elements()
        self._load_room_distances()
        self._load_all_fallbacks()
        self._load_random_accidents()

    # ==========================================
    # 卡牌Style
    # ==========================================

    def _load_card_styles(self):
        path = DATA_DIR / "card_styles.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._card_styles = json.load(f)

    def get_card_style(self, card_id: str) -> str:
        """获取卡牌的style标签"""
        if card_id.startswith("E"):
            entry = self._card_styles.get("emotions", {}).get(card_id)
        else:
            entry = self._card_styles.get("actions", {}).get(card_id)
        return entry["style"] if entry else "normal"

    # ==========================================
    # NPC反应档案
    # ==========================================

    def _load_npc_profiles(self):
        path = DATA_DIR / "npc_profiles.json"
        if path.exists():
            with open(path, "r", encoding="utf-8-sig") as f:
                self._npc_profiles = json.load(f)

    def get_npc_reaction(self, npc_id: str, combo: str) -> dict:
        """
        获取NPC对某combo的反应（单轨：仅as_primary）。

        参数:
            npc_id: NPC的ID（如 "npc_xxx"）
            combo: combo类型（"steady"/"comply"/"rebel"/"contrast"/"crazy"）

        返回:
            {"affinity": int, "suspicion": int, "thought": str}
        """
        profile = self._npc_profiles.get(npc_id, {})
        role_data = profile.get("as_primary", {})
        reaction = role_data.get(combo, {})
        if not isinstance(reaction, dict):
            reaction = {}
        thought = reaction.get("thought", reaction.get("tone", "没什么反应"))
        return {
            "affinity": int(reaction.get("affinity", 0)),
            "suspicion": int(reaction.get("suspicion", 0)),
            "thought": str(thought or "没什么反应"),
        }

    def get_npc_field(self, npc_id: str, field: str, default=""):
        profile = self._npc_profiles.get(npc_id, {})
        if not isinstance(profile, dict):
            return default
        return profile.get(field, default)

    def get_npc_witness_reaction(self, npc_id: str) -> str:
        """
        获取一条 NPC 的 witness_reaction(目击事件时的第一人称内心独白)。

        支持两种格式,自动判断:
          - list[str]: 从池中随机抽一条(推荐,避免重复感)
          - str: 直接返回该字符串(向下兼容旧格式)
          - 缺失或其他类型: 返回空字符串
        """
        field = self.get_npc_field(npc_id, "witness_reaction", "")
        if isinstance(field, list):
            valid = [str(item).strip() for item in field if str(item).strip()]
            if valid:
                return random.choice(valid)
            return ""
        if isinstance(field, str):
            return field.strip()
        return ""

    def get_npc_identity(self, npc_id: str) -> str:
        """获取NPC身份描述（统一从npc_profiles.json读取）。"""
        profile = self._npc_profiles.get(npc_id, {})
        return str(profile.get("identity", "未知NPC")).strip() or "未知NPC"

    def get_npc_aim(self, npc_id: str) -> str:
        """获取NPC的当前行为目标/动机描述（用于角色扮演prompt）。"""
        profile = self._npc_profiles.get(npc_id, {})
        return str(profile.get("aim", "")).strip()

    def get_npc_identity_2p(self, npc_id: str) -> str:
        """获取NPC二人场身份描述；缺失时回退到常规 identity。"""
        profile = self._npc_profiles.get(npc_id, {})
        identity_2p = str(profile.get("identity_2p", "")).strip()
        return identity_2p if identity_2p else self.get_npc_identity(npc_id)

    def get_npc_aim_2p(self, npc_id: str) -> str:
        """获取NPC二人场目标描述；缺失时回退到常规 aim。"""
        profile = self._npc_profiles.get(npc_id, {})
        aim_2p = str(profile.get("aim_2p", "")).strip()
        return aim_2p if aim_2p else self.get_npc_aim(npc_id)

    def get_random_act1_example(self) -> str:
        """随机返回一条 Act1 示例文本；加载失败时返回空字符串。"""
        cls = self.__class__
        if cls._act1_examples_cache is None:
            path = DATA_DIR / "elements" / "act1_examples.csv"
            examples: list[str] = []
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        text = str(row.get("text", "")).strip()
                        if text:
                            examples.append(text)
            except Exception:
                examples = []
            cls._act1_examples_cache = examples
        return random.choice(cls._act1_examples_cache) if cls._act1_examples_cache else ""

    # ==========================================
    # PUA模板 / 经理观察 / 房间日常
    # ==========================================

    def _load_pua_templates(self) -> None:
        """加载 pua_templates.csv,缓存到 self._pua_templates。"""
        self.load_pua_templates()

    def load_pua_templates(self):
        """
        加载 backend/data/config/pua_templates.csv。
        字段：part,npc_id,text,affinity_delta,suspicion_delta
        """
        self._pua_templates = {"opening": [], "reaction": {}, "ending": []}
        path = DATA_DIR / "config" / "pua_templates.csv"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                part = str(row.get("part", "")).strip().lower()
                npc_id = str(row.get("npc_id", "")).strip().lower()
                text = str(row.get("text", "")).strip()
                if not text:
                    continue
                affinity_delta = self._safe_int(row.get("affinity_delta", 0), 0)
                suspicion_delta = self._safe_int(row.get("suspicion_delta", 0), 0)
                entry = {
                    "text": text,
                    "affinity_delta": affinity_delta,
                    "suspicion_delta": suspicion_delta,
                }
                if part in ("opening", "ending"):
                    self._pua_templates[part].append(entry)
                    continue
                if part != "reaction" or not npc_id:
                    continue
                reaction_entry = {
                    "npc_id": npc_id,
                    "text": text,
                    "affinity_delta": affinity_delta,
                    "suspicion_delta": suspicion_delta,
                }
                by_npc = self._pua_templates["reaction"]
                if npc_id not in by_npc:
                    by_npc[npc_id] = []
                by_npc[npc_id].append(reaction_entry)

    def pick_pua_segments(self, target_npc_id: str) -> dict | None:
        """
        随机抽取 PUA 三段(opening + reaction + ending)。

        参数:
            target_npc_id: 被 PUA 的 NPC ID(玩家时传 "player"——无 reaction 段,只有 opening+ending)

        返回:
            {
                "opening_text": str,
                "reaction_text": str,    # 玩家时为空
                "ending_text": str,
                "full_text": str,        # 三段拼接后的完整剧情
                "memory_text": str,      # opening + reaction(给经理记忆用,不含 ending)
                "affinity_delta": int,   # reaction 段的好感变化(经理对目标)
                "suspicion_delta": int,
            }
            数据缺失返回 None。
        """
        if not getattr(self, "_pua_templates", None):
            return None
        templates = self._pua_templates
        openings = templates.get("opening", [])
        endings = templates.get("ending", [])
        if not openings or not endings:
            return None

        target = str(target_npc_id or "").strip().lower()
        opening = random.choice(openings)
        ending = random.choice(endings)

        opening_text = str((opening or {}).get("text", "")).strip()
        ending_text = str((ending or {}).get("text", "")).strip()
        if not opening_text or not ending_text:
            return None

        if target == "player" or not target:
            # 玩家被 PUA: 无 reaction 段(MVP 简化)
            return {
                "opening_text": opening_text,
                "reaction_text": "",
                "ending_text": ending_text,
                "full_text": f"{opening_text}\n\n{ending_text}",
                "memory_text": opening_text,
                "affinity_delta": 0,
                "suspicion_delta": 0,
            }

        reactions = templates.get("reaction", {}).get(target, [])
        if not reactions:
            # 没有该 NPC 的 reaction 池: 只用 opening + ending
            return {
                "opening_text": opening_text,
                "reaction_text": "",
                "ending_text": ending_text,
                "full_text": f"{opening_text}\n\n{ending_text}",
                "memory_text": opening_text,
                "affinity_delta": 0,
                "suspicion_delta": 0,
            }

        reaction = random.choice(reactions)
        reaction_text = str((reaction or {}).get("text", "")).strip()

        return {
            "opening_text": opening_text,
            "reaction_text": reaction_text,
            "ending_text": ending_text,
            "full_text": f"{opening_text}\n\n{reaction_text}\n\n{ending_text}",
            "memory_text": f"{opening_text}\n{reaction_text}",
            "affinity_delta": int(reaction.get("affinity_delta", 0)),
            "suspicion_delta": int(reaction.get("suspicion_delta", 0)),
        }

    def get_pua_scene(self, npc_id: str) -> dict[str, object]:
        """
        返回拼装好的PUA三段文本与数值变化：
        {
            "opening": "...",
            "reaction": "...",
            "ending": "...",
            "full_text": "...",
            "memory_text": "...",   # opening + reaction（不含ending）
            "affinity_delta": int,
            "suspicion_delta": int,
        }
        """
        segments = self.pick_pua_segments(str(npc_id).strip().lower())
        if not segments:
            return {}
        reaction_text = str(segments.get("reaction_text", "")).strip()
        if not reaction_text:
            return {}
        return {
            "opening": str(segments.get("opening_text", "")).strip(),
            "reaction": reaction_text,
            "ending": str(segments.get("ending_text", "")).strip(),
            "full_text": str(segments.get("full_text", "")).strip(),
            "memory_text": str(segments.get("memory_text", "")).strip(),
            "affinity_delta": int(segments.get("affinity_delta", 0)),
            "suspicion_delta": int(segments.get("suspicion_delta", 0)),
        }

    def load_boss_observations(self):
        """
        加载 backend/data/config/boss_npc_observations.csv。
        字段：npc_id,task_id,memory_text,scout_text
        """
        self._boss_observations = {}
        path = DATA_DIR / "config" / "boss_npc_observations.csv"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                npc_id = str(row.get("npc_id", "")).strip()
                task_id = str(row.get("task_id", "any")).strip().lower() or "any"
                memory_text = str(row.get("memory_text", "")).strip()
                scout_text = str(row.get("scout_text", "")).strip()
                if not npc_id or (not memory_text and not scout_text):
                    continue
                npc_bucket = self._boss_observations.setdefault(npc_id, {})
                task_bucket = npc_bucket.setdefault(task_id, [])
                task_bucket.append(
                    {
                        "npc_id": npc_id,
                        "task_id": task_id,
                        "memory_text": memory_text,
                        "scout_text": scout_text,
                    }
                )

    def get_boss_observation(self, npc_id: str, task_id: str) -> dict[str, str]:
        """
        随机返回一条经理观察。
        优先级：精确task_id > any
        """
        npc_key = str(npc_id).strip()
        task_key = str(task_id or "any").strip().lower() or "any"
        npc_bucket = self._boss_observations.get(npc_key, {})
        candidates = list(npc_bucket.get(task_key, []))
        if not candidates and task_key != "any":
            candidates = list(npc_bucket.get("any", []))
        if not candidates:
            return {}
        chosen = random.choice(candidates)
        return {
            "npc_id": str(chosen.get("npc_id", "")).strip(),
            "task_id": str(chosen.get("task_id", "")).strip(),
            "memory_text": str(chosen.get("memory_text", "")).strip(),
            "scout_text": str(chosen.get("scout_text", "")).strip(),
        }

    def load_room_idle(self):
        """
        加载 backend/data/config/room_idle_descriptions.csv。
        字段：room,text
        """
        self._room_idle_descriptions = {}
        path = DATA_DIR / "config" / "room_idle_descriptions.csv"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                room = self._normalize_room_key(row.get("room", ""))
                text = str(row.get("text", "")).strip()
                if not room or not text:
                    continue
                if room not in self._room_idle_descriptions:
                    self._room_idle_descriptions[room] = []
                self._room_idle_descriptions[room].append(text)

    def get_room_idle(self, room: str) -> str:
        """随机返回房间日常描述。"""
        room_key = self._normalize_room_key(room)
        items = self._room_idle_descriptions.get(room_key, [])
        return random.choice(items) if items else ""

    def load_npc_anomaly_events(self):
        """
        加载 backend/data/config/npc_anomaly_events.csv。
        字段：npc_id,text,is_evidence_hint
        """
        self._npc_anomaly_events = {}
        path = DATA_DIR / "config" / "npc_anomaly_events.csv"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                npc_id = str(row.get("npc_id", "")).strip()
                text = str(row.get("text", "")).strip()
                if not npc_id or not text:
                    continue
                raw_hint = str(row.get("is_evidence_hint", "")).strip().lower()
                is_hint = raw_hint in {"1", "true", "yes", "y"}
                bucket = self._npc_anomaly_events.setdefault(npc_id, [])
                bucket.append(
                    {
                        "npc_id": npc_id,
                        "text": text,
                        "is_evidence_hint": bool(is_hint),
                    }
                )

    def get_npc_anomaly_event(self, npc_id: str) -> dict[str, object]:
        """随机返回一条NPC异常行为描述。"""
        npc_key = str(npc_id).strip()
        items = list(self._npc_anomaly_events.get(npc_key, []))
        if not items:
            return {}
        chosen = random.choice(items)
        return {
            "npc_id": str(chosen.get("npc_id", "")).strip(),
            "text": str(chosen.get("text", "")).strip(),
            "is_evidence_hint": bool(chosen.get("is_evidence_hint", False)),
        }

    def load_npc_gossip_templates(self):
        """
        加载 backend/data/config/npc_gossip_templates.csv。
        字段：template_id,text
        """
        self._npc_gossip_templates = {}
        path = DATA_DIR / "config" / "npc_gossip_templates.csv"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                template_id = str(row.get("template_id", "")).strip().lower()
                text = str(row.get("text", "")).strip()
                if not template_id or not text:
                    continue
                self._npc_gossip_templates.setdefault(template_id, []).append(text)

    def _load_random_accidents(self) -> None:
        """加载 random_accidents.csv 到 self._random_accidents。"""
        import csv
        self._random_accidents = []
        filepath = DATA_DIR / "elements" / "random_accidents.csv"
        if not filepath.exists():
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 标准化字段
                    row["location"] = str(row.get("location", "")).strip().lower()
                    row["npc"] = str(row.get("npc", "")).strip().lower()
                    row["text"] = str(row.get("text", "")).strip()
                    row["condition"] = str(row.get("condition", "neutral")).strip().lower()
                    try:
                        row["weight"] = float(row.get("weight", 1.0) or 1.0)
                    except (TypeError, ValueError):
                        row["weight"] = 1.0
                    if row["location"] and row["npc"] and row["text"]:
                        self._random_accidents.append(row)
        except Exception as e:
            # 加载失败不要崩,留空列表让上层走 fallback
            self._random_accidents = []

    def pick_random_accident(self, location: str, candidates: list[str], player_name: str = "") -> dict | None:
        """
        从 random_accidents.csv 中按 location + candidates 加权随机抽取一条。

        参数:
            location: 房间 key (office/meeting/warehouse/pantry/reception)
            candidates: 候选主角 ID 列表(通常为 [玩家 ID 'player', NPC ID])
            player_name: 玩家显示名,用于替换 {player_name} 占位符

        返回:
            {
                "text": str,           # 已替换占位符
                "condition": str,      # negative / positive / neutral
                "subject_id": str,     # 事件主角 ID(就是 npc 字段)
                "weight": float,
            }
            无匹配时返回 None。
        """
        import random
        if not getattr(self, "_random_accidents", None):
            return None
        loc_norm = str(location or "").strip().lower()
        cand_set = {str(c).strip().lower() for c in (candidates or []) if str(c).strip()}
        if not loc_norm or not cand_set:
            return None

        matched = [
            r for r in self._random_accidents
            if r["location"] == loc_norm and r["npc"] in cand_set
        ]
        if not matched:
            return None

        weights = [float(r.get("weight", 1.0) or 1.0) for r in matched]
        chosen = random.choices(matched, weights=weights, k=1)[0]

        text = str(chosen["text"])
        if player_name:
            text = text.replace("{player_name}", player_name)

        return {
            "text": text,
            "condition": chosen["condition"],
            "subject_id": chosen["npc"],
            "weight": float(chosen.get("weight", 1.0)),
        }

    def get_npc_gossip_text(self, template_id: str, default: str = "", **kwargs) -> str:
        """按模板ID随机取一条并格式化；无配置时返回default。"""
        key = str(template_id or "").strip().lower()
        candidates = list(self._npc_gossip_templates.get(key, []))
        template = random.choice(candidates) if candidates else str(default or "")
        if not template:
            return ""
        try:
            return str(template).format(**kwargs).strip()
        except Exception:
            return str(template).strip()

    def get_all_npc_profiles(self) -> dict[str, dict]:
        """返回全部NPC档案（浅拷贝），数据唯一来源为npc_profiles.json。"""
        return {
            str(k): dict(v)
            for k, v in self._npc_profiles.items()
            if isinstance(v, dict) and str(k) and not str(k).startswith("_") and ("name" in v)
        }

    def get_npc_name_to_id_map(self) -> dict[str, str]:
        """返回NPC姓名/展示名到ID的映射（用于前后端统一反查）。"""
        mapping: dict[str, str] = {}
        for npc_id, profile in self.get_all_npc_profiles().items():
            name = str(profile.get("name", "")).strip()
            display_name = str(profile.get("display_name", name)).strip()
            aliases = profile.get("aliases", [])
            if name:
                mapping[name] = npc_id
            if display_name:
                mapping[display_name] = npc_id
            if isinstance(aliases, list):
                for alias in aliases:
                    alias_str = str(alias).strip()
                    if alias_str:
                        mapping[alias_str] = npc_id
        return mapping

    def get_initial_relationships(self) -> dict[tuple[str, str], tuple[int, int]]:
        """
        从npc_profiles.json读取初始关系（_initial_relationships）。
        结构示例：
          [{"from":"npc_a","to":"npc_b","affinity":-20,"suspicion":30}, ...]
        """
        rows = self._npc_profiles.get("_initial_relationships", [])
        if not isinstance(rows, list):
            return {}
        result: dict[tuple[str, str], tuple[int, int]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            from_id = str(row.get("from", "")).strip()
            to_id = str(row.get("to", "")).strip()
            if not from_id or not to_id or from_id == to_id:
                continue
            try:
                aff = int(row.get("affinity", 0))
                sus = int(row.get("suspicion", 0))
            except Exception:
                continue
            result[(from_id, to_id)] = (aff, sus)
        return result

    # ==========================================
    # 事件骨架
    # ==========================================

    def _load_all_skeletons(self):
        skeletons_dir = DATA_DIR / "skeletons"
        if not skeletons_dir.exists():
            return
        for json_file in skeletons_dir.glob("*.json"):
            room_name = json_file.stem  # "office" / "pua" 等
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data:  # 跳过空数组
                    self._skeletons[room_name] = data

    def get_skeletons_for_room_task(
        self,
        room: str,
        task_id: str,
        event_route: str = "duo",
    ) -> list[dict]:
        """
        获取某房间在某个任务+事件类型下可用的骨架。

        兼容两种骨架结构：
        1) 旧结构（list）：每条骨架可带 task_ids 过滤；
        2) 中间结构（dict）：按 task_id 分组，值为骨架列表（默认视为duo）；
        3) 新结构（dict）：按 task_id 分组，值为 {"duo":[],"solo":[],"interaction":[]}。
        """
        data = self._skeletons.get(room)
        if not data:
            return []

        # 新结构或中间结构：{"task_xxx": ...}
        if isinstance(data, dict):
            task_skeletons = data.get(task_id, [])
            # 新结构：按事件类型再分层
            if isinstance(task_skeletons, dict):
                by_route = task_skeletons.get(event_route, [])
                return by_route if isinstance(by_route, list) else []
            # 中间结构：task -> list，视为duo
            if isinstance(task_skeletons, list):
                return task_skeletons if event_route == "duo" else []
            return []

        # 旧结构：[skeleton...]
        if isinstance(data, list):
            if event_route != "duo":
                return []
            result: list[dict] = []
            for sk in data:
                if not isinstance(sk, dict):
                    continue
                task_ids = sk.get("task_ids")
                if isinstance(task_ids, list) and task_ids:
                    if "*" in task_ids or task_id in task_ids:
                        result.append(sk)
                else:
                    # 旧数据未配置task_ids时，视为该房间内通用
                    result.append(sk)
            return result

        return []

    def get_pua_skeletons(self) -> list[dict]:
        """获取PUA专属骨架"""
        data = self._skeletons.get("pua", [])
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            merged: list[dict] = []
            for _, val in data.items():
                if isinstance(val, list):
                    merged.extend(val)
            return merged
        return []

    # ==========================================
    # 元素池
    # ==========================================

    def _load_all_elements(self):
        elements_dir = DATA_DIR / "elements"
        if not elements_dir.exists():
            return
        self._elements = {}
        self._element_rows = {}
        for csv_file in elements_dir.glob("*.csv"):
            pool_name = csv_file.stem  # "office" / "fallback" 等
            pools: dict[str, list[str]] = {}
            pool_rows: dict[str, list[dict[str, object]]] = {}
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = str(row.get("pool", "")).strip()
                    text = str(row.get("text", "")).strip()
                    # 将CSV中写成字面量的"\\n"转成真实换行，供前端正常渲染。
                    text = text.replace("\\n", "\n")
                    if not key or not text:
                        continue
                    pools.setdefault(key, []).append(text)
                    try:
                        weight = int(str(row.get("weight", "1")).strip() or "1")
                    except (TypeError, ValueError):
                        weight = 1
                    reward_type = str(row.get("reward_type", "")).strip().lower()
                    min_raw = str(row.get("reward_value_min", "")).strip()
                    max_raw = str(row.get("reward_value_max", "")).strip()
                    try:
                        reward_min = int(min_raw) if min_raw != "" else None
                    except (TypeError, ValueError):
                        reward_min = None
                    try:
                        reward_max = int(max_raw) if max_raw != "" else None
                    except (TypeError, ValueError):
                        reward_max = None
                    pool_rows.setdefault(key, []).append(
                        {
                            "pool": key,
                            "text": text,
                            "reward_type": reward_type,
                            "reward_value_min": reward_min,
                            "reward_value_max": reward_max,
                            "weight": max(1, weight),
                        }
                    )
            if pools:
                self._elements[pool_name] = pools
            if pool_rows:
                self._element_rows[pool_name] = pool_rows

    def get_element_pools(self, source: str) -> dict[str, list[str]]:
        """
        获取某来源的所有元素池。

        参数:
            source: CSV文件名（不含扩展名），如 "office" / "pua" / "fallback"

        返回:
            {"action": ["...", "..."], "object": ["...", "..."], ...}
        """
        return self._elements.get(source, {})

    def pick_random_element(self, source: str, pool: str) -> str:
        """从指定元素池中随机抽一个"""
        pools = self._elements.get(source, {})
        items = pools.get(pool, [])
        return random.choice(items) if items else ""

    def pick_weighted_element_row(self, source: str, pool: str) -> dict[str, object]:
        """从指定元素池中按weight随机抽一行完整配置。"""
        source_key = str(source or "").strip()
        pool_key = str(pool or "").strip()
        pool_rows = self._element_rows.get(source_key, {})
        rows = list(pool_rows.get(pool_key, []))
        if not rows:
            return {}
        weights: list[int] = []
        for row in rows:
            try:
                w = int(row.get("weight", 1))
            except (TypeError, ValueError):
                w = 1
            weights.append(max(1, w))
        chosen = random.choices(rows, weights=weights, k=1)[0]
        return dict(chosen)

    def _load_solo_prompt_elements(self):
        """
        加载单人Act1元素池：
        - backend/data/elements/absurd_elements.csv
        - backend/data/elements/workplace_elements.csv
        字段：id, content, tags(可选)
        """
        elements_dir = DATA_DIR / "elements"
        files = {
            "absurd": elements_dir / "absurd_elements.csv",
            "workplace": elements_dir / "workplace_elements.csv",
        }
        self._solo_prompt_elements = {"absurd": [], "workplace": []}
        for pool_name, path in files.items():
            if not path.exists():
                continue
            rows: list[dict[str, object]] = []
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    content = str(row.get("content", row.get("text", ""))).strip()
                    if not content:
                        continue
                    raw_tags = str(row.get("tags", row.get("room_scope", ""))).strip()
                    tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()] if raw_tags else []
                    rows.append(
                        {
                            "id": str(row.get("id", "")).strip(),
                            "content": content,
                            "tags": tags,
                        }
                    )
            self._solo_prompt_elements[pool_name] = rows

    @staticmethod
    def _match_solo_tags(tags: list[str], room_key: str, task_name: str) -> bool:
        if not tags:
            return True
        room_tags = [t.split(":", 1)[1].strip() for t in tags if t.startswith("room:")]
        task_tags = [t.split(":", 1)[1].strip() for t in tags if t.startswith("task:")]
        room_ok = (not room_tags) or (room_key in room_tags)
        task_lower = str(task_name or "").strip().lower()
        task_ok = (not task_tags) or any(k and (k in task_lower) for k in task_tags)
        return room_ok and task_ok

    def pick_solo_prompt_element(
        self,
        pool_name: str,
        room_key: str,
        task_name: str,
    ) -> str:
        """
        从单人Act1元素池挑选元素（带tags过滤，避免明显不匹配）。
        tags支持：
          - room:office / room:meeting ...
          - task:库存 / task:邮件 ...
        """
        rows = list(self._solo_prompt_elements.get(pool_name, []))
        if not rows:
            return ""
        room_norm = normalize_room_key(room_key)
        matched = [
            r for r in rows
            if self._match_solo_tags(
                list(r.get("tags", [])),
                room_norm,
                task_name,
            )
        ]
        candidates = matched if matched else rows
        chosen = random.choice(candidates)
        return str(chosen.get("content", "")).strip()

    # ==========================================
    # 房间距离矩阵
    # ==========================================

    def _load_room_distances(self):
        self._room_distances = {}
        path = DATA_DIR / "room_distances.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                for key, dist in raw.items():
                    rooms = key.split("-")
                    if len(rooms) == 2:
                        distance = float(dist)
                        self._room_distances[(rooms[0], rooms[1])] = distance
                        self._room_distances[(rooms[1], rooms[0])] = distance

    def get_move_time(self, from_room: str, to_room: str) -> float:
        """获取两个房间之间的移动时间（秒）。同房间返回0.5（原地等待）"""
        if from_room == to_room:
            return 0.5
        return self._room_distances.get((from_room, to_room), 2.0)

    # ==========================================
    # Fallback文案池
    # ==========================================

    def _load_all_fallbacks(self):
        """
        加载 backend/data/fallback/*.csv。
        每个csv都按 DictReader 读取为行字典列表。
        """
        fallback_dir = DATA_DIR / "fallback"
        self._fallbacks = {}
        if not fallback_dir.exists():
            return

        for csv_file in fallback_dir.glob("*.csv"):
            rows: list[dict[str, str]] = []
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    normalized = {
                        str(k).lstrip("\ufeff").strip(): str(v).strip()
                        for k, v in row.items()
                        if k is not None and v is not None
                    }
                    if normalized:
                        rows.append(normalized)
            self._fallbacks[csv_file.stem] = rows

    def get_fallback(
        self,
        file_key: str,
        npc_id: str = None,
        combo: str = None,
        room: str = None,
        attitude: str = None,
        default: str = "",
    ) -> str:
        """
        从fallback文件中按条件筛选并随机返回一条。

        参数:
            file_key: 文件名（不含扩展名），如 "f05_duo_act2"
            npc_id: 按NPC筛选（可选）
            combo: 按combo类型筛选（可选）
            room: 按房间筛选（可选）
            attitude: 按态度筛选（可选）
            default: 没命中时返回的兜底文本
        """
        rows = self._fallbacks.get(file_key, [])
        if not rows:
            return default

        normalized_room = self._normalize_room_key(room) if room else None

        def _eq(row_val: str, filter_val: str) -> bool:
            return str(row_val).strip().lower() == str(filter_val).strip().lower()

        def _eq_room(row_val: str, filter_val: str) -> bool:
            row_room = self._normalize_room_key(row_val)
            filter_room = self._normalize_room_key(filter_val)
            return row_room == filter_room

        filtered = rows
        if npc_id:
            filtered = [r for r in filtered if _eq(r.get("npc_id", ""), npc_id)]
        if combo:
            filtered = [r for r in filtered if _eq(r.get("combo", ""), combo)]
        if normalized_room:
            filtered = [r for r in filtered if _eq_room(r.get("room", ""), normalized_room)]
        if attitude:
            filtered = [r for r in filtered if _eq(r.get("attitude", ""), attitude)]

        # 条件过严时，退化到首要条件
        if not filtered:
            if npc_id:
                filtered = [r for r in rows if _eq(r.get("npc_id", ""), npc_id)]
            elif combo:
                filtered = [r for r in rows if _eq(r.get("combo", ""), combo)]
            elif normalized_room:
                filtered = [r for r in rows if _eq_room(r.get("room", ""), normalized_room)]
            elif attitude:
                filtered = [r for r in rows if _eq(r.get("attitude", ""), attitude)]

        if not filtered:
            filtered = rows

        chosen = random.choice(filtered)
        text = str(chosen.get("text", "")).strip()
        return text if text else default

    @staticmethod
    def _normalize_room_key(room: str | None) -> str:
        """统一中英文房间名为内部key，避免调用端关心命名风格。"""
        return normalize_room_key(room)

    def get_fallback_row(
        self,
        file_key: str,
        npc_id: str = None,
        combo: str = None,
        room: str = None,
        attitude: str = None,
    ) -> dict[str, str]:
        """返回一条完整fallback记录（用于需要读取非text字段的场景）。"""
        rows = self._fallbacks.get(file_key, [])
        if not rows:
            return {}
        chosen_text = self.get_fallback(
            file_key=file_key,
            npc_id=npc_id,
            combo=combo,
            room=room,
            attitude=attitude,
            default="",
        )
        if not chosen_text:
            return random.choice(rows)
        for row in rows:
            if str(row.get("text", "")).strip() == chosen_text:
                return row
        return random.choice(rows)

    def get_fallback_text(
        self,
        file_key: str,
        filters: dict[str, str] | None = None,
        default: str = "",
    ) -> str:
        """兼容旧调用：转发到 get_fallback。"""
        filters = filters or {}
        return self.get_fallback(
            file_key=file_key,
            npc_id=filters.get("npc_id"),
            combo=filters.get("combo"),
            room=filters.get("room"),
            attitude=filters.get("attitude"),
            default=default,
        )

    @staticmethod
    def _safe_int(raw_val: object, default: int = 0) -> int:
        try:
            return int(str(raw_val).strip())
        except Exception:
            return default

    def get_npc_npc_interaction_template(self, tone: str | None = None) -> dict[str, object]:
        """
        从 f13_npc_npc_interaction.csv 随机抽一条NPC-NPC互动模板。

        返回字段：
            {
                "tone": str,
                "template": str,
                "affinity_delta": int,
                "suspicion_delta": int,
            }
        """
        rows = self._fallbacks.get("f13_npc_npc_interaction", [])
        if not rows:
            return {}

        normalized_tone = str(tone or "").strip().lower()
        candidates = rows
        if normalized_tone:
            candidates = [
                row
                for row in rows
                if str(row.get("tone", "")).strip().lower() == normalized_tone
            ]
            if not candidates:
                return {}

        chosen = random.choice(candidates)
        template = str(chosen.get("template", "")).strip()
        if not template:
            return {}
        template_active = str(chosen.get("template_active", "")).strip() or template
        template_passive = str(chosen.get("template_passive", "")).strip() or template_active
        return {
            "tone": str(chosen.get("tone", "")).strip(),
            "template": template,
            "template_active": template_active,
            "template_passive": template_passive,
            "affinity_delta": self._safe_int(chosen.get("affinity_delta", 0), 0),
            "suspicion_delta": self._safe_int(chosen.get("suspicion_delta", 0), 0),
        }

    # ==========================================
    # 骨架拼装
    # ==========================================

    def assemble_seed(
        self,
        skeleton: dict,
        primary_npc_name: str,
    ) -> str:
        """
        用元素池填充骨架插槽，生成半成品seed。

        参数:
            skeleton: 骨架dict
            primary_npc_name: 主角NPC的显示名

        返回:
            assembled_seed
        """
        room = skeleton["room"]
        template = skeleton["skeleton"]

        # 确定元素来源
        sources = [room]  # 主房间元素池
        evidence_type = skeleton.get("evidence_type")
        if evidence_type:
            sources.append(f"evidence_{evidence_type}")

        # 收集所有可用元素
        all_pools: dict[str, list[str]] = {}
        for src in sources:
            for pool_name, items in self.get_element_pools(src).items():
                if pool_name not in all_pools:
                    all_pools[pool_name] = []
                all_pools[pool_name].extend(items)

        # 替换插槽
        assembled = template
        assembled = assembled.replace("{primary_npc}", primary_npc_name)
        assembled = assembled.replace(
            "{bystander_note}",
            "当前只有{primary_npc}和玩家两人在场。".replace(
                "{primary_npc}", primary_npc_name
            ),
        )

        # 替换所有元素插槽
        for pool_name, items in all_pools.items():
            placeholder = "{" + pool_name + "}"
            if placeholder in assembled:
                chosen = random.choice(items)
                assembled = assembled.replace(placeholder, chosen)

        return assembled
