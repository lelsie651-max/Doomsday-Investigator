"""
NPC daily_state 异步预生成服务

职责:
1. 每天开局为每个 NPC 异步预生成 daily_state
2. 基于:扩展档案(长期底色)+ 三层记忆(昨日事件)+ 关系账本 + 中期目标进度
3. 生成失败时回退到 fallback 模板
4. 所有调用走 AILogger 记录

设计原则:
- 不修改现有 NPCState / npc_profiles.json / memory_system 任何接口
- 数据独立存储在 npc_extended_profiles.json
- 输出 JSON 严格符合 schema,校验失败回退
- longterm_backstory 原样传递,不截断;max_tokens=2000 保证完整输出
- 不接受 AI 输出的 progress_change(进度规则在外层)
- 玩家姓名用 {player_name} 占位符,生成时替换为实际玩家名
"""

import json
from pathlib import Path
from typing import Optional

from .ai_service import DEEPSEEK_MODEL, create_deepseek_chat_completion
from .ai_logger import AILogger
from .prompt_registry import PromptRegistry

EXTENDED_PROFILES_PATH = Path(__file__).resolve().parent / "data" / "npc_extended_profiles.json"

# 关键参数
DAILY_STATE_MAX_TOKENS = 2000   # 防截断,留足余量
DAILY_STATE_TIMEOUT = 12         # 沿用项目标准
DAILY_STATE_TEMPERATURE = 0.9    # 创意类任务,高 temperature

PLAYER_NAME_PLACEHOLDER = "{player_name}"
DEFAULT_PLAYER_NAME = "调查员"


def _replace_player_placeholder_in_dict_keys(d: dict, player_name: str) -> dict:
    """把 dict 的 key 中的 {player_name} 占位符替换为实际玩家名。"""
    if not isinstance(d, dict):
        return {}
    return {
        str(k).replace(PLAYER_NAME_PLACEHOLDER, player_name): v
        for k, v in d.items()
    }


class DailyStateService:
    """daily_state 预生成服务"""

    _extended_profiles_cache: Optional[dict] = None

    @classmethod
    def _load_extended_profiles(cls) -> dict:
        """单例懒加载扩展档案"""
        if cls._extended_profiles_cache is None:
            with EXTENDED_PROFILES_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            cls._extended_profiles_cache = data.get("npcs", {})
        return cls._extended_profiles_cache

    @classmethod
    def get_npc_extended_profile(cls, npc_id: str) -> dict:
        """获取某 NPC 的扩展档案。返回空 dict 时表示该 NPC 未配置扩展档案。"""
        return cls._load_extended_profiles().get(npc_id, {})

    @classmethod
    async def generate_daily_state(
        cls,
        npc_id: str,
        day: int,
        yesterday_memories_text: str,
        relationship_snapshot_text: str,
        midterm_goal_current: dict,
        player_name: str = DEFAULT_PLAYER_NAME,
    ) -> dict:
        """
        生成某 NPC 在某天的 daily_state。

        参数:
            npc_id: NPC 标识
            day: 第几天(1-5)
            yesterday_memories_text: 昨天该 NPC 经历的关键事件(已翻译成人话)
            relationship_snapshot_text: 当前关系账本快照(已翻译成人话)
            midterm_goal_current: 当前中期目标(含进度)
            player_name: 玩家实际姓名(用于替换 {player_name} 占位符)
        """
        # 兜底:player_name 不能为空
        effective_player_name = (player_name or "").strip() or DEFAULT_PLAYER_NAME

        profile = cls.get_npc_extended_profile(npc_id)
        if not profile:
            return cls._build_fallback_response(npc_id, day, effective_player_name, reason="no_profile")

        _start = AILogger.start_timer()
        system_prompt = ""
        user_prompt = ""

        try:
            system_prompt = cls._build_system_prompt(profile, npc_id)
            user_prompt = cls._build_user_prompt(
                profile=profile,
                day=day,
                yesterday_memories_text=yesterday_memories_text,
                relationship_snapshot_text=relationship_snapshot_text,
                midterm_goal_current=midterm_goal_current,
                player_name=effective_player_name,
            )

            response = await create_deepseek_chat_completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=DAILY_STATE_TEMPERATURE,
                max_tokens=DAILY_STATE_MAX_TOKENS,
                timeout=DAILY_STATE_TIMEOUT,
            )
            raw = response.choices[0].message.content.strip()
            _elapsed = AILogger.elapsed_since(_start)

            parsed = cls._parse_and_validate(
                raw, profile, npc_id, day, midterm_goal_current, effective_player_name
            )

            AILogger.log_call(
                call_type="DAILY_STATE",
                context={
                    "npc": npc_id,
                    "day": day,
                    "goal_id": midterm_goal_current.get("id", ""),
                    "player_name": effective_player_name,
                },
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=parsed.get("status", "unknown"),
                status=parsed.get("status", "parse_error"),
                elapsed_ms=_elapsed,
            )
            return parsed

        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start)
            fallback = cls._build_fallback_response(
                npc_id, day, effective_player_name, reason=f"exception: {str(e)[:100]}"
            )
            AILogger.log_call(
                call_type="DAILY_STATE",
                context={
                    "npc": npc_id,
                    "day": day,
                    "goal_id": midterm_goal_current.get("id", ""),
                    "player_name": effective_player_name,
                },
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"EXCEPTION: {str(e)}",
                final_output="fallback",
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return fallback

    @classmethod
    def _build_system_prompt(cls, profile: dict, npc_id: str) -> str:
        """渲染 daily_state_generator_system 模板。longterm_backstory 原样传递。"""
        return PromptRegistry.render(
            "daily_state_generator_system",
            npc_id=npc_id,
            longterm_backstory=profile.get("longterm_backstory", ""),
            compressed_core=profile.get("longterm_compressed_core", ""),
            core_trauma=profile.get("core_trauma", ""),
            ultimate_motivation=profile.get("ultimate_motivation", ""),
            behavior_pattern=profile.get("behavior_pattern", ""),
        )

    @classmethod
    def _build_user_prompt(
        cls,
        profile: dict,
        day: int,
        yesterday_memories_text: str,
        relationship_snapshot_text: str,
        midterm_goal_current: dict,
        player_name: str,
    ) -> str:
        """渲染 daily_state_generator_user 模板。anchors_text 中的 {player_name} 占位符会被替换。"""
        concerns_text = "\n".join(
            f"- [{c['id']}] {c['title']} (情感权重: {c['emotional_weight']})"
            for c in profile.get("concerns_pool", [])
        )
        anchors_text = "\n".join(
            f"- {target}: {desc}"
            for target, desc in profile.get("relationship_anchors", {}).items()
        )
        # 替换关系锚点中的玩家姓名占位符
        anchors_text = anchors_text.replace(PLAYER_NAME_PLACEHOLDER, player_name)

        return PromptRegistry.render(
            "daily_state_generator_user",
            day=day,
            concerns_pool=concerns_text,
            relationship_anchors=anchors_text,
            yesterday_memories=yesterday_memories_text or "(昨天没什么特别的事)",
            relationship_snapshot=relationship_snapshot_text or "(关系平稳)",
            midterm_goal_id=midterm_goal_current.get("id", ""),
            midterm_goal_title=midterm_goal_current.get("title", "(无)"),
            midterm_goal_narrative=midterm_goal_current.get("narrative", ""),
            midterm_goal_progress=midterm_goal_current.get("progress", 0),
            midterm_goal_completion_hint=midterm_goal_current.get("completion_event_hint", ""),
        )

    @classmethod
    def _parse_and_validate(
        cls,
        raw: str,
        profile: dict,
        npc_id: str,
        day: int,
        midterm_goal: dict,
        player_name: str,
    ) -> dict:
        """
        解析 AI 返回的 JSON,校验字段合法性。
        校验规则:
          - concern_ids 必须在 pool 内 -> 否则该字段回退
          - midterm_goal_state.goal_id 必须匹配当前目标 -> 否则该字段回退
          - 不接受 AI 输出的 progress_change 字段(静默移除)
        """
        try:
            json_match = cls._extract_json(raw)
            data = json.loads(json_match)

            partial_fallback = False

            # 校验 1: concern_ids 必须在 pool 内
            valid_concern_ids = {c["id"] for c in profile.get("concerns_pool", [])}
            referenced = data.get("today_concerns", {}).get("concern_ids", [])
            invalid_concerns = [cid for cid in referenced if cid not in valid_concern_ids]

            if invalid_concerns:
                data["today_concerns"] = {
                    "concern_ids": [],
                    "narrative": "(牵挂池引用校验失败,沿用昨天状态)",
                }
                partial_fallback = True

            # 校验 2: midterm_goal_state.goal_id 必须匹配当前目标
            mg_state = data.get("midterm_goal_state", {})
            if mg_state.get("goal_id") and mg_state.get("goal_id") != midterm_goal.get("id"):
                data["midterm_goal_state"] = {
                    "goal_id": midterm_goal.get("id", ""),
                    "current_status": "状态校验失败,沿用昨天",
                    "today_intent": "",
                    "completion_signal": "",
                }
                partial_fallback = True

            # 校验 3: 不接受 AI 输出的 progress_change(静默移除)
            if isinstance(mg_state, dict) and "progress_change" in mg_state:
                del mg_state["progress_change"]

            data["status"] = "partial_fallback" if partial_fallback else "ai_generated"
            data["npc_id"] = npc_id
            data["day"] = day
            return data

        except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
            return cls._build_fallback_response(npc_id, day, player_name, reason="parse_error")

    @classmethod
    def _extract_json(cls, raw: str) -> str:
        """从 AI 回复中提取 JSON 部分(去掉 markdown 包裹等)"""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return raw[start : end + 1]
        return raw

    @classmethod
    def _build_fallback_response(
        cls,
        npc_id: str,
        day: int,
        player_name: str,
        reason: str = "",
    ) -> dict:
        """
        构建 fallback 响应。
        Demo 阶段只取 applicable_when="default" 的模板;情境匹配预留给未来。
        fallback 模板的 today_attitudes dict key 中的 {player_name} 占位符会被替换。
        """
        profile = cls.get_npc_extended_profile(npc_id)
        templates = profile.get("fallback_daily_state_templates", [])
        if not templates:
            return cls._emergency_fallback(npc_id, day, reason)

        chosen = next(
            (t for t in templates if t.get("applicable_when") == "default"),
            templates[0],
        )

        # 替换 today_attitudes dict key 中的占位符
        raw_attitudes = chosen.get("today_attitudes", {})
        inner_attitudes = _replace_player_placeholder_in_dict_keys(raw_attitudes, player_name)

        return {
            "npc_id": npc_id,
            "day": day,
            "status": "fallback_template",
            "fallback_reason": reason,
            "today_body": chosen.get("today_body", ""),
            "today_concerns": {
                "concern_ids": [],
                "narrative": chosen.get("today_concerns", ""),
            },
            "yesterday_residue": chosen.get("yesterday_residue", ""),
            "inner_attitudes_toward_others": inner_attitudes,
            "midterm_goal_state": {
                "goal_id": "",
                "current_status": "未知",
                "today_intent": "",
                "completion_signal": "",
            },
            "leakable_details": chosen.get(
                "leakable_details",
                {"passive": "", "observable": "", "scoutable": ""},
            ),
        }

    @classmethod
    def _emergency_fallback(cls, npc_id: str, day: int, reason: str) -> dict:
        """极端兜底:连模板都没有"""
        return {
            "npc_id": npc_id,
            "day": day,
            "status": "fallback_emergency",
            "fallback_reason": reason,
            "today_body": "状态平稳",
            "today_concerns": {"concern_ids": [], "narrative": "(无)"},
            "yesterday_residue": "(无)",
            "inner_attitudes_toward_others": {},
            "midterm_goal_state": {
                "goal_id": "",
                "current_status": "未知",
                "today_intent": "",
                "completion_signal": "",
            },
            "leakable_details": {"passive": "", "observable": "", "scoutable": ""},
        }
