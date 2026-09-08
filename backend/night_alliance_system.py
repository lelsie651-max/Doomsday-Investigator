import asyncio
import re

from .ai_logger import AILogger
from .ai_service import AIService, DEEPSEEK_MODEL, create_deepseek_chat_completion
from .data_loader import DataLoader


class NightAllianceSystem:
    """夜间拉帮结伙系统（后端规则+少量AI对话生成）。"""

    @staticmethod
    def _alive_npc_ids(npcs: dict) -> list[str]:
        return [nid for nid, npc in npcs.items() if getattr(npc, "alive", False)]

    @staticmethod
    def _display_name(npc_id: str) -> str:
        dl = DataLoader()
        return str(
            dl.get_npc_field(
                npc_id,
                "display_name",
                dl.get_npc_field(npc_id, "name", npc_id),
            )
        ).strip() or npc_id

    @staticmethod
    def _top_affinity_target(npc_id: str, candidate_ids: list[str], relationships: dict) -> str:
        rel_map = relationships.get(npc_id, {})
        best_id = ""
        best_score = -10**9
        for tid in candidate_ids:
            if tid == npc_id:
                continue
            rel = rel_map.get(tid)
            if rel is None:
                continue
            score = int(getattr(rel, "affinity", 0))
            if score > best_score:
                best_score = score
                best_id = tid
        return best_id

    @staticmethod
    def _best_vote_target_for_npc(npc_id: str, relationships: dict, alive_ids: list[str]) -> str:
        """[Deprecated] 仅按 npc_id 自身排除，未排除盟友。仅作回滚保留。
        新代码请使用 _best_vote_target_for_npc_v2(exclude_ids=...)。"""
        rel_map = relationships.get(npc_id, {})
        best_target = ""
        best_score = -10**9
        for tid in alive_ids:
            if tid == npc_id:
                continue
            rel = rel_map.get(tid)
            if rel is None:
                continue
            score = int(getattr(rel, "suspicion", 0)) - int(getattr(rel, "affinity", 0))
            if score > best_score:
                best_score = score
                best_target = tid
        if best_target:
            return best_target
        fallback = [cid for cid in alive_ids if cid != npc_id]
        return fallback[0] if fallback else "player"

    @staticmethod
    def _best_vote_target_for_npc_v2(
        npc_id: str,
        relationships: dict,
        alive_ids: list[str],
        exclude_ids: list[str] | None = None,
    ) -> str:
        """v2：找该 NPC 想投谁。
        - 永远不会返回 npc_id 自己；
        - exclude_ids 可显式追加排除项（用于"找谁结盟则不能投谁"的场景）。
        """
        excludes: set[str] = {str(npc_id).strip()}
        for x in (exclude_ids or []):
            xv = str(x).strip()
            if xv:
                excludes.add(xv)
        rel_map = relationships.get(npc_id, {})
        best_target = ""
        best_score = -10**9
        for tid in alive_ids:
            if tid in excludes:
                continue
            rel = rel_map.get(tid)
            if rel is None:
                continue
            score = int(getattr(rel, "suspicion", 0)) - int(getattr(rel, "affinity", 0))
            if score > best_score:
                best_score = score
                best_target = tid
        if best_target:
            return best_target
        fallback = [cid for cid in alive_ids if cid not in excludes]
        if fallback:
            return fallback[0]
        # 真的全被排除了，再退回不含玩家的成员中随便挑一个
        last_resort = [cid for cid in alive_ids if cid != npc_id]
        return last_resort[0] if last_resort else ""

    @staticmethod
    def calculate_alliance_target(
        npc_a_id: str,
        npc_b_id: str,
        relationships: dict,
        alive_ids: list[str],
    ) -> str:
        """
        结盟后联合投票目标：
        suspicion(A)+suspicion(B)-affinity(A)-affinity(B) 最高者。
        """
        best_target = ""
        best_score = -10**9
        rel_a = relationships.get(npc_a_id, {})
        rel_b = relationships.get(npc_b_id, {})
        for tid in alive_ids:
            if tid in (npc_a_id, npc_b_id):
                continue
            ra = rel_a.get(tid)
            rb = rel_b.get(tid)
            if ra is None or rb is None:
                continue
            score = (
                int(getattr(ra, "suspicion", 0))
                + int(getattr(rb, "suspicion", 0))
                - int(getattr(ra, "affinity", 0))
                - int(getattr(rb, "affinity", 0))
            )
            if score > best_score:
                best_score = score
                best_target = tid
        if best_target:
            return best_target
        fallback = [cid for cid in alive_ids if cid not in (npc_a_id, npc_b_id)]
        return fallback[0] if fallback else "player"

    @staticmethod
    def calculate_alliances(npcs: dict, relationships: dict, player_name: str) -> dict:
        """
        纯数值结盟判定：
        1) 先NPC-NPC互选最高好感，形成自动结盟；
        2) 再判定剩余NPC中“最高好感目标是player”的来访者。
        """
        _ = player_name  # 预留参数，保持接口语义稳定
        alive_npc_ids = NightAllianceSystem._alive_npc_ids(npcs)
        candidate_ids = ["player"] + alive_npc_ids
        picked: set[str] = set()
        mutual_pairs: list[tuple[str, str]] = []

        # 先收集互选关系
        top_map: dict[str, str] = {}
        for nid in alive_npc_ids:
            top_map[nid] = NightAllianceSystem._top_affinity_target(nid, candidate_ids, relationships)

        # 情况三：NPC-NPC互选
        for nid in alive_npc_ids:
            if nid in picked:
                continue
            top = top_map.get(nid, "")
            if not top or top in ("player", "boss") or top in picked:
                continue
            if top_map.get(top, "") == nid and top not in picked:
                pair = tuple(sorted((nid, top)))
                if pair not in mutual_pairs:
                    mutual_pairs.append(pair)
                picked.add(nid)
                picked.add(top)

        # 联盟目标
        alliances: list[tuple[str, str, str]] = []
        alive_targets = ["player"] + alive_npc_ids
        for a, b in mutual_pairs:
            target = NightAllianceSystem.calculate_alliance_target(a, b, relationships, alive_targets)
            alliances.append((a, b, target))

        # 情况一/二：来找玩家
        visitors: list[str] = []
        for nid in alive_npc_ids:
            if nid in picked:
                continue
            if top_map.get(nid, "") == "player":
                visitors.append(nid)
                picked.add(nid)

        return {
            "alliances": alliances,
            "visitors": visitors,
        }

    @staticmethod
    async def generate_visitor_proposal(
        npc_id: str,
        npc_name: str,
        npc_identity: str,
        player_name: str,
        npcs: dict,
        relationships: dict,
        memory,
        day: int,
    ) -> dict:
        """NPC来访玩家的结盟提议（AI生成剧情+系统计算提议目标）。
        关键修正：NPC 来找"player"结盟时，投票目标不可以是 player 自己（不能拉盟友投盟友）。"""
        alive_ids = ["player"] + NightAllianceSystem._alive_npc_ids(npcs)
        target_id = NightAllianceSystem._best_vote_target_for_npc_v2(
            npc_id,
            relationships,
            alive_ids,
            exclude_ids=["player"],
        )
        target_name = player_name if target_id == "player" else NightAllianceSystem._display_name(target_id)
        memory_rel = ""
        if memory:
            memory_rel = memory.build_memory_and_relations_text(
                npc_id,
                relationships,
                npcs,
                player_name=player_name,
                alive_only=True,
            )

        system_prompt = AIService.build_npc_worldview_system_prompt(
            npc_name=npc_name,
            npc_identity=npc_identity,
            npc_aim=DataLoader().get_npc_field(npc_id, "aim", ""),
            npc_memory_rel=memory_rel,
        )
        user_prompt = f"""今天是第{day}天夜里。你决定去找{player_name}密谋。
你想拉他一起在明天的投票中对付某个人，系统给你的倾向目标是：{target_name}。

请以你的性格风格，生成一段你敲门后的对话（3-5句），最后明确提出你的提议：一起投{target_name}。
写作要求：
1. 搞笑、毒舌、职场黑色幽默。
2. 旁白使用第二人称“你”指代{player_name}。
3. 直接输出中文正文，不要Markdown。"""

        fallback_story = f"{npc_name}压低声音敲门：“{player_name}，明天咱们一起投{target_name}，别给他翻身机会。”"
        try:
            _start = AILogger.start_timer()
            response = await create_deepseek_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.85,
                max_tokens=260,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            story = re.sub(r"<[^>]+>", "", raw).strip() or fallback_story
            AILogger.log_call(
                call_type="NIGHT_VISITOR_PROPOSAL",
                context={"npc": npc_id, "target": target_id, "day": day},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=story,
                status="success",
                elapsed_ms=AILogger.elapsed_since(_start),
            )
            return {"success": True, "target_id": target_id, "story_text": story}
        except Exception as e:
            AILogger.log_call(
                call_type="NIGHT_VISITOR_PROPOSAL",
                context={"npc": npc_id, "target": target_id, "day": day},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback_story,
                status="fallback",
                elapsed_ms=0,
            )
            return {"success": False, "target_id": target_id, "story_text": fallback_story}

    @staticmethod
    async def generate_all_visitor_proposals(
        visitors: list[str],
        npcs: dict,
        relationships: dict,
        memory,
        day: int,
        player_name: str,
    ) -> dict:
        if not visitors:
            return {}
        tasks = []
        for nid in visitors:
            npc = npcs.get(nid)
            if npc is None:
                continue
            tasks.append(
                NightAllianceSystem.generate_visitor_proposal(
                    npc_id=nid,
                    npc_name=npc.name,
                    npc_identity=DataLoader().get_npc_field(nid, "identity", ""),
                    player_name=player_name,
                    npcs=npcs,
                    relationships=relationships,
                    memory=memory,
                    day=day,
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output: dict[str, dict] = {}
        idx = 0
        for nid in visitors:
            npc = npcs.get(nid)
            if npc is None:
                continue
            data = results[idx]
            idx += 1
            if isinstance(data, Exception):
                target_id = NightAllianceSystem._best_vote_target_for_npc_v2(
                    nid,
                    relationships,
                    ["player"] + NightAllianceSystem._alive_npc_ids(npcs),
                    exclude_ids=["player"],
                )
                target_name = player_name if target_id == "player" else NightAllianceSystem._display_name(target_id)
                data = {
                    "success": False,
                    "target_id": target_id,
                    "story_text": f"{npc.name}在门外压低声音说：明天一起投{target_name}。",
                }
            output[nid] = {
                "target_id": str(data.get("target_id", "")),
                "story_text": str(data.get("story_text", "")).strip(),
            }
        return output

    @staticmethod
    async def handle_player_seeks_alliance(
        target_npc_id: str,
        vote_target_id: str,
        npc_alliances: list[tuple[str, str, str]],
        relationships: dict,
        memory,
        day: int,
        player_name: str,
        npcs: dict,
    ) -> dict:
        """玩家主动找NPC结盟。"""
        in_alliance = False
        for a, b, _ in npc_alliances:
            if target_npc_id in (a, b):
                in_alliance = True
                break
        npc_name = NightAllianceSystem._display_name(target_npc_id)
        if in_alliance:
            return {
                "success": False,
                "agreed": False,
                "message": f"{npc_name}的房间门紧闭着，里面似乎有说话声……",
            }

        vote_target_name = player_name if vote_target_id == "player" else NightAllianceSystem._display_name(vote_target_id)
        npc_identity = DataLoader().get_npc_field(target_npc_id, "identity", "")
        memory_rel = ""
        if memory:
            memory_rel = memory.build_memory_and_relations_text(
                target_npc_id,
                relationships,
                npcs,
                player_name=player_name,
                alive_only=True,
            )
        system_prompt = AIService.build_npc_worldview_system_prompt(
            npc_name=npc_name,
            npc_identity=npc_identity,
            npc_aim=DataLoader().get_npc_field(target_npc_id, "aim", ""),
            npc_memory_rel=memory_rel,
        )
        user_prompt = f"""{player_name}深夜来找你密谋，想拉你明天一起投{vote_target_name}。
请根据你的性格和你对{player_name}的看法决定是否同意。
严格按格式回复：
态度：同意/拒绝
回应：（一句话）"""

        try:
            _start = AILogger.start_timer()
            response = await create_deepseek_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=100,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).strip()
            agreed = "同意" in cleaned and "拒绝" not in cleaned
            reply = ""
            for line in cleaned.splitlines():
                ln = line.strip()
                if ln.startswith("回应") and ("：" in ln or ":" in ln):
                    sep = "：" if "：" in ln else ":"
                    reply = ln.split(sep, 1)[1].strip()
            if not reply:
                reply = "行，就这么办。" if agreed else "算了，我不掺和。"
            AILogger.log_call(
                call_type="NIGHT_SEEK_ALLIANCE",
                context={"npc": target_npc_id, "vote_target": vote_target_id, "day": day},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"{'同意' if agreed else '拒绝'}:{reply}",
                status="success",
                elapsed_ms=AILogger.elapsed_since(_start),
            )
        except Exception as e:
            agreed = False
            reply = "你这提议听着就不靠谱。"
            AILogger.log_call(
                call_type="NIGHT_SEEK_ALLIANCE",
                context={"npc": target_npc_id, "vote_target": vote_target_id, "day": day},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=f"拒绝:{reply}",
                status="fallback",
                elapsed_ms=0,
            )

        if memory:
            if agreed:
                memory.add_impression(
                    observer_id=target_npc_id,
                    target_id="player",
                    day=day,
                    impression_text=f"{player_name}深夜来找我密谋，想一起投{vote_target_name}，我同意了。",
                )
            else:
                memory.add_impression(
                    observer_id=target_npc_id,
                    target_id="player",
                    day=day,
                    impression_text=f"{player_name}深夜来找我密谋，我觉得不靠谱，拒绝了他。",
                )

        return {
            "success": True,
            "agreed": agreed,
            "message": reply,
            "target_npc_id": target_npc_id,
            "vote_target_id": vote_target_id,
            "vote_target_name": vote_target_name,
        }
