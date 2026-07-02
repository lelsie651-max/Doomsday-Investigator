import random

from .data_loader import DataLoader
from .models import BossState, NPCState


class VoteSystem:
    """
    投票系统（MVP版）。

    每日工作结束后，所有角色匿名投票选出"最可疑的人"。
    NPC投票基于怀疑度 + 性格倾向权重 + 随机扰动。
    MVP阶段不做派系逻辑。
    """

    NOISE_RANGE = (-10, 10)

    @staticmethod
    def calculate_npc_vote(
        npc: NPCState,
        relationships: dict[str, dict],
        alive_targets: list[str],
    ) -> str:
        if not alive_targets:
            return ""

        npc_rels = relationships.get(npc.id, {})
        vote_weights: dict[str, float] = {}

        for target_id in alive_targets:
            if target_id == npc.id:
                continue

            rel = npc_rels.get(target_id)
            if rel is None:
                suspicion = 20
                affinity = 0
            else:
                suspicion = rel.suspicion
                affinity = rel.affinity

            base_weight = suspicion - (affinity / 4.0)
            noise = random.randint(*VoteSystem.NOISE_RANGE)
            vote_weights[target_id] = base_weight + noise

        vote_weights = VoteSystem._apply_personality(npc, vote_weights, relationships)

        if not vote_weights:
            return random.choice(alive_targets)

        return max(vote_weights, key=vote_weights.get)

    @staticmethod
    def _apply_personality(
        npc: NPCState,
        weights: dict[str, float],
        relationships: dict[str, dict],
    ) -> dict[str, float]:
        npc_id = npc.id
        adjusted = dict(weights)
        strategy = str(DataLoader().get_npc_field(npc_id, "vote_strategy", "default")).strip()

        if strategy == "aggressive":
            for target_id in adjusted:
                adjusted[target_id] *= 1.5

        elif strategy == "avoid_top_pick":
            if adjusted:
                max_w = max(adjusted.values())
                min_w = min(adjusted.values())
                for target_id in adjusted:
                    if adjusted[target_id] == max_w:
                        adjusted[target_id] *= 0.5
                    elif adjusted[target_id] == min_w:
                        adjusted[target_id] *= 1.8

        elif strategy == "noisy":
            for target_id in adjusted:
                extra_noise = random.randint(-15, 15)
                adjusted[target_id] += extra_noise

        elif strategy == "grudge":
            npc_rels = relationships.get(npc_id, {})
            lowest_affinity_target = None
            lowest_affinity = 999
            for target_id in adjusted:
                rel = npc_rels.get(target_id)
                aff = rel.affinity if rel else 0
                if aff < lowest_affinity:
                    lowest_affinity = aff
                    lowest_affinity_target = target_id
            if lowest_affinity_target:
                adjusted[lowest_affinity_target] += 30

        return adjusted

    @staticmethod
    def calculate_boss_vote(
        boss: BossState,
        relationships: dict[str, dict],
        alive_targets: list[str],
    ) -> str:
        if not alive_targets:
            return ""

        boss_rels = relationships.get(boss.id, {})
        vote_weights: dict[str, float] = {}

        for target_id in alive_targets:
            rel = boss_rels.get(target_id)
            suspicion = rel.suspicion if rel else 20
            noise = random.randint(-3, 3)
            vote_weights[target_id] = suspicion + noise

        if not vote_weights:
            return random.choice(alive_targets)

        return max(vote_weights, key=vote_weights.get)

    @staticmethod
    def execute_full_vote(
        player_vote_target: str,
        npcs: dict[str, NPCState],
        boss: BossState,
        relationships: dict[str, dict],
        current_day: int = 1,
    ) -> dict:
        alive_targets = ["player"]
        for npc_id, npc in npcs.items():
            if npc.alive:
                alive_targets.append(npc_id)

        vote_record: dict[str, str] = {}
        vote_record["player"] = player_vote_target

        for npc_id, npc in npcs.items():
            if not npc.alive:
                continue
            npc_targets = [target for target in alive_targets if target != npc_id]
            vote = VoteSystem.calculate_npc_vote(npc, relationships, npc_targets)
            vote_record[npc_id] = vote

        boss_targets = list(alive_targets)
        boss_vote = VoteSystem.calculate_boss_vote(boss, relationships, boss_targets)
        vote_record["boss"] = boss_vote

        # ===== 第1天投票保护 =====
        # 第1天确保玩家最多获得1票，多余的票随机分散给其他人
        if current_day == 1:
            vote_record = VoteSystem._apply_day1_protection(
                vote_record, alive_targets
            )

        tally: dict[str, int] = {}
        for _, target_id in vote_record.items():
            tally[target_id] = tally.get(target_id, 0) + 1

        if not tally:
            return VoteSystem._empty_result(vote_record)

        highest_votes = max(tally.values())
        top_candidates = [candidate_id for candidate_id, count in tally.items() if count == highest_votes]
        is_tie = len(top_candidates) > 1

        return VoteSystem._build_result_from_record(
            vote_record, tally, npcs, boss, is_tie
        )

    @staticmethod
    def _build_result_from_record(
        vote_record: dict[str, str],
        tally: dict[str, int],
        npcs: dict[str, NPCState],
        boss: BossState,
        is_tie: bool,
    ) -> dict:
        """从既有vote_record+tally构建标准投票结果。"""
        highest_votes = max(tally.values()) if tally else 0
        if is_tie or not tally:
            target = None
            target_name = ""
        else:
            top_candidates = [candidate_id for candidate_id, count in tally.items() if count == highest_votes]
            target = top_candidates[0] if top_candidates else None
            target_name = VoteSystem._get_name(target, npcs) if target else ""

        vote_details = VoteSystem._build_vote_details(vote_record, npcs, boss)

        return {
            "vote_record": vote_record,
            "tally": tally,
            "highest_votes": highest_votes,
            "is_tie": is_tie,
            "target": target,
            "target_name": target_name,
            "player_eliminated": target == "player",
            "vote_details": vote_details,
        }

    @staticmethod
    def _get_name(character_id: str, npcs: dict[str, NPCState]) -> str:
        if character_id == "player":
            return "你"
        if character_id == "boss":
            return str(DataLoader().get_npc_field("boss", "name", "经理")).strip() or "经理"
        npc = npcs.get(character_id)
        return npc.name if npc else character_id

    @staticmethod
    def _build_vote_details(
        vote_record: dict[str, str],
        npcs: dict[str, NPCState],
        boss: BossState,
    ) -> list[dict]:
        details = []
        for voter_id, target_id in vote_record.items():
            voter_name = VoteSystem._get_name(voter_id, npcs)
            if voter_id == "boss":
                voter_name = str(DataLoader().get_npc_field("boss", "display_name", voter_name)).strip() or voter_name
            target_name = VoteSystem._get_name(target_id, npcs)

            details.append(
                {
                    "voter_id": voter_id,
                    "voter_name": voter_name,
                    "target_id": target_id,
                    "target_name": target_name,
                }
            )
        return details

    @staticmethod
    def _empty_result(vote_record: dict) -> dict:
        return {
            "vote_record": vote_record,
            "tally": {},
            "highest_votes": 0,
            "is_tie": True,
            "target": None,
            "target_name": "",
            "player_eliminated": False,
            "vote_details": [],
        }

    @staticmethod
    def _apply_day1_protection(
        vote_record: dict[str, str],
        alive_targets: list[str],
    ) -> dict[str, str]:
        """
        第1天投票保护：确保玩家最多获得1票。
        多余投给玩家的票悄悄改投其他人，唱票结果看起来完全自然。
        """
        # 统计投给玩家的NPC（不含玩家自己的票）
        voters_targeting_player = [
            voter_id for voter_id, target_id in vote_record.items()
            if target_id == "player" and voter_id != "player"
        ]

        if len(voters_targeting_player) <= 1:
            return vote_record  # 不需要干预

        # 保留第1个投玩家的，其余改投其他人
        protected = dict(vote_record)
        redirect_voters = voters_targeting_player[1:]

        # 可选的替代目标（排除玩家自己）
        other_targets = [t for t in alive_targets if t != "player"]
        if not other_targets:
            return vote_record  # 没有其他人可投，不干预

        for voter_id in redirect_voters:
            # 不能改成“投给自己”
            valid_targets = [t for t in other_targets if t != voter_id]
            if not valid_targets:
                continue
            protected[voter_id] = random.choice(valid_targets)

        return protected
