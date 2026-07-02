"""
NPC 记忆系统

第一层：静态身份（不变）
第二层：关系账本（每天更新，数值翻译成人话）
第三层：事件印象（按观察者/目标/天数分组）

核心原则：AI永远不接触数值，只看到人话描述。
"""

from .enums import Room
from .models import NPCState, BossState, Relationship
from .data_loader import DataLoader

# 每个观察者对同一目标在同一天最多保留的印象条数
MAX_IMPRESSIONS_PER_DAY = 5

# 房间中文名
ROOM_NAMES = {
    "office": "主办公区",
    "meeting": "会议室",
    "warehouse": "仓库",
    "pantry": "茶水间",
    "reception": "接待区",
    "boss_office": "经理办公室",
}


class MemorySystem:
    """NPC记忆管理器"""

    def __init__(self):
        # memories[observer_id][target_id][day_number] = list[object]
        # 例：memories["laowang"]["player"][2] = ["在茶水间说话很冲", "今天反而挺配合"]
        self._dl = DataLoader()
        profile_ids = list(self._dl.get_all_npc_profiles().keys())
        observer_ids: list[str] = ["player"]
        observer_ids.extend(profile_ids)
        # 去重，保持顺序
        observer_ids = list(dict.fromkeys([oid for oid in observer_ids if oid]))
        self.memories: dict[str, dict[str, dict[int, list[object]]]] = {
            observer_id: {} for observer_id in observer_ids
        }

    @staticmethod
    def unpack_memory_entry(entry: object) -> tuple[str, bool]:
        """
        统一解析记忆条目，兼容旧的 str 与新的 dict 结构。

        返回:
            (text, sealed)
        """
        if isinstance(entry, dict):
            text = str(entry.get("text", "")).strip()
            sealed = bool(entry.get("sealed", False))
            return text, sealed
        return str(entry).strip(), False

    # ========================================
    # 第一层：静态身份
    # ========================================
    @staticmethod
    def get_identity(npc_id: str) -> str:
        """获取NPC的身份描述（供AI prompt使用）"""
        return DataLoader().get_npc_identity(npc_id)

    @staticmethod
    def get_aim(npc_id: str) -> str:
        """获取NPC目标描述（来自npc_profiles.json的aim字段）。"""
        return DataLoader().get_npc_aim(npc_id)

    # ========================================
    # 第二层：关系账本（数值 -> 人话）
    # ========================================
    @staticmethod
    def translate_affinity(value: int) -> str:
        """好感度数值翻译成人话"""
        if value >= 50:
            return "非常喜欢"
        elif value >= 20:
            return "略有好感"
        elif value >= -20:
            return "无感"
        elif value >= -50:
            return "讨厌"
        else:
            return "恨之入骨"

    @staticmethod
    def translate_suspicion(value: int) -> str:
        """怀疑度数值翻译成人话"""
        if value >= 80:
            return "几乎确信是卧底"
        elif value >= 60:
            return "极度怀疑"
        elif value >= 40:
            return "有些怀疑"
        elif value >= 20:
            return "略微警惕"
        else:
            return "没什么怀疑"

    @staticmethod
    def build_relationship_text(
        npc_id: str,
        relationships: dict[str, dict[str, "Relationship"]],
        npcs: dict[str, NPCState],
        alive_only: bool = True,
    ) -> str:
        """
        构建某个NPC的关系账本人话版本。

        返回示例：
          "对玩家：略微警惕，无感
           对某同事A：没什么怀疑，略有好感
           对某同事B：有些怀疑，讨厌"
        """
        if npc_id not in relationships:
            return "（无关系数据）"

        lines = []
        npc_rels = relationships[npc_id]

        # 对玩家的关系
        if "player" in npc_rels:
            rel = npc_rels["player"]
            aff = MemorySystem.translate_affinity(rel.affinity)
            sus = MemorySystem.translate_suspicion(rel.suspicion)
            lines.append(f"对玩家：{sus}，{aff}")

        # 对其他NPC的关系
        for target_id, rel in npc_rels.items():
            if target_id == "player" or target_id == npc_id:
                continue
            if target_id == "boss":
                target_name = str(DataLoader().get_npc_field("boss", "display_name", DataLoader().get_npc_field("boss", "name", "经理"))).strip() or "经理"
            elif target_id in npcs:
                if alive_only and not npcs[target_id].alive:
                    continue
                target_name = npcs[target_id].name
            else:
                continue

            aff = MemorySystem.translate_affinity(rel.affinity)
            sus = MemorySystem.translate_suspicion(rel.suspicion)
            lines.append(f"对{target_name}：{sus}，{aff}")

        return "\n".join(lines) if lines else "（对周围人没什么特别看法）"

    # ========================================
    # 第三层：事件记忆（新结构）
    # ========================================
    def add_impression(
        self,
        observer_id: str,
        target_id: str,
        day: int,
        impression_text: str,
        sealed: bool = False,
        source: str = "",
    ) -> None:
        """写入一条主观印象：观察者 -> 目标 -> 天数 -> 印象列表。"""
        observer = str(observer_id).strip()
        target = str(target_id).strip()
        text = str(impression_text).strip()
        if not observer or not target or not text:
            return
        if observer not in self.memories:
            self.memories[observer] = {}
        target_bucket = self.memories[observer].setdefault(target, {})
        day_key = int(day) if isinstance(day, int) else 0
        if day_key <= 0:
            day_key = 1
        impressions = target_bucket.setdefault(day_key, [])
        entry: object = {
            "text": text,
            "sealed": bool(sealed),
        }
        source_text = str(source).strip()
        if source_text:
            entry["source"] = source_text
        impressions.append(entry)
        if len(impressions) > MAX_IMPRESSIONS_PER_DAY:
            target_bucket[day_key] = impressions[-MAX_IMPRESSIONS_PER_DAY:]

    def merge_into_last_impression(
        self,
        observer_id: str,
        target_id: str,
        day: int,
        append_text: str,
        sealed: bool = False,
        source: str = "",
    ) -> bool:
        """
        把 append_text 追加到 (observer_id, target_id, day) 下最后一条记忆里。

        用途: 合并因果链记忆 (例如 Act2 见证 + 协商响应),
              避免同一事件被拆成两条独立记忆。

        合并规则:
        - 旧文本以句号类标点 (。!?．！？…) 结尾 → 直接拼接
        - 否则中间加全角句号"。"作分隔
        - sealed: 旧值与新参数取"或"(任一方需要 seal 整条都 seal)
        - source: 旧 source + "+" + 新 source,可追溯链路

        若该天对该目标无记忆,则降级为普通 add_impression。

        返回:
            True  = 成功合并到现有 entry
            False = 没找到现有 entry,降级新建
        """
        observer = str(observer_id).strip()
        target = str(target_id).strip()
        text_to_append = str(append_text).strip()
        if not observer or not target or not text_to_append:
            return False

        day_key = int(day) if isinstance(day, int) else 0
        if day_key <= 0:
            day_key = 1

        target_bucket = self.memories.get(observer, {}).get(target, {})
        impressions = target_bucket.get(day_key) if isinstance(target_bucket, dict) else None
        if not impressions:
            # 当天对该目标无记忆 → 走普通 add_impression
            self.add_impression(
                observer, target, day_key, text_to_append,
                sealed=bool(sealed), source=source,
            )
            return False

        last_entry = impressions[-1]
        old_text, old_sealed = MemorySystem.unpack_memory_entry(last_entry)
        old_source = ""
        if isinstance(last_entry, dict):
            old_source = str(last_entry.get("source", "")).strip()

        # 拼接: 旧文本末尾若没有句号类标点,加全角句号
        sep = "" if old_text.endswith(("。", "！", "？", ".", "!", "?", "…")) else "。"
        new_text = f"{old_text}{sep}{text_to_append}"

        new_sealed = bool(old_sealed) or bool(sealed)

        new_entry: dict = {
            "text": new_text,
            "sealed": new_sealed,
        }
        new_source_parts = [s for s in [old_source, str(source).strip()] if s]
        if new_source_parts:
            new_entry["source"] = "+".join(new_source_parts)

        impressions[-1] = new_entry
        return True

    def add_memory(self, npc_id: str, memory_text: str) -> None:
        """[Deprecated] 兼容旧接口：默认写为“对玩家”的印象。"""
        text = str(memory_text).strip()
        if not text:
            return
        day = 1
        if text.startswith("第"):
            try:
                # 尽量兼容“第X天：...”与“第X天，...”
                day_part = text.split("天", 1)[0].replace("第", "").strip()
                day = max(1, int(day_part))
            except Exception:
                day = 1
        self.add_impression(npc_id, "player", day, text)

    def get_memories(self, npc_id: str) -> list[str]:
        """兼容旧接口：返回某观察者的扁平记忆列表（由新结构flatten）。"""
        observer = str(npc_id).strip()
        observer_mem = self.memories.get(observer, {})
        flat: list[str] = []
        for target_id in sorted(observer_mem.keys()):
            day_map = observer_mem.get(target_id, {})
            for day in sorted(day_map.keys()):
                for entry in day_map[day]:
                    memory_text, _ = MemorySystem.unpack_memory_entry(entry)
                    if memory_text:
                        flat.append(f"第{day}天：{memory_text}")
        return flat

    def add_event_memory_for_witnesses(
        self,
        witness_npc_ids: list[str],
        day: int,
        room_name: str,
        event_summary: str,
        target_id: str = "player",
    ) -> None:
        """
        [Deprecated] 兼容旧接口：为所有目击者写入“对某目标”的印象。

        参数:
            witness_npc_ids: 在场目击的NPC ID列表
            day: 第几天
            room_name: 房间中文名
            event_summary: 事件摘要（由规则引擎生成，不用AI）
        """
        memory_text = f"在{room_name}，{event_summary}"
        for npc_id in witness_npc_ids:
            self.add_impression(npc_id, target_id, day, memory_text)

    @staticmethod
    def generate_event_summary(
        emotion_card_name: str,
        action_card_name: str,
        combo_type: str,
        room_name: str,
    ) -> str:
        """
        用规则引擎生成事件摘要（不用AI）。
        存入NPC记忆供后续prompt使用。
        """
        combo_desc = {
            "steady": "表现得中规中矩",
            "contrast": "做了一些让人困惑的事",
            "crazy": "彻底发疯了",
        }
        desc = combo_desc.get(combo_type, "做了些事")
        return f"玩家以{emotion_card_name}的态度{action_card_name}，{desc}。"

    # ========================================
    # 构建完整的NPC信息包（供AI调用）
    # ========================================
    def build_npc_info_for_ai(
        self,
        npc_id: str,
        relationships: dict[str, dict],
        npcs: dict[str, NPCState],
        player_name: str = "调查员",
    ) -> dict:
        """
        构建单个NPC的完整信息包，直接传给AIService。

        返回:
            {
                "id": "npc_xxx",
                "name": "某同事",
                "identity": "...",
                "relationships": "对玩家：略微警惕...",
                "memories": ["第1天：...", "第2天：..."],
            }
        """
        npc = npcs.get(npc_id)
        name = npc.name if npc else npc_id

        return {
            "id": npc_id,
            "name": name,
            "identity": self.get_identity(npc_id),
            "aim": self.get_aim(npc_id),
            "relationships": self.build_relationship_text(
                npc_id, relationships, npcs
            ),
            "memories": self.get_memories(npc_id),
            "memory_and_relations": self.build_memory_and_relations_text(
                npc_id=npc_id,
                relationships=relationships,
                npcs=npcs,
                player_name=player_name,
            ),
        }

    def build_memory_and_relations_text(
        self,
        npc_id: str,
        relationships: dict[str, dict[str, "Relationship"]],
        npcs: dict[str, NPCState],
        player_name: str = "调查员",
        alive_only: bool = True,
    ) -> str:
        """
        合并“关系账本 + 分天记忆”为统一文本块，供AI直接使用。
        """
        observer_name = self._get_character_name(npc_id, npcs, player_name)
        if npc_id not in relationships:
            return f"{observer_name}的记忆与对其他同事的看法：\n\n（无关系数据）"

        lines = [f"{observer_name}的记忆与对其他同事的看法：", ""]
        for target_id in self._iter_alive_targets(npc_id, npcs, alive_only=alive_only):
            target_name = self._get_character_name(target_id, npcs, player_name)
            public_impression = self._get_public_impression(target_id)
            lines.append(f"对{target_name}（{public_impression}）：")

            rel = relationships.get(npc_id, {}).get(target_id)
            if rel is not None:
                sus = MemorySystem.translate_suspicion(rel.suspicion)
                aff = MemorySystem.translate_affinity(rel.affinity)
                lines.append(f"  当前看法：{sus}，{aff}")

            day_map = self.memories.get(npc_id, {}).get(target_id, {})
            if day_map:
                for day in sorted(day_map.keys()):
                    for entry in day_map[day]:
                        memory_text, _ = MemorySystem.unpack_memory_entry(entry)
                        if memory_text:
                            lines.append(f"  第{day}天：{memory_text}")
            else:
                witness_default = self._get_witness_default(target_id)
                lines.append(f"  （暂无直接交集，初始印象：{witness_default}）")
        return "\n".join(lines).strip()

    def _iter_alive_targets(
        self,
        observer_id: str,
        npcs: dict[str, NPCState],
        alive_only: bool = True,
    ) -> list[str]:
        target_ids: list[str] = ["player"]
        for npc_id, npc in npcs.items():
            if alive_only and not npc.alive:
                continue
            target_ids.append(npc_id)
        ordered = []
        for tid in target_ids:
            if tid == observer_id:
                continue
            if tid not in ordered:
                ordered.append(tid)
        return ordered

    def _get_player_public_impression(self) -> str:
        raw_profiles = getattr(self._dl, "_npc_profiles", {})
        if isinstance(raw_profiles, dict):
            text = str(raw_profiles.get("player_public_impression", "")).strip()
            if text:
                return text
        return "默默无闻的底层员工，平时话不多，但在伤亡率极高的末日通勤中总能毫发无损，背景是个谜。"

    def _get_public_impression(self, target_id: str) -> str:
        if target_id == "player":
            return self._get_player_public_impression()
        text = str(self._dl.get_npc_field(target_id, "public_impression", "")).strip()
        if text:
            return text
        return "看起来平平无奇"

    def _get_witness_default(self, target_id: str) -> str:
        if target_id == "player":
            return "来路不明的危险分子。"
        text = str(self._dl.get_npc_field(target_id, "witness_default", "")).strip()
        if text:
            return text
        return "没怎么打过交道，先保持距离。"

    def _get_character_name(
        self,
        char_id: str,
        npcs: dict[str, NPCState],
        player_name: str,
    ) -> str:
        if char_id == "player":
            return str(player_name).strip() or "调查员"
        if char_id == "boss":
            display_name = str(
                self._dl.get_npc_field(
                    "boss",
                    "display_name",
                    self._dl.get_npc_field("boss", "name", "经理"),
                )
            ).strip()
            return display_name or "经理"
        if char_id in npcs:
            return str(npcs[char_id].name).strip() or char_id
        fallback = str(self._dl.get_npc_field(char_id, "name", char_id)).strip()
        return fallback or char_id
