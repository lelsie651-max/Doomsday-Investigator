"""
Agent决策服务 - 6个AI Agent的决策统一入口

职责：
1. NPC Agent选任务（5个同事并行）
2. 经理Agent规划巡视路线（PUA由实时分发器触发）
3. 投票Agent推理（在后续补丁中添加）
"""

import asyncio
import random
import re

from .ai_service import AIService, DEEPSEEK_MODEL, create_deepseek_chat_completion
from .ai_logger import AILogger
from .data_loader import DataLoader
from .memory_system import MemorySystem
from .models import NPCState, BossState


class AgentService:
    """Agent决策服务"""

    # ==========================================
    # P01: NPC Agent 选任务
    # ==========================================

    @staticmethod
    async def npc_select_tasks(
        npc: NPCState,
        day: int,
        task_list: list[dict],
        relationships: dict,
        npcs: dict,
        memory: MemorySystem,
        max_tasks: int = 5,
    ) -> dict:
        """
        单个NPC Agent选择今天的任务。

        参数:
            npc: NPC状态对象
            day: 当前天数
            task_list: 12个候选任务 [{"id": "task_xxx", "name": "处理客户询盘"}, ...]
            relationships: 全局关系表
            npcs: 全局NPC字典
            memory: 记忆系统
            max_tasks: 最多选几个（默认5）

        返回:
            {"success": bool, "task_ids": list[str], "reason": str}
        """
        identity = MemorySystem.get_identity(npc.id)
        aim = MemorySystem.get_aim(npc.id)
        memory_rel_text = (
            memory.build_memory_and_relations_text(
                npc.id, relationships, npcs, alive_only=True
            )
            if memory else ""
        )

        task_text = ""
        for i, t in enumerate(task_list):
            task_text += f"{i + 1}. {t['id']} {t['name']}\n"

        # 统一走世界观+身份+目标+记忆与关系的标准段（与 Act1/Act2/投票一致）。
        system_prompt = AIService.build_npc_worldview_system_prompt(
            npc_name=npc.name,
            npc_identity=identity,
            npc_aim=aim if aim else npc.hidden_goal,
            npc_memory_rel=memory_rel_text,
        )

        user_prompt = f"""今天是第{day}天。

你今天可选的工作任务如下（共{len(task_list)}个，你需要选{max_tasks}个）：
{task_text}
请根据你的性格和个人目标选择{max_tasks}个任务。
严格按以下格式回复，不要输出其他内容：
任务：task_id_1, task_id_2, task_id_3, task_id_4, task_id_5
理由：（一句话，用你的性格来说）"""

        try:
            _start = AILogger.start_timer()
            response = await create_deepseek_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                max_tokens=200,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            _elapsed = AILogger.elapsed_since(_start)

            result = AgentService._parse_task_selection(raw, task_list, max_tasks)

            AILogger.log_call(
                call_type="AGENT_TASK",
                context={"npc": npc.name, "day": day, "aim": aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=str(result["task_ids"]),
                status="success" if result["success"] else "parse_error",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            fallback = AgentService._fallback_task_selection(
                npc, task_list, max_tasks, str(e)
            )
            AILogger.log_call(
                call_type="AGENT_TASK",
                context={"npc": npc.name, "day": day, "aim": aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=str(fallback.get("task_ids", [])),
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return fallback

    @staticmethod
    def _parse_task_selection(raw: str, task_list: list[dict], max_tasks: int) -> dict:
        """解析NPC的任务选择回复"""
        valid_ids = {t["id"] for t in task_list}
        reason = ""

        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("理由") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                reason = line.split(sep, 1)[1].strip()
            elif line.startswith("任务") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                ids_part = line.split(sep, 1)[1].strip()
                task_ids = [tid.strip() for tid in re.split(r"[,，、\s]+", ids_part) if tid.strip()]
                # 过滤有效ID
                task_ids = [tid for tid in task_ids if tid in valid_ids]
                # 去重
                seen = set()
                unique = []
                for tid in task_ids:
                    if tid not in seen:
                        seen.add(tid)
                        unique.append(tid)
                task_ids = unique[:max_tasks]

                if len(task_ids) >= 3:  # 至少选了3个算成功
                    # 不够的随机补
                    while len(task_ids) < max_tasks:
                        remaining = [t["id"] for t in task_list if t["id"] not in seen]
                        if not remaining:
                            break
                        pick = random.choice(remaining)
                        task_ids.append(pick)
                        seen.add(pick)
                    return {"success": True, "task_ids": task_ids, "reason": reason}

        return {"success": False, "task_ids": [], "reason": ""}

    @staticmethod
    def _fallback_task_selection(npc, task_list, max_tasks, error):
        """降级：规则引擎随机选任务"""
        ids = [t["id"] for t in task_list]
        selected = random.sample(ids, min(max_tasks, len(ids)))
        dl = DataLoader()
        reason = dl.get_fallback(
            "f01_npc_task_reason",
            npc_id=npc.id,
        )
        if not reason:
            reason = f"（{npc.name}今天懒得想）"
        return {
            "success": False,
            "task_ids": selected,
            "reason": reason,
        }

    # ==========================================
    # P02: 经理Agent 规划
    # ==========================================

    @staticmethod
    async def boss_plan_day(
        boss: BossState,
        day: int,
        employee_schedule: str,
        relationships: dict,
        npcs: dict,
        memory: MemorySystem,
        player_name: str = "调查员",
        total_hours: int = 5,
    ) -> dict:
        """
        经理Agent规划今天的巡视路线。

        返回:
            {
                "success": bool,
                "patrol_rooms": list[str],  # 5个房间value
                "reason": str,
            }
        """
        boss_aim = MemorySystem.get_aim("boss")
        boss_name = str(DataLoader().get_npc_field("boss", "name", "经理")).strip() or "经理"
        boss_identity = MemorySystem.get_identity("boss")
        memory_rel_text = (
            memory.build_memory_and_relations_text(
                "boss",
                relationships,
                npcs,
                player_name=player_name,
                alive_only=True,
            )
            if memory else ""
        )

        # 经理段保持自身专属世界观（贪污的Boss剧情），不调用通用 helper。
        system_prompt = f"""你是{boss_name}，{boss_identity}
你收到绝密情报，一个专门查贪污的'末日调查员'卧底在了你手下的销售小组里！如果让他活着把证据带回总部，你私吞公款买纯金浴缸的事就彻底败露。
你的核心目标：{boss_aim if boss_aim else "维持控制并规避风险"}
{memory_rel_text}"""

        user_prompt = f"""今天是第{day}天。

今天员工们的工作安排：
{employee_schedule}

你需要规划今天的行程（共{total_hours}个小时）：
每个小时去哪个房间巡视（可选：主办公区、会议室、仓库、茶水间、接待区、经理办公室）。

严格按以下格式回复：
巡视：主办公区, 会议室, 仓库, 茶水间, 接待区
目的：（一句话）"""

        room_name_map = {
            "主办公区": "office", "办公区": "office",
            "会议室": "meeting",
            "仓库": "warehouse",
            "茶水间": "pantry",
            "接待区": "reception",
            "经理办公室": "boss_office",
            "office": "office",
            "meeting": "meeting",
            "warehouse": "warehouse",
            "pantry": "pantry",
            "reception": "reception",
            "boss_office": "boss_office",
        }
        try:
            _start = AILogger.start_timer()
            response = await create_deepseek_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                max_tokens=200,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            _elapsed = AILogger.elapsed_since(_start)

            result = AgentService._parse_boss_plan(
                raw, room_name_map, total_hours
            )

            AILogger.log_call(
                call_type="BOSS_PLAN",
                context={"day": day, "aim": boss_aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=str(result),
                status="success" if result["success"] else "parse_error",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            fallback = AgentService._fallback_boss_plan(total_hours, str(e))
            AILogger.log_call(
                call_type="BOSS_PLAN",
                context={"day": day, "aim": boss_aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=str(fallback),
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return fallback

    @staticmethod
    def _parse_boss_plan(raw, room_map, total_hours):
        """解析经理的规划回复"""
        patrol_rooms = []
        reason = ""

        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("巡视") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                parts = re.split(r"[,，、\s]+", line.split(sep, 1)[1].strip())
                for p in parts:
                    p = p.strip()
                    mapped = room_map.get(p, "") or room_map.get(p.lower(), "")
                    if mapped:
                        patrol_rooms.append(mapped)
            elif (line.startswith("理由") or line.startswith("目的")) and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                reason = line.split(sep, 1)[1].strip()

        # 补齐巡视路线
        all_rooms = ["office", "meeting", "warehouse", "pantry", "reception", "boss_office"]
        while len(patrol_rooms) < total_hours:
            patrol_rooms.append(random.choice(all_rooms))
        patrol_rooms = patrol_rooms[:total_hours]

        return {
            "success": len(patrol_rooms) == total_hours,
            "patrol_rooms": patrol_rooms,
            "reason": reason,
        }

    @staticmethod
    def _fallback_boss_plan(total_hours, error):
        """降级：随机巡视，不PUA"""
        rooms = ["office", "meeting", "warehouse", "pantry", "reception"]
        patrol = [random.choice(rooms) for _ in range(total_hours)]
        reason = DataLoader().get_fallback("f02_boss_patrol_reason")
        if not reason:
            reason = "（经理今天心情不好，随便逛逛）"
        return {
            "success": False,
            "patrol_rooms": patrol,
            "reason": reason,
        }

    # ==========================================
    # 批量调用：所有Agent并行选任务
    # ==========================================

    @staticmethod
    async def all_agents_select_tasks(
        npcs: dict[str, NPCState],
        boss: BossState,
        day: int,
        task_list: list[dict],
        player_tasks_summary: str,
        relationships: dict,
        memory: MemorySystem,
        player_name: str = "调查员",
        max_tasks: int = 5,
    ) -> dict:
        """
        仅经理Agent决策：根据已确定的员工排班规划巡视+PUA。

        返回:
            {
                "npc_selections": {},
                "boss_plan": {"patrol_rooms": [...], ...},
            }
        """
        # 老 BOSS_PLAN(巡视决策)已被 _invoke_boss_pua_planning(统一经理 Agent)取代,
        # 不再调用以避免冲突 + 节省 API 成本
        # boss_plan = await cls.boss_plan_day(...)  # 弃用
        boss_result = {"patrol_rooms": [], "reason": "deprecated_by_boss_pua_plan"}

        return {
            "npc_selections": {},
            "boss_plan": boss_result,
        }

    # ==========================================
    # P10: 投票Agent推理
    # ==========================================

    @staticmethod
    async def agent_vote(
        npc_id: str,
        npc_name: str,
        npc_identity: str,
        npc_aim: str,
        day: int,
        memory_relations_text: str,
        alive_names: list[str],
        player_name: str = "调查员",
    ) -> dict:
        """
        单个Agent投票推理。

        返回:
            {"success": bool, "target_name": str, "reason": str}
        """
        names_text = "、".join(alive_names)
        system_prompt = AIService.build_npc_worldview_system_prompt(
            npc_name=npc_name,
            npc_identity=npc_identity,
            npc_aim=npc_aim,
            npc_memory_rel="",
        )

        user_prompt = f"""今天是第{day}天,下班投票时间到了。

你对每个人的看法（同事关系与记忆）：
{memory_relations_text}

存活的同事：{names_text}

⚠️ 投票决策优先级（必读,严格按此顺序判断）：

【最高优先级 — 检查约定】
请你先扫一遍上面的记忆,看有没有出现下列任一情况:
1. "我和某人达成共识,明天一起投XX" — 这是你昨夜结盟时定下的约定
2. "某人同意跟我结盟,明天一起投XX" — 这是你主动邀请别人结盟达成的约定
3. "某人找我密谋,想一起投XX,我同意了" — 这是你昨夜被找上门同意的约定
4. "我成功敲诈到某人...让他必须投XX" — 你勒索别人时定的投票指令
5. "某人成功敲诈我...我必须投XX" — 你被勒索时被强制的投票目标

如果记忆里有以上任何一条,而且对方没有当天明显背叛你 — **请直接投给约定/胁迫指定的目标**。
违反约定会让对方在心里把你拉黑,明天他可能反过来对付你。

【次优先级 — 自由判断】
如果上面 5 条都没有出现在你的记忆里,再按你的怀疑度、性格、最近发生的事自由判断,投给你认为最可疑的那个人。

严格按以下格式回复(不要多余文字)：
投票：（一个人的名字,必须是存活同事中的一个）
理由：（10个字以内，搞笑幽默风格）

⚠️ 理由特别要求(必读!严禁违反):
- **禁止暴露你的真实动机** — 即使你在履约或被胁迫,理由也必须写得像"我真的怀疑这个人"
- **严禁出现以下表达**:"答应过的"/"和XX约好了"/"和XX说好了"/"被XX逼的"/"履约"/"约定"/"诚信"/"承诺"/"不得不"/"没办法"
- 履约或被胁迫时:**必须根据你对他的记忆虚构一个针对目标的具体怀疑** — 例如:
  - "他眼神就有问题"
  - "昨天偷偷瞄保险柜"
  - "鼻子嗅得太勤"
  - "她笑得不像个活人"
  - "藤蔓伸太长了"
- 想象你是个会演戏的人 — 理由要让其他同事**完全看不出你是按约定在投票**,以为你是真心怀疑这个目标""" 

        try:
            _start = AILogger.start_timer()
            response = await create_deepseek_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=100,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            _elapsed = AILogger.elapsed_since(_start)

            result = AgentService._parse_vote(raw, alive_names)

            AILogger.log_call(
                call_type="AGENT_VOTE",
                context={"npc": npc_name, "day": day, "aim": npc_aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"{result['target_name']}: {result['reason']}",
                status="success" if result["success"] else "parse_error",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            fallback_reason = DataLoader().get_fallback(
                "f08_vote_reason",
                npc_id=npc_id,
                default="（沉默）",
            )
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            fallback = {"success": False, "target_name": "", "reason": fallback_reason}
            AILogger.log_call(
                call_type="AGENT_VOTE",
                context={"npc": npc_name, "day": day, "aim": npc_aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=str(fallback),
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return fallback

    @staticmethod
    def _parse_vote(raw: str, alive_names: list[str]) -> dict:
        """解析投票回复"""
        target = ""
        reason = ""
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("投票") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                name = line.split(sep, 1)[1].strip()
                # 模糊匹配
                for alive in alive_names:
                    if alive in name or name in alive:
                        target = alive
                        break
                if not target:
                    target = name  # 原样保留，后续映射
            elif line.startswith("理由") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                reason = line.split(sep, 1)[1].strip()[:20]

        return {
            "success": bool(target),
            "target_name": target,
            "reason": reason or "（说不上来）",
        }

    # ==========================================
    # 批量投票
    # ==========================================

    @staticmethod
    async def all_agents_vote(
        npcs: dict[str, NPCState],
        boss: BossState,
        day: int,
        relationships: dict,
        memory: MemorySystem,
        alive_names: list[str],
        player_name: str = "调查员",
    ) -> dict:
        """
        所有Agent并行投票。

        返回:
            {npc_id: {"target_name": str, "reason": str}, "boss": {...}}
        """
        tasks = []
        agent_ids = []

        for npc_id, npc in npcs.items():
            if not npc.alive:
                continue
            agent_ids.append(npc_id)
            memory_rel_text = (
                memory.build_memory_and_relations_text(
                    npc_id,
                    relationships,
                    npcs,
                    player_name=player_name,
                    alive_only=True,
                )
                if memory else
                MemorySystem.build_relationship_text(npc_id, relationships, npcs)
            )
            identity_full = MemorySystem.get_identity(npc_id)
            npc_aim = MemorySystem.get_aim(npc_id)
            tasks.append(AgentService.agent_vote(
                npc_id, npc.name, identity_full, npc_aim, day,
                memory_rel_text, alive_names, player_name,
            ))

        # 经理也投票
        agent_ids.append("boss")
        boss_rel_text = (
            memory.build_memory_and_relations_text(
                "boss",
                relationships,
                npcs,
                player_name=player_name,
                alive_only=True,
            )
            if memory else
            MemorySystem.build_relationship_text("boss", relationships, npcs)
        )
        boss_vote_name = str(DataLoader().get_npc_field("boss", "display_name", DataLoader().get_npc_field("boss", "name", "经理"))).strip() or "经理"
        boss_vote_identity = MemorySystem.get_identity("boss")
        tasks.append(AgentService.agent_vote(
            "boss", boss_vote_name,
            boss_vote_identity,
            MemorySystem.get_aim("boss"),
            day, boss_rel_text, alive_names, player_name,
        ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        vote_results = {}
        for i, agent_id in enumerate(agent_ids):
            r = results[i]
            if isinstance(r, Exception):
                r = {"success": False, "target_name": "", "reason": "（沉默）"}
            vote_results[agent_id] = r

        return vote_results
