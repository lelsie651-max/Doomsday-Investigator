import random
from dataclasses import dataclass, field
from typing import Optional

from .data_loader import DataLoader
from .constants import *
from .enums import *
from .models import *


@dataclass
class GameState:
    """游戏主状态，Python 后端的单一真相源"""
    current_day: int = 1
    current_phase: GamePhase = GamePhase.TASK_SELECTION
    current_hour: int = 0
    game_over: bool = False
    game_result: Optional[str] = None

    player: PlayerState = field(default_factory=PlayerState)
    npcs: dict[str, NPCState] = field(default_factory=dict)
    boss: BossState = field(default_factory=BossState)

    relationships: dict[str, dict[str, Relationship]] = field(default_factory=dict)
    daily: DailyState = field(default_factory=DailyState)
    evidence_collected: list[RecordCard] = field(default_factory=list)

    @classmethod
    def new_game(cls) -> "GameState":
        """创建一局新游戏，初始化所有状态"""
        state = cls()

        state.player = PlayerState(
            gold=INITIAL_GOLD,
            battery=INITIAL_BATTERY,
        )
        state.player.name = random.choice(PLAYER_NAMES)
        for i in range(INITIAL_BLANK_RECORD_CARDS):
            state.player.record_cards.append(
                RecordCard(id=f"rc_{i+1:03d}")
            )

        dl = DataLoader()
        profiles = dl.get_all_npc_profiles()
        for npc_id, profile in profiles.items():
            if npc_id == "boss":
                continue
            state.npcs[npc_id] = NPCState(
                id=npc_id,
                name=str(profile.get("name", npc_id)).strip() or npc_id,
                species=str(profile.get("species", "未知物种")).strip() or "未知物种",
                personality=str(profile.get("personality", "未知性格")).strip() or "未知性格",
                vote_tendency=str(profile.get("vote_tendency", "随机应对")).strip() or "随机应对",
                hidden_goal=str(profile.get("hidden_goal", profile.get("aim", ""))).strip(),
                task_preferences=dict(profile.get("task_preferences", {
                    "office": 0.2,
                    "meeting": 0.2,
                    "warehouse": 0.2,
                    "pantry": 0.2,
                    "reception": 0.2,
                })),
            )
        boss_profile = profiles.get("boss", {})
        if boss_profile:
            state.boss.name = str(boss_profile.get("name", state.boss.name)).strip() or state.boss.name
            state.boss.species = str(boss_profile.get("species", state.boss.species)).strip() or state.boss.species

        state._init_relationships(dl.get_initial_relationships())
        return state

    def _init_relationships(self, initial_relationships: dict[tuple[str, str], tuple[int, int]]):
        """初始化所有角色间的关系"""
        character_ids = ["player", "boss"] + list(self.npcs.keys())
        for from_id in character_ids:
            self.relationships[from_id] = {}
            for to_id in character_ids:
                if from_id == to_id:
                    continue
                key = (from_id, to_id)
                if key in initial_relationships:
                    aff, sus = initial_relationships[key]
                    self.relationships[from_id][to_id] = Relationship(
                        affinity=aff,
                        suspicion=sus,
                    )
                else:
                    self.relationships[from_id][to_id] = Relationship(
                        affinity=DEFAULT_AFFINITY,
                        suspicion=DEFAULT_SUSPICION,
                    )
