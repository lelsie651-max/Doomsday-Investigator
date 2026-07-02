"""
AI 服务层 - DeepSeek API 调用封装

职责：
1. 管理API连接和配置
2. 拼接Prompt模板
3. 调用DeepSeek生成单Agent文本
4. 解析AI响应提取结构化数据
5. 支持单人/双人（玩家+1 NPC）流程
"""

import os
import sys
import json
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from .ai_logger import AILogger
from .config_loader import (
    COMBO_TONE_CONFIG,
    normalize_room_key,
)
from .data_loader import DataLoader
from .prompt_registry import PromptRegistry

# 加载.env文件
# 兼容开发环境和 PyInstaller 打包环境
if getattr(sys, "frozen", False):
    # PyInstaller 打包后:.env 应该和 server.exe 同级
    _env_path = Path(sys.executable).parent / ".env"
else:
    # 开发环境:.env 在项目根目录(backend/ 上一级)
    _env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 创建异步客户端
_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    max_retries=0,   # 禁用自动重试,12秒超时后直接走 fallback
    timeout=12.0,    # 单次请求超时(秒)
)

COMBO_TONE = COMBO_TONE_CONFIG


class AIService:
    """DeepSeek AI 调用服务"""
    @staticmethod
    def build_npc_worldview_system_prompt(
        *,
        npc_name: str,
        npc_identity: str,
        npc_aim: str,
        npc_memory_rel: str = "",
    ) -> str:
        """统一的NPC世界观+身份+利害关系+目标段落，供Act1/Act2/投票共用。"""
        core = PromptRegistry.render(
            "npc_worldview_system_core",
            npc_name=npc_name,
            npc_identity=npc_identity,
            npc_aim=npc_aim if npc_aim else "（暂无明确目标）",
        )
        if npc_memory_rel:
            return f"{core}\n{npc_memory_rel}"
        return core

    @staticmethod
    def _parse_negotiation_response(raw_text: str, context: dict) -> dict:
        """
        通用解析器。祈求和勒索共用此方法。

        参数 context 必须包含:
            - "kind": "plea" 或 "extortion" (区分中文 key)
            - "amount_min": int
            - "amount_max": int
            - "available_targets":
                - 祈求时支持 list[dict] ({"id": "...", "name": "..."})
                  或 list[str]（兼容旧数据）
                - 勒索时是投票目标 NPC 显示名列表 list[str]

        返回:
        {
            "agree": bool,           # AI 是否决定祈求/勒索
            "method": str,           # "金钱" / "黑料" / "投票" / "无"
            "amount": int,           # 金钱金额(已 clamp)
            "target": str,           # 黑料对象 ID / 投票目标显示名
            "summary": str,          # 黑料内容(仅祈求+黑料时)
            "story": str,            # AI 生成的台词
            "_parse_failed": bool,   # 解析是否失败(失败时上层走 fallback)
        }
        """
        import json
        import re

        # 默认返回(解析失败时的安全值)
        default_result = {
            "agree": False,
            "method": "无",
            "amount": 0,
            "target": "",
            "summary": "",
            "story": "",
            "memory_text": "",
            "_parse_failed": False,
        }

        if not raw_text or not isinstance(raw_text, str):
            default_result["_parse_failed"] = True
            return default_result

        # DeepSeek 偶尔会带 ```json 标记或解释文字,做温和清理
        cleaned = raw_text.strip()
        # 去掉可能的 ```json ... ``` 包裹
        if "```" in cleaned:
            # 提取 ``` 之间的内容
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()
            else:
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        # 去掉非 JSON 前缀(比如 AI 偶尔会写"好的,以下是回复:")
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            cleaned = cleaned[first_brace: last_brace + 1]

        # ===== 中文标点清洗(防 DeepSeek 用中文引号导致 JSON 解析失败) =====
        # AI 偶尔会在生成 JSON 时把双引号写成中文版,直接替换为 ASCII 双引号。
        # 注意:只在"字符串外层"做替换风险高(可能误替换台词内容),
        # 但实际上 DeepSeek 通常只在 JSON 结构层用错,所以全文替换也基本安全。
        # 这套替换覆盖最常见的错误用法。
        cleaned = (
            cleaned
            .replace("\u201C", '"')  # 中文左双引号 "
            .replace("\u201D", '"')  # 中文右双引号 "
            .replace("\u2018", "'")  # 中文左单引号 '
            .replace("\u2019", "'")  # 中文右单引号 '
            .replace("\uFF1A", ":")  # 中文冒号 :
            .replace("\uFF0C", ",")  # 中文逗号 ,
        )
        # 注: 只替换 JSON 结构相关的标点,不动其他中文内容(如换行符、空格)。

        kind = str(context.get("kind", "")).strip().lower()
        amount_min = int(context.get("amount_min", 10))
        amount_max = int(context.get("amount_max", 80))
        available_targets = list(context.get("available_targets", []) or [])

        # 中文 key 兼容
        if kind == "plea":
            agree_key = "是否祈求"
            method_key = "祈求方式"
            amount_key = "金钱金额"
            target_key = "黑料对象"
            summary_key = "黑料内容"
            story_key = "祈求台词"
        elif kind == "extortion":
            agree_key = "是否勒索"
            method_key = "勒索方式"
            amount_key = "金钱金额"
            target_key = "投票目标"
            summary_key = ""  # 勒索没有 summary 字段
            story_key = "勒索台词"
        else:
            default_result["_parse_failed"] = True
            return default_result

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            # 宽松兜底：当台词里出现未转义引号时，严格 JSON 解析会失败。
            # 这里尽量提取关键字段，避免整段回退。
            def _extract_text_field(key: str) -> str:
                pattern = rf'"{re.escape(key)}"\s*:\s*"([^"\r\n]*)"'
                match = re.search(pattern, cleaned)
                return str(match.group(1)).strip() if match else ""

            def _extract_int_field(key: str, default: int = 0) -> int:
                pattern = rf'"{re.escape(key)}"\s*:\s*(-?\d+)'
                match = re.search(pattern, cleaned)
                if not match:
                    return default
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    return default

            def _extract_story_field(key: str) -> str:
                # story 通常是最后一个字段，允许内部出现未转义双引号。
                pattern_last = rf'"{re.escape(key)}"\s*:\s*"(.*)"\s*\}}\s*$'
                match_last = re.search(pattern_last, cleaned, re.DOTALL)
                if match_last:
                    return str(match_last.group(1)).strip()
                # 兜底：普通字符串提取（不跨行）
                return _extract_text_field(key)

            loose_data: dict[str, object] = {}
            agree_val = _extract_text_field(agree_key)
            method_val = _extract_text_field(method_key)
            target_val = _extract_text_field(target_key)
            story_val = _extract_story_field(story_key)
            amount_val = _extract_int_field(amount_key, 0)
            summary_val = _extract_text_field(summary_key) if summary_key else ""
            memory_val = _extract_text_field("记忆")

            if agree_val:
                loose_data[agree_key] = agree_val
            if method_val:
                loose_data[method_key] = method_val
            loose_data[amount_key] = amount_val
            if target_val:
                loose_data[target_key] = target_val
            if summary_key:
                loose_data[summary_key] = summary_val
            if story_val:
                loose_data[story_key] = story_val
            if memory_val:
                loose_data["记忆"] = memory_val

            if not loose_data:
                default_result["_parse_failed"] = True
                default_result["story"] = raw_text[:200]  # 保留原文用于 fallback 显示
                return default_result
            data = loose_data

        # 兼容大小写/英文备选
        agree_raw = str(data.get(agree_key, data.get("agree", "否"))).strip()
        is_agree = agree_raw in ("是", "yes", "Y", "y", "true", "True")

        story = str(data.get(story_key, data.get("story", ""))).strip()
        memory_text = str(data.get("记忆", "")).strip()

        if not is_agree:
            return {
                "agree": False,
                "method": "无",
                "amount": 0,
                "target": "",
                "summary": "",
                "story": story,
                "memory_text": memory_text,
                "_parse_failed": False,
            }

        method = str(data.get(method_key, data.get("method", "无"))).strip()

        # 金钱方式: clamp 数额
        if method == "金钱":
            try:
                amount = int(data.get(amount_key, 0) or 0)
            except (TypeError, ValueError):
                amount = 0
            amount = max(amount_min, min(amount, amount_max))
            return {
                "agree": True,
                "method": "金钱",
                "amount": amount,
                "target": "",
                "summary": "",
                "story": story,
                "memory_text": memory_text,
                "_parse_failed": False,
            }

        # 黑料方式(仅祈求): 校验 target 合法
        if method == "黑料" and kind == "plea":
            target = str(data.get(target_key, "")).strip()
            summary = str(data.get(summary_key, "")).strip()[:80]  # 限长

            # 兼容 AI 回 "阿花"（姓名）或 "ahua"（ID）
            # 统一映射为 NPC ID 返回给上层。
            name_or_id_to_id: dict[str, str] = {}
            for item in available_targets:
                if isinstance(item, dict):
                    tid = str(item.get("id", "")).strip()
                    tname = str(item.get("name", "")).strip()
                    if tid:
                        name_or_id_to_id[tid] = tid
                    if tname and tid:
                        name_or_id_to_id[tname] = tid
                else:
                    raw = str(item).strip()
                    if raw:
                        name_or_id_to_id[raw] = raw

            resolved_target = name_or_id_to_id.get(target, "")
            if not resolved_target and target:
                # 温和兜底: 忽略前后空格后再比较一次
                compact = target.replace(" ", "")
                for k, v in name_or_id_to_id.items():
                    if k.replace(" ", "") == compact:
                        resolved_target = v
                        break

            if not resolved_target:
                # target 不合法,降级为不祈求
                return {
                    "agree": False,
                    "method": "无",
                    "amount": 0,
                    "target": "",
                    "summary": "",
                    "story": story,
                    "memory_text": memory_text,
                    "_parse_failed": False,
                }
            return {
                "agree": True,
                "method": "黑料",
                "amount": 0,
                "target": resolved_target,
                "summary": summary,
                "story": story,
                "memory_text": memory_text,
                "_parse_failed": False,
            }

        # 投票方式(仅勒索): 校验 target 合法
        if method == "投票" and kind == "extortion":
            target = str(data.get(target_key, "")).strip()
            if target not in available_targets:
                return {
                    "agree": False,
                    "method": "无",
                    "amount": 0,
                    "target": "",
                    "summary": "",
                    "story": story,
                    "memory_text": memory_text,
                    "_parse_failed": False,
                }
            return {
                "agree": True,
                "method": "投票",
                "amount": 0,
                "target": target,
                "summary": "",
                "story": story,
                "memory_text": memory_text,
                "_parse_failed": False,
            }

        # method == "无" 或非法值 → 返回不同意
        return {
            "agree": False,
            "method": "无",
            "amount": 0,
            "target": "",
            "summary": "",
            "story": story,
            "memory_text": memory_text,
            "_parse_failed": False,
        }

    @staticmethod
    async def generate_npc_plea(
        npc_profile: dict,
        npc_name: str,
        npc_identity: str,
        npc_aim: str,
        npc_memory_rel: str,
        player_name: str,
        room_name: str,
        task_text: str,
        act1_text: str,
        accident_text: str,
        amount_min: int,
        amount_max: int,
        cash_available: bool,
        available_blackmail_targets: list[dict],
        npc_id: str = "",
        event_recap: str = "",
    ) -> dict:
        """
        Act2 结算后,fear ≥ 70 时调用此方法让 NPC 祈求玩家。
        AI 完全自主决定是否祈求、用钱还是黑料、出多少。

        参数:
            npc_profile: NPC 配置(来自 npc_profiles.json)
            npc_name/npc_identity/npc_aim/npc_memory_rel: 用于构建世界观 system prompt
            player_name: 玩家名
            room_name: 当前房间中文名
            task_text: 当前任务描述
            act1_text: Act1 已生成的剧情文本
            accident_text: 突发状况描述(NPC 是当事人)
            amount_min/amount_max: 系统计算好的金额范围
            cash_available: NPC 钱够不够(False 时屏蔽"用钱"选项)
            available_blackmail_targets: 可作为黑料对象的 NPC 列表
                格式: [{"id": "xiaoli", "name": "小李"}, ...]

        返回:
            {
                "agree": bool,
                "method": "金钱" / "黑料" / "无",
                "amount": int,
                "target_id": str,        # 黑料对象 NPC ID
                "summary": str,          # 黑料内容
                "story": str,            # 祈求台词
                "raw_response": str,
                "status": "success" / "fallback",
            }
        """
        dl = DataLoader()
        npc_identity_2p = dl.get_npc_identity_2p(npc_id) if npc_id else npc_identity
        npc_aim_2p = dl.get_npc_aim_2p(npc_id) if npc_id else npc_aim
        npc_memory_rel_2p = (npc_memory_rel or "").replace(
            f"{npc_name}的记忆与对其他同事的看法:",
            "你对周围同事的看法和记忆:",
        ).replace(
            f"{npc_name}的记忆与对其他同事的看法：",
            "你对周围同事的看法和记忆:",
        )
        effective_recap = (event_recap or "").strip() or (act1_text or "")

        # 构建可见的黑料对象列表(仅显示姓名，减少 AI 输出 ID 的概率)
        blackmail_targets_display = ", ".join(
            str(t.get("name", t.get("id", ""))).strip() for t in available_blackmail_targets
        ) if available_blackmail_targets else "(暂无可选对象)"

        # cash_option_block 根据 cash_available 切换文案
        if cash_available:
            cash_block = f"你可以出 {amount_min} 到 {amount_max} 金币(根据你目前手头的钱)。"
        else:
            cash_block = f"你目前囊中羞涩,手头的钱不足以让「{player_name}」满意。这条路走不通,只能选其他方式。"

        # System Prompt: NPC演员人格
        system_prompt = PromptRegistry.render(
            "act2_actor_system",
            npc_name=npc_name,
            npc_identity_2p=npc_identity_2p,
            npc_aim_2p=npc_aim_2p if npc_aim_2p else "(暂无明确目标)",
            memory_and_relations=npc_memory_rel_2p,
        )

        # User Prompt: 祈求情境
        user_prompt = PromptRegistry.render(
            "negotiation_plea_actor_user_prompt",
            npc_name=npc_name,
            player_name=player_name,
            event_recap=effective_recap,
            cash_block=cash_block,
            blackmail_targets_display=blackmail_targets_display,
            amount_min=amount_min,
            amount_max=amount_max,
        )

        fallback_result = {
            "agree": False,
            "method": "无",
            "amount": 0,
            "target_id": "",
            "summary": "",
            "story": f"你看到{npc_name}想说什么但又咽了回去,转过身去假装在整理文件。",
            "memory_text": "",
            "raw_response": "",
            "status": "fallback",
        }

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.85,
                max_tokens=600,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            _elapsed = AILogger.elapsed_since(_start)

            parsed = AIService._parse_negotiation_response(
                raw_text=raw,
                context={
                    "kind": "plea",
                    "amount_min": amount_min,
                    "amount_max": amount_max,
                    "available_targets": available_blackmail_targets,
                },
            )

            if parsed["_parse_failed"]:
                AILogger.log_call(
                    call_type="NPC_PLEA",
                    context={"npc": npc_name, "room": room_name},
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    raw_reply=raw,
                    final_output="parse_failed → fallback",
                    status="fallback",
                    elapsed_ms=_elapsed,
                )
                return fallback_result

            # 如果 cash_available=False 但 AI 还是选了金钱,降级为不祈求
            if parsed["method"] == "金钱" and not cash_available:
                parsed["agree"] = False
                parsed["method"] = "无"
                parsed["amount"] = 0

            result = {
                "agree": parsed["agree"],
                "method": parsed["method"],
                "amount": parsed["amount"],
                "target_id": parsed["target"],
                "summary": parsed["summary"],
                "story": parsed["story"] or fallback_result["story"],
                "memory_text": parsed.get("memory_text", ""),
                "raw_response": raw,
                "status": "success",
            }

            AILogger.log_call(
                call_type="NPC_PLEA",
                context={"npc": npc_name, "agree": result["agree"], "method": result["method"]},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"agree={result['agree']} method={result['method']} amount={result['amount']}",
                status="success",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            AILogger.log_call(
                call_type="NPC_PLEA",
                context={"npc": npc_name, "room": room_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)[:100]}",
                final_output="exception → fallback",
                status="fallback",
                elapsed_ms=0,
            )
            return fallback_result

    @staticmethod
    async def generate_npc_extortion(
        npc_profile: dict,
        npc_name: str,
        npc_identity: str,
        npc_aim: str,
        npc_memory_rel: str,
        player_name: str,
        room_name: str,
        task_text: str,
        act1_text: str,
        accident_text: str,
        amount_min: int,
        amount_max: int,
        alive_npc_names: list[str],
        npc_id: str = "",
        event_recap: str = "",
    ) -> dict:
        """
        Act2 结算后,玩家是 negative 当事人时调用此方法让 NPC 决定是否勒索玩家。
        AI 完全自主决定是否勒索、要钱还是控制投票、出多少。

        参数:
            npc_profile/npc_name/npc_identity/npc_aim/npc_memory_rel: 用于构建世界观
            player_name/room_name/task_text/act1_text/accident_text: 当前情境
            amount_min/amount_max: 系统侧根据 NPC 的 extortion_price + 玩家钱包封顶计算好的范围
            alive_npc_names: 今晚还活着的同事显示名列表(不含玩家、不含该 NPC 自己)

        返回:
            {
                "agree": bool,
                "method": "金钱" / "投票" / "无",
                "amount": int,
                "target_name": str,      # 投票目标显示名
                "story": str,            # 勒索台词
                "raw_response": str,
                "status": "success" / "fallback",
            }
        """
        dl = DataLoader()
        npc_identity_2p = dl.get_npc_identity_2p(npc_id) if npc_id else npc_identity
        npc_aim_2p = dl.get_npc_aim_2p(npc_id) if npc_id else npc_aim
        npc_memory_rel_2p = (npc_memory_rel or "").replace(
            f"{npc_name}的记忆与对其他同事的看法:",
            "你对周围同事的看法和记忆:",
        ).replace(
            f"{npc_name}的记忆与对其他同事的看法：",
            "你对周围同事的看法和记忆:",
        )
        effective_recap = (event_recap or "").strip() or (act1_text or "")

        alive_npcs_display = "、".join(alive_npc_names) if alive_npc_names else "(暂无可选目标)"

        # System Prompt: NPC演员人格
        system_prompt = PromptRegistry.render(
            "act2_actor_system",
            npc_name=npc_name,
            npc_identity_2p=npc_identity_2p,
            npc_aim_2p=npc_aim_2p if npc_aim_2p else "(暂无明确目标)",
            memory_and_relations=npc_memory_rel_2p,
        )

        # User Prompt: 勒索情境(注意:不暴露 greed/钱包等数值)
        user_prompt = PromptRegistry.render(
            "negotiation_extortion_actor_user_prompt",
            npc_name=npc_name,
            player_name=player_name,
            event_recap=effective_recap,
            amount_min=amount_min,
            amount_max=amount_max,
            alive_npcs_display=alive_npcs_display,
        )

        fallback_result = {
            "agree": False,
            "method": "无",
            "amount": 0,
            "target_name": "",
            "story": f"你注意到{npc_name}似乎想说什么,但他终究没说出口,转身忙自己的事去了。",
            "memory_text": "",
            "raw_response": "",
            "status": "fallback",
        }

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.85,
                max_tokens=600,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            _elapsed = AILogger.elapsed_since(_start)

            parsed = AIService._parse_negotiation_response(
                raw_text=raw,
                context={
                    "kind": "extortion",
                    "amount_min": amount_min,
                    "amount_max": amount_max,
                    "available_targets": alive_npc_names,
                },
            )

            if parsed["_parse_failed"]:
                AILogger.log_call(
                    call_type="NPC_EXTORTION",
                    context={"npc": npc_name, "room": room_name},
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    raw_reply=raw,
                    final_output="parse_failed → fallback",
                    status="fallback",
                    elapsed_ms=_elapsed,
                )
                return fallback_result

            result = {
                "agree": parsed["agree"],
                "method": parsed["method"],
                "amount": parsed["amount"],
                "target_name": parsed["target"],
                "story": parsed["story"] or fallback_result["story"],
                "memory_text": parsed.get("memory_text", ""),
                "raw_response": raw,
                "status": "success",
            }

            AILogger.log_call(
                call_type="NPC_EXTORTION",
                context={"npc": npc_name, "agree": result["agree"], "method": result["method"]},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"agree={result['agree']} method={result['method']} amount={result['amount']} target={result['target_name']}",
                status="success",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            AILogger.log_call(
                call_type="NPC_EXTORTION",
                context={"npc": npc_name, "room": room_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)[:100]}",
                final_output="exception → fallback",
                status="fallback",
                elapsed_ms=0,
            )
            return fallback_result

    @staticmethod
    async def generate_boss_pua_plan(
        boss_identity: str,
        boss_aim: str,
        boss_relations_text: str,
        last_pua_target_name: str,
        recent_memories: list[str],
        candidates: list[dict],
        total_hours: int = 5,
    ) -> dict:
        """
        每天早上调用一次,让经理 AI 决定今日 PUA 计划。
        AI 完全自主决策:可以选择不 PUA(target=""),可以选择任何人(NPC 或玩家),可以选任意小时。

        返回:
        {
            "target_id": str,    # NPC ID 或 "player" 或 ""(今天不 PUA)
            "hour": int,         # 0-4 对应第 1-5 小时,-1 表示无
            "reason": str,       # AI 内部理由(日志用)
            "raw_response": str,
            "status": "success" / "fallback",
        }
        """
        candidate_names = ", ".join(
            str(c.get("name", "")).strip()
            for c in candidates
            if isinstance(c, dict) and str(c.get("name", "")).strip()
        ) if candidates else "(无可选目标)"
        candidate_names_with_ids = ", ".join(
            f"{str(c.get('name', '')).strip()}({str(c.get('id', '')).strip()})"
            for c in candidates
            if isinstance(c, dict)
            and str(c.get("name", "")).strip()
            and str(c.get("id", "")).strip()
        ) if candidates else "(无可选目标)"

        last_pua_block = ""
        if last_pua_target_name:
            last_pua_block = (
                f"\n昨天你 PUA 了「{last_pua_target_name}」,通常你会换一个目标"
                "(但也可以连续 PUA 同一个人,如果你认为有必要)。"
            )

        memories_block = ""
        if recent_memories:
            mem_lines = "\n".join(f"  - {m}" for m in recent_memories[-5:])
            memories_block = f"\n你最近的记忆:\n{mem_lines}"

        system_prompt = PromptRegistry.render(
            "boss_pua_plan_system_prompt",
            boss_identity=boss_identity,
            boss_aim=boss_aim,
        )
        user_prompt = f"""今天是新的一天,你需要决定今日完整行程(PUA 计划 + 其他时间巡视计划)。

你的员工和你的关系:
{boss_relations_text}
{memories_block}
{last_pua_block}

请基于你对每个员工的看法、最近发生的事、以及你的统治直觉,做出今日决策:

【决策 1: PUA 谁(可以选不 PUA)】
你今天要把谁叫进经理办公室"谈话"?
可选目标: {candidate_names_with_ids}
你也可以选择今天不 PUA 任何人(让员工松一口气,反而更容易暴露马脚)。

【决策 2: 第几小时 PUA】
公司一天工作 {total_hours} 个小时。
- 选择早(第 1-2 小时):打员工措手不及
- 选择中(第 2-3 小时):员工进入工作状态后打断
- 选择晚(第 4-5 小时):让员工担心一整天
- 不 PUA 时填 -1

【决策 3: 其他小时巡视哪里】
不 PUA 的其他小时,你要去哪些房间巡视?可选房间:
- 主办公区(office) / 会议室(meeting) / 仓库(warehouse) / 茶水间(pantry) / 接待区(reception)

提示:
- 你可以重复巡视同一房间(显示"持续监视")
- 选择员工最多的房间制造压迫感,或选择空房间偷偷查看(看你心情)
- PUA 那一小时(如果有)系统会自动安排在经理办公室,你不需要为那一小时填房间

请按以下 JSON 格式严格输出,不要多余文字、不要 ```json 标记:

{{
  "PUA目标": "<NPC 名字,或者空字符串(今天不 PUA)>",
  "PUA小时": <整数 1-{total_hours},不 PUA 时填 -1>,
  "巡视计划": ["<房间1>", "<房间2>", ...],
  "决策理由": "<2-3 句话说明 PUA 决定的理由>",
  "巡视目的": "<1 句话说明今日巡视策略>"
}}

注意事项:
1. 「PUA目标」只能填名字(从可选目标中选),不能填 ID。
2. 「巡视计划」必须填满 {total_hours} 个房间(对应 {total_hours} 个小时)。
   PUA 那一小时也要填一个房间(系统会自动改为"经理办公室",你的填写会被覆盖,
   但 JSON 格式要求每个数组元素不能空)。
3. 不 PUA 时(PUA目标=""),「巡视计划」依然是 {total_hours} 个房间——填满你的整个工作日。
4. 房间名只能用上述 5 个中文名,不要用英文 ID。
5. 你是克苏鲁经理,决策可以阴险、随性、看心情——别像个数据分析师。"""

        fallback_result = {
            "target_id": "",
            "hour": -1,
            "patrol_rooms": ["office"] * total_hours,
            "reason": "fallback: AI 调用失败,今日不 PUA",
            "patrol_purpose": "默认巡视",
            "raw_response": "",
            "status": "fallback",
        }

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.85,
                max_tokens=400,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            _elapsed = AILogger.elapsed_since(_start)

            cleaned = raw
            if "```" in cleaned:
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
                else:
                    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
            first_brace = cleaned.find("{")
            last_brace = cleaned.rfind("}")
            if first_brace >= 0 and last_brace > first_brace:
                cleaned = cleaned[first_brace: last_brace + 1]

            try:
                data = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                AILogger.log_call(
                    call_type="BOSS_PUA_PLAN",
                    context={"day": "next"},
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    raw_reply=raw,
                    final_output="json_parse_failed → fallback",
                    status="fallback",
                    elapsed_ms=_elapsed,
                )
                return fallback_result

            target_name = str(data.get("PUA目标", "")).strip().strip("「」\"'")
            try:
                hour_input = int(data.get("PUA小时", -1) or -1)
            except (TypeError, ValueError):
                hour_input = -1
            reason = str(data.get("决策理由", "")).strip()

            patrol_input = data.get("巡视计划", []) or []
            room_name_to_key = {
                "主办公区": "office",
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
            patrol_rooms = []
            for r in patrol_input[:total_hours]:
                key = room_name_to_key.get(str(r).strip(), "office")
                patrol_rooms.append(key)
            while len(patrol_rooms) < total_hours:
                patrol_rooms.append("office")

            patrol_purpose = str(data.get("巡视目的", "")).strip()

            name_to_id = {
                str(c.get("name", "")).strip(): str(c.get("id", "")).strip()
                for c in candidates
                if isinstance(c, dict)
                and str(c.get("name", "")).strip()
                and str(c.get("id", "")).strip()
            }
            target_id = name_to_id.get(target_name, "")
            if target_name and not target_id:
                hour_input = -1

            if target_id == "" or hour_input < 1 or hour_input > total_hours:
                target_id = ""
                hour_zero_based = -1
            else:
                hour_zero_based = hour_input - 1

            result = {
                "target_id": target_id,
                "hour": hour_zero_based,
                "patrol_rooms": patrol_rooms,
                "reason": reason,
                "patrol_purpose": patrol_purpose,
                "raw_response": raw,
                "status": "success",
            }

            AILogger.log_call(
                call_type="BOSS_PUA_PLAN",
                context={"target": target_id, "hour": hour_zero_based},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"target={target_id} hour={hour_zero_based} reason={reason[:60]}",
                status="success",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            AILogger.log_call(
                call_type="BOSS_PUA_PLAN",
                context={"day": "next"},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)[:100]}",
                final_output="exception → fallback",
                status="fallback",
                elapsed_ms=0,
            )
            return fallback_result

    # ==========================================
    # Act 1：前置剧情生成（新）
    # ==========================================

    @staticmethod
    def _strip_seed_skeleton_labels(seed_text: str) -> str:
        """
        清洗 assembled_seed 的骨架标签,让 Act1 fallback 文本看起来像自然剧情。
        - 去掉行首"场景核心:""冲突点:""升级:""结尾困境:"等标签(中英冒号都支持)
        - 去掉最后那行"当前只有X和玩家两人在场。"调度信息
        - 空行也去掉
        """
        if not seed_text:
            return ""

        label_pattern = re.compile(r"^\s*(?:场景核心|冲突点|升级|结尾困境)\s*[:：]\s*")
        bystander_pattern = re.compile(r"^当前只有.+?和玩家两人在场。?\s*$")

        cleaned_lines = []
        for line in str(seed_text).split("\n"):
            line = line.strip()
            if not line:
                continue
            if bystander_pattern.match(line):
                continue
            line = label_pattern.sub("", line).strip()
            if line:
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    @staticmethod
    async def generate_act1(
        assembled_seed: str,
        npc_infos: list[dict],
        primary_npc_name: str,
        room_name: str,
        player_name: str = "调查员",
        is_solo: bool = False,
        is_evidence_event: bool = False,
        evidence_hint: str = "",
        solo_task_name: str = "",
        solo_absurd_element: str = "",
        solo_workplace_element: str = "",
        solo_evidence_element: str = "本次事件无证据",
        duo_task_text: str = "",
        duo_absurd_element: str = "",
        duo_workplace_element: str = "",
        duo_random_accident: str = "",
        duo_random_condition: str = "",
    ) -> dict:
        """
        基于拼装好的seed生成Act 1小剧场（玩家出牌前的前置剧情）。

        参数:
            assembled_seed: 骨架+元素池拼装后的半成品seed
            npc_infos: 在场NPC信息列表（含identity/relationships/memories）
            primary_npc_name: 主角NPC名字
            room_name: 房间中文名
            is_evidence_event: 是否证据事件
            evidence_hint: 证据线索融入提示

        返回:
            {"success": bool, "act1_text": str, "raw_response": str}
        """
        evidence_block = ""
        if is_evidence_event and evidence_hint:
            evidence_block = f"\n【隐藏剧情要求】\n{evidence_hint}\n不要刻意点明，让NPC像是在闲聊、抱怨、吐槽中不小心说漏嘴。\n"

        # 兼容保留：
        # 当前主流程的单人事件 Act2 由 generate_solo_action_act2() 处理，
        # 常规不会走到这里；该分支仅用于“调用端传入 is_solo=True”的兜底路径，
        # 避免异常上下文（如空NPC）时整段Act2直接失败。
        if is_solo:
            absurd_element = str(solo_absurd_element or "过期食材").strip()
            workplace_element = str(solo_workplace_element or "降本增效").strip()
            evidence_element = str(solo_evidence_element or "本次事件不会出现任务公司的罪证").strip()
            task_text = str(solo_task_name or "例行工作").strip()
            system_prompt = PromptRegistry.render(
                "act1_solo_system_prompt",
                player_name=player_name,
            )
            user_prompt = PromptRegistry.render(
                "act1_solo_user_prompt",
                player_name=player_name,
                room_name=room_name,
                task_text=task_text,
                absurd_element=absurd_element,
                workplace_element=workplace_element,
                evidence_element=evidence_element,
            )

        else:
            # 双人场景：玩家 + 1个NPC
            npc = npc_infos[0] if npc_infos else {}
            npc_name = npc.get("name", primary_npc_name or "NPC")
            npc_identity = npc.get("identity", "未知NPC")
            npc_aim = npc.get("aim", "")
            npc_memory_rel = str(npc.get("memory_and_relations", "")).strip()
            if not npc_memory_rel:
                npc_rel = npc.get("relationships", "")
                npc_mem = npc.get("memories", [])
                mem_text = "\n".join(f"  - {m}" for m in npc_mem[-5:]) if npc_mem else "  （暂无近期记忆）"
                npc_memory_rel = (
                    f"{npc_name}对其他同事的看法：\n"
                    f"{npc_rel if npc_rel else '（暂无明确关系）'}\n"
                    f"{npc_name}最近的记忆：\n{mem_text}"
                )
            task_text = str(duo_task_text or "处理当前工作").strip()
            random_accident = str(duo_random_accident or "").strip()
            # 风险倾向由系统侧决策器处理,不再写入给 AI 的提示词
            # Act1 开场完全由随机突发事件文本驱动
            if not random_accident:
                random_accident = (
                    f"{npc_name}和{player_name}在处理{task_text}时出现了一段容易引发误会的插曲。"
                )

            example_text = DataLoader().get_random_act1_example()
            if not example_text:
                example_text = "(无可用示例,请发挥)"

            system_prompt = PromptRegistry.render(
                "act1_screenwriter_system",
                player_name=player_name,
                npc_name=npc_name,
                npc_identity=npc_identity,
                npc_aim=npc_aim if npc_aim else "(暂无明确目标)",
                memory_and_relations=npc_memory_rel,
            )

            user_prompt = PromptRegistry.render(
                "act1_screenwriter_user",
                npc_name=npc_name,
                player_name=player_name,
                room_name=room_name,
                task_text=task_text,
                random_accident=random_accident,
                example=example_text,
            )

        try:
            _start = AILogger.start_timer()
            max_tokens = 1200
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.95,
                max_tokens=max_tokens,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            # 清理可能的XML标签残留
            raw = re.sub(r"<[^>]+>", "", raw).strip()
            _elapsed = AILogger.elapsed_since(_start)

            AILogger.log_call(
                call_type="ACT1",
                context={"room": room_name, "primary": primary_npc_name, "aim": npc_aim if not is_solo else ""},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=raw,
                status="success",
                elapsed_ms=_elapsed,
            )
            return {"success": True, "act1_text": raw, "raw_response": raw}

        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            dl = DataLoader()
            room_key = normalize_room_key(room_name)
            cleaned_seed = AIService._strip_seed_skeleton_labels(assembled_seed)
            if is_solo:
                fallback_text = dl.get_fallback(
                    "f03_solo_act1",
                    room=room_key,
                    default=cleaned_seed,
                )
            else:
                fallback_text = cleaned_seed
            AILogger.log_call(
                call_type="ACT1",
                context={"room": room_name, "primary": primary_npc_name, "aim": npc_aim if not is_solo else ""},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback_text,
                status="fallback",
                elapsed_ms=_elapsed,
            )
            # 降级：直接使用拼装好的seed作为剧情文本
            return {
                "success": False,
                "act1_text": fallback_text,
                "raw_response": f"ACT1_FALLBACK: {str(e)[:100]}",
            }

    @staticmethod
    async def generate_event_recap(
        npc_name: str,
        player_name: str,
        act1_text: str,
    ) -> dict:
        """
        把 Act1 剧情压缩成 NPC 第一人称回忆,供 Act2 使用。

        返回:
            {"success": bool, "recap_text": str, "raw_response": str}

        失败 fallback:
            recap_text 直接返回 act1_text(原文降级,不阻塞游戏)。
        """
        system_prompt = ""
        user_prompt = ""
        try:
            system_prompt = PromptRegistry.render(
                "event_recap_system",
                npc_name=npc_name,
            )
            user_prompt = PromptRegistry.render(
                "event_recap_user",
                npc_name=npc_name,
                player_name=player_name,
                act1_text=act1_text,
            )
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=300,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r"<[^>]+>", "", raw).strip()
            if "```" in raw:
                raw = raw.replace("```json", "").replace("```", "").strip()
            _elapsed = AILogger.elapsed_since(_start)

            AILogger.log_call(
                call_type="EVENT_RECAP",
                context={"npc_name": npc_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=raw,
                status="success",
                elapsed_ms=_elapsed,
            )
            return {"success": True, "recap_text": raw, "raw_response": raw}

        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            fallback_text = f"我和{player_name}刚才有过一次接触,具体细节有点模糊。"
            AILogger.log_call(
                call_type="EVENT_RECAP",
                context={"npc_name": npc_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback_text,
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return {
                "success": False,
                "recap_text": fallback_text,
                "raw_response": f"RECAP_FALLBACK: {str(e)[:100]}",
            }

    @staticmethod
    async def generate_pua_memory_recap(
        target_name: str,
        full_pua_text: str,
    ) -> dict:
        """
        把 PUA 完整剧本压缩成 boss 和 target NPC 两个视角的第一人称记忆。

        返回:
            {
                "success": bool,
                "boss_memory": str,
                "target_memory": str,
                "raw_response": str,
            }

        失败 fallback:
            boss_memory / target_memory 各自回退到通用模板,不阻塞游戏。
        """
        fallback_boss = f"我把{target_name}叫进办公室盘问了一阵,他磕磕巴巴的样子让我心里有数。"
        fallback_target = "经理把我拉进办公室一顿审,触手在我眼前晃来晃去,我硬着头皮装傻应付了过去。"
        system_prompt = ""
        user_prompt = ""
        try:
            system_prompt = PromptRegistry.render("pua_memory_recap_system")
            user_prompt = PromptRegistry.render(
                "pua_memory_recap_user",
                target_name=target_name,
                full_pua_text=full_pua_text,
            )
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                max_tokens=300,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            cleaned = raw
            if "```" in cleaned:
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                cleaned = match.group()
            parsed = json.loads(cleaned)
            boss_memory = str(parsed.get("boss_memory", "")).strip()
            target_memory = str(parsed.get("target_memory", "")).strip()
            if not boss_memory or not target_memory:
                raise ValueError("missing boss_memory or target_memory in AI output")
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="PUA_MEMORY_RECAP",
                context={"target": target_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"boss={boss_memory[:30]} | target={target_memory[:30]}",
                status="success",
                elapsed_ms=_elapsed,
            )
            return {
                "success": True,
                "boss_memory": boss_memory,
                "target_memory": target_memory,
                "raw_response": raw,
            }
        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            AILogger.log_call(
                call_type="PUA_MEMORY_RECAP",
                context={"target": target_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=f"FALLBACK boss={fallback_boss[:30]}",
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return {
                "success": False,
                "boss_memory": fallback_boss,
                "target_memory": fallback_target,
                "raw_response": f"PUA_RECAP_FALLBACK: {str(e)[:100]}",
            }

    # ==========================================
    # Act 2：出牌后结局生成（新）
    # ==========================================

    @staticmethod
    async def generate_act2(
        npc_infos: list[dict],
        act1_text: str,
        room_name: str,
        task_text: str,
        emotion_card_name: str,
        emotion_card_tone: str,
        action_card_name: str,
        action_card_effect: str,
        combo_type: str,
        npc_reactions: dict,
        player_name: str = "调查员",
        is_solo: bool = False,
        evidence_hint: str = "",
    ) -> dict:
        """
        生成Act 2（玩家出牌后的结局剧情）。

        关键区别：NPC的态度由系统预设（thought字段），AI只需按预设态度写对话，
        不需要自行判断谁高兴谁生气。

        参数:
            npc_infos: NPC信息列表
            act1_text: Act 1的剧情文本（用于上下文）
            room_name: 房间中文名
            emotion_card_name: 玩家选的情绪卡名
            emotion_card_tone: 情绪卡语气方向
            action_card_name: 玩家选的行动卡名
            action_card_effect: 行动卡效果
            combo_type: 5档combo类型
            npc_reactions: resolve_npc_reactions()的返回值，含每个NPC的thought
            narrator_mood: 旁白基调（可选）

        返回:
            {"success": bool, "act2_text": str, "dialogues": dict, "narrator": str, "raw_response": str}
        """
        combo_tone = COMBO_TONE.get(combo_type, COMBO_TONE.get("contrast", ""))
        npc_aim = ""

        if is_solo:
            system_prompt = PromptRegistry.render(
                "act2_solo_system_prompt",
                player_name=player_name,
                combo_tone=combo_tone,
            )
            user_prompt = PromptRegistry.render(
                "act2_solo_user_prompt",
                room_name=room_name,
                player_name=player_name,
                act1_preview=act1_text[:200],
                emotion_card_name=emotion_card_name,
                emotion_card_tone=emotion_card_tone,
                action_card_name=action_card_name,
                action_card_effect=action_card_effect,
            )

        else:
            npc_name = npc_infos[0]["name"] if npc_infos else "NPC"
            npc_identity = npc_infos[0].get("identity", "未知身份") if npc_infos else "未知身份"
            npc_aim = npc_infos[0].get("aim", "") if npc_infos else ""
            dl = DataLoader()
            npc_id = npc_infos[0].get("id", "") if npc_infos else ""
            npc_identity_2p = dl.get_npc_identity_2p(npc_id) if npc_id else npc_identity
            npc_aim_2p = dl.get_npc_aim_2p(npc_id) if npc_id else npc_aim
            npc_memory_rel = str(npc_infos[0].get("memory_and_relations", "")).strip() if npc_infos else ""
            if not npc_memory_rel:
                npc_rel = npc_infos[0].get("relationships", "") if npc_infos else ""
                npc_mem = npc_infos[0].get("memories", []) if npc_infos else []
                mem_text = "\n".join(f"  - {m}" for m in npc_mem[-5:]) if npc_mem else "  （暂无近期记忆）"
                npc_memory_rel = (
                    f"{npc_name}对其他同事的看法：\n"
                    f"{npc_rel if npc_rel else '（暂无明确关系）'}\n"
                    f"{npc_name}最近的记忆：\n{mem_text}"
                )
            npc_memory_rel_2p = npc_memory_rel.replace(
                f"{npc_name}的记忆与对其他同事的看法:",
                "你对周围同事的看法和记忆:",
            ).replace(
                f"{npc_name}的记忆与对其他同事的看法：",
                "你对周围同事的看法和记忆:",
            )
            recap_result = await AIService.generate_event_recap(
                npc_name=npc_name,
                player_name=player_name,
                act1_text=act1_text,
            )
            event_recap = recap_result.get("recap_text") or act1_text

            evidence_hint_text = str(evidence_hint or "").strip()
            evidence_block = ""
            if evidence_hint_text:
                evidence_block = (
                    f"\n隐藏剧情要求(不展示给玩家,融入对话中):\n"
                    f"请在你的对话或旁白中,自然地暴露以下线索:{evidence_hint_text}\n"
                    f"不要刻意点明,像是聊天中不小心说漏嘴的。\n"
                )

            system_prompt = PromptRegistry.render(
                "act2_actor_system",
                npc_name=npc_name,
                npc_identity_2p=npc_identity_2p,
                npc_aim_2p=npc_aim_2p if npc_aim_2p else "(暂无明确目标)",
                memory_and_relations=npc_memory_rel_2p,
            )

            user_prompt = PromptRegistry.render(
                "act2_actor_user",
                npc_name=npc_name,
                player_name=player_name,
                event_recap=event_recap,
                emotion_card_name=emotion_card_name,
                emotion_card_tone=emotion_card_tone,
                action_card_name=action_card_name,
                action_card_effect=action_card_effect,
                evidence_block=evidence_block,
            )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=1000,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            result = AIService._parse_act2_response(raw, npc_infos)
            result["raw_response"] = raw
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="ACT2",
                context={"room": room_name, "combo": combo_type, "aim": npc_aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=result.get("act2_text", ""),
                status="success" if result["success"] else "parse_error",
                elapsed_ms=_elapsed,
            )
            return result

        except Exception as e:
            _elapsed = AILogger.elapsed_since(_start) if "_start" in locals() else 0
            result = AIService._fallback_act2(npc_infos, combo_type, str(e))
            AILogger.log_call(
                call_type="ACT2",
                context={"room": room_name, "combo": combo_type, "aim": npc_aim},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=result.get("act2_text", ""),
                status="fallback",
                elapsed_ms=_elapsed,
            )
            return result

    @staticmethod
    async def generate_pua_player_act1(
        boss_identity: str,
        pua_reason: str,
        boss_memory_relations: str,
        player_name: str,
    ) -> dict:
        """
        玩家被经理PUA时的Act1开场生成。
        """
        dl = DataLoader()
        boss_name = str(dl.get_npc_field("boss", "display_name", "鲍斯")).strip() or "鲍斯"
        boss_aim = str(dl.get_npc_field("boss", "aim", "")).strip() or "找出卧底，维持统治。"
        identity = str(boss_identity or "").strip() or str(dl.get_npc_identity("boss") or "").strip() or "未知身份"
        reason = str(pua_reason or "").strip() or "你需要通过施压进一步确认其真实立场。"
        memory_rel = str(boss_memory_relations or "").strip() or "（暂无可用记忆）"
        fallback_scene = dl.pick_pua_segments("player") or {}
        fallback_text = str(fallback_scene.get("opening_text", "")).strip() or str(
            fallback_scene.get("full_text", "")
        ).strip() or f"{boss_name}把{player_name}叫进办公室，八条触手同时敲击桌面，空气安静得像要被挤爆。"

        system_prompt = AIService.build_npc_worldview_system_prompt(
            npc_name=boss_name,
            npc_identity=identity,
            npc_aim=boss_aim,
            npc_memory_rel=memory_rel,
        )
        user_prompt = PromptRegistry.render(
            "pua_player_act1",
            boss_identity=identity,
            pua_reason=reason,
            boss_memory_relations=memory_rel,
            player_name=player_name,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.92,
                max_tokens=900,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).strip()
            text = cleaned or fallback_text
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="PUA_PLAYER_ACT1",
                context={"player_name": player_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=text,
                status="success" if cleaned else "fallback",
                elapsed_ms=_elapsed,
            )
            return {"success": bool(cleaned), "act1_text": text, "raw_response": raw}
        except Exception as e:
            AILogger.log_call(
                call_type="PUA_PLAYER_ACT1",
                context={"player_name": player_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback_text,
                status="fallback",
                elapsed_ms=0,
            )
            return {
                "success": False,
                "act1_text": fallback_text,
                "raw_response": f"PUA_PLAYER_ACT1_FALLBACK: {str(e)[:100]}",
            }

    @staticmethod
    async def generate_pua_player_act2(
        act1_text: str,
        emotion_card_name: str,
        emotion_card_tone: str,
        action_card_name: str,
        action_card_effect: str,
        combo_type: str,
        boss_thought: str,
        player_name: str,
    ) -> dict:
        """
        玩家在PUA场景出牌后的Act2生成，支持解析“印象：”字段。
        """
        dl = DataLoader()
        boss_name = str(dl.get_npc_field("boss", "display_name", "鲍斯")).strip() or "鲍斯"
        boss_identity = str(dl.get_npc_identity("boss") or "").strip() or "未知身份"
        boss_aim = str(dl.get_npc_field("boss", "aim", "")).strip() or "找出卧底，维持统治。"
        thought = str(boss_thought or "").strip() or "目标行为仍需继续观察。"
        fallback_scene = dl.pick_pua_segments("player") or {}
        fallback_text = str(fallback_scene.get("ending_text", "")).strip() or str(
            fallback_scene.get("full_text", "")
        ).strip() or "鲍斯的触手慢慢收回阴影里，只留下一句模棱两可的警告。"

        system_prompt = AIService.build_npc_worldview_system_prompt(
            npc_name=boss_name,
            npc_identity=boss_identity,
            npc_aim=boss_aim,
            npc_memory_rel="",
        )
        user_prompt = PromptRegistry.render(
            "pua_player_act2",
            act1_text=act1_text,
            emotion_card_name=emotion_card_name,
            emotion_card_tone=emotion_card_tone,
            action_card_name=action_card_name,
            action_card_effect=action_card_effect,
            combo_type=combo_type,
            boss_thought=thought,
            player_name=player_name,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=700,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).strip()
            display_text, memory_text, impression = AIService._split_act2_display_and_memory_impression(cleaned)
            if not display_text:
                display_text = fallback_text
            if not impression:
                impression = thought
            if not memory_text:
                memory_text = impression
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="PUA_PLAYER_ACT2",
                context={"combo": combo_type},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=f"{display_text}\n印象：{impression}",
                status="success" if cleaned else "fallback",
                elapsed_ms=_elapsed,
            )
            return {
                "success": bool(cleaned),
                "act2_text": display_text,
                "dialogues": {boss_name: display_text},
                "narrator": "",
                "raw_response": raw,
                "memory_text": memory_text,
                "impression": impression,
            }
        except Exception as e:
            AILogger.log_call(
                call_type="PUA_PLAYER_ACT2",
                context={"combo": combo_type},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback_text,
                status="fallback",
                elapsed_ms=0,
            )
            return {
                "success": False,
                "act2_text": fallback_text,
                "dialogues": {boss_name: fallback_text},
                "narrator": "",
                "raw_response": f"PUA_PLAYER_ACT2_FALLBACK: {str(e)[:100]}",
                "memory_text": thought,
                "impression": thought,
            }

    @staticmethod
    async def generate_solo_action_act2(
        act1_text: str,
        room_name: str,
        task_text: str,
        action_card_name: str,
        action_card_effect: str,
        action_card_tone: str,
        player_name: str = "调查员",
        evidence_hint: str = "",
    ) -> dict:
        """
        单人事件专用Act2：仅基于一张行为牌，不使用combo。
        当 evidence_hint 非空时，prompt 会要求把线索自然融入剧情。
        """
        system_prompt = PromptRegistry.render(
            "solo_action_act2_system_prompt",
            player_name=player_name,
        )

        evidence_hint_text = str(evidence_hint or "").strip()
        evidence_block = ""
        if evidence_hint_text:
            evidence_block = (
                f"\n隐藏剧情要求（不展示给玩家，融入旁白中）：\n"
                f"请在旁白中自然地暴露以下线索：{evidence_hint_text}\n"
                f"不要刻意点明，像是{player_name}不经意瞥见、想起或听到的细节。\n"
            )

        user_prompt = PromptRegistry.render(
            "solo_action_act2_user_prompt",
            player_name=player_name,
            room_name=room_name,
            task_text=task_text,
            act1_text=act1_text,
            action_card_name=action_card_name,
            action_card_effect=action_card_effect,
            evidence_block=evidence_block,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=600,
                timeout=8,
            )
            raw = response.choices[0].message.content.strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).strip()
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="ACT2_SOLO_ACTION",
                context={"room": room_name, "tone": action_card_tone},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=cleaned,
                status="success",
                elapsed_ms=_elapsed,
            )
            return {
                "success": bool(cleaned),
                "act2_text": cleaned,
                "dialogues": {},
                "narrator": cleaned,
                "raw_response": raw,
            }
        except Exception as e:
            dl = DataLoader()
            fallback = dl.get_fallback(
                "f04_solo_act2",
                default=f"{player_name}在{room_name}里做出了一个离谱但克制的动作，空气短暂地恢复了平静。",
            )
            AILogger.log_call(
                call_type="ACT2_SOLO_ACTION",
                context={"room": room_name, "tone": action_card_tone},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback,
                status="fallback",
                elapsed_ms=0,
            )
            return {
                "success": False,
                "act2_text": fallback,
                "dialogues": {},
                "narrator": fallback,
                "raw_response": f"ACT2_SOLO_ACTION_FALLBACK: {str(e)[:100]}",
            }

    @staticmethod
    def _parse_act2_response(raw: str, npc_infos: list[dict]) -> dict:
        """解析Act 2响应——纯文本模式，不再需要XML解析"""
        # 清理可能残留的标签
        cleaned = re.sub(r"<[^>]+>", "", raw).strip()
        if not cleaned:
            cleaned = raw.strip()

        # 独自场景：不构造任何NPC对话，避免前端展示“NPC: ...”
        if not npc_infos:
            return {
                "success": bool(cleaned),
                "act2_text": cleaned,
                "dialogues": {},
                "narrator": cleaned,
                "memory_text": "",
                "impression": "",
            }

        display_text, memory_text, impression = AIService._split_act2_display_and_memory_impression(cleaned)
        npc_name = npc_infos[0]["name"]
        return {
            "success": bool(display_text),
            "act2_text": display_text,
            "dialogues": {npc_name: display_text},
            "narrator": "",
            "memory_text": memory_text,
            "impression": impression,
        }

    @staticmethod
    def _fallback_act2(npc_infos: list[dict], combo_type: str, error_msg: str) -> dict:
        """Act 2降级：仅使用 fallback/*.csv。"""
        dl = DataLoader()

        dialogues = {}
        if npc_infos:
            # 明确只使用primary，防止未来误把多NPC列表喂进来。
            primary = npc_infos[0]
            name = primary["name"]
            npc_id = primary.get("id", "").strip()
            csv_text = dl.get_fallback(
                "f05_duo_act2",
                npc_id=npc_id,
                combo=combo_type,
                default="",
            )
            dialogues[name] = csv_text or f"{name}没多说什么,只是抬头瞄了你一眼,转头继续做手里的事。"
        else:
            solo_text = dl.get_fallback(
                "f04_solo_act2",
                combo=combo_type,
                default="你在昏暗中等了几秒,什么都没有发生,仿佛刚才的异常只是错觉。",
            )
            if solo_text:
                dialogues["环境"] = solo_text

        parts = list(dialogues.values())

        return {
            "success": False,
            "act2_text": "\n\n".join(parts),
            "dialogues": dialogues,
            "narrator": "",
            "raw_response": f"ACT2_FALLBACK: {error_msg}",
            "memory_text": "",
            "impression": "",
        }

    @staticmethod
    def _split_act2_display_and_memory_impression(raw_text: str) -> tuple[str, str, str]:
        """
        从Act2原始文本中拆分"展示正文 / 记忆 / 印象"。

        支持两种 prompt 输出格式,自动识别:

        格式 A(带 --- 分隔符,PUA 系列):
            [剧情]
            ---
            印象:xxx
        或
            [剧情]
            ---
            记忆:xxx

        格式 B(无分隔符,常规 Act2):
            [剧情]
            记忆:xxx

        规则:
        - 优先按 "---" 切分;切分后从 meta 段提取 印象/记忆
        - 没有 "---" 就在原文里找 "记忆:" 或 "印象:" 行,提取并从展示中移除
        - 如果有 印象 但没 记忆,记忆 fallback 到 印象的内容
        """
        text = str(raw_text or "").strip()
        if not text:
            return "", "", ""

        memory_text = ""
        impression = ""

        # 格式 A:有 --- 分隔符,先分两段,后段提取标签
        if "---" in text:
            parts = text.split("---", 1)
            display_text = parts[0].rstrip()
            meta_block = parts[1].strip() if len(parts) > 1 else ""
            m_imp = re.search(r"^\s*印象[:：]\s*(.+?)\s*$", meta_block, re.MULTILINE)
            if m_imp:
                impression = str(m_imp.group(1) or "").strip()
            m_mem = re.search(r"^\s*记忆[:：]\s*(.+?)\s*$", meta_block, re.MULTILINE)
            if m_mem:
                memory_text = str(m_mem.group(1) or "").strip()
            # 如果只给了 印象 没给 记忆,记忆 fallback 用 印象
            if impression and not memory_text:
                memory_text = impression
            return display_text, memory_text, impression

        # 格式 B:无 --- 分隔符,直接在正文里找 记忆: / 印象: 行并移除
        display_text = text
        m_mem = re.search(r"^\s*记忆[:：]\s*(.+?)\s*$", display_text, re.MULTILINE)
        if m_mem:
            memory_text = str(m_mem.group(1) or "").strip()
            display_text = display_text.replace(m_mem.group(0), "", 1).rstrip()
        m_imp = re.search(r"^\s*印象[:：]\s*(.+?)\s*$", display_text, re.MULTILINE)
        if m_imp:
            impression = str(m_imp.group(1) or "").strip()
            display_text = display_text.replace(m_imp.group(0), "", 1).rstrip()
        if impression and not memory_text:
            memory_text = impression

        return display_text, memory_text, impression

    @staticmethod
    async def generate_record_card_summary(
        *,
        act1_text: str,
        act2_text: str,
        room_name: str,
        task_name: str,
        npc_name: str,
        player_name: str = "调查员",
    ) -> str:
        """
        独立请求：生成记录卡客观总结。
        输出格式：记录：（谁在哪做了什么，结果如何）
        """
        act1_snippet = str(act1_text or "").strip()[:150]
        act2_snippet = str(act2_text or "").strip()[:150]
        fallback = f"记录：{npc_name}在{room_name}{task_name}中出现异常。"
        system_prompt = PromptRegistry.get_template("record_card_summary_system_prompt")
        user_prompt = PromptRegistry.render(
            "record_card_summary_user_prompt",
            room_name=room_name,
            task_name=task_name,
            npc_name=npc_name,
            player_name=player_name,
            act1_snippet=act1_snippet,
            act2_snippet=act2_snippet,
        )
        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=120,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).strip()
            if not cleaned.startswith("记录：") and not cleaned.startswith("记录:"):
                cleaned = f"记录：{cleaned}" if cleaned else fallback
            if len(cleaned) > 80:
                cleaned = cleaned[:80].rstrip("，。；、 ") + "。"
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="RECORD_CARD_SUMMARY",
                context={"room": room_name, "task": task_name, "npc": npc_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=cleaned,
                status="success",
                elapsed_ms=_elapsed,
            )
            return cleaned
        except Exception as e:
            AILogger.log_call(
                call_type="RECORD_CARD_SUMMARY",
                context={"room": room_name, "task": task_name, "npc": npc_name},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output=fallback,
                status="fallback",
                elapsed_ms=0,
            )
            return fallback

    # ==========================================
    # 涌现行为可视化优化（V1：群体黑料剧情整合）
    # ==========================================

    @staticmethod
    async def merge_blackmail_broadcast_replies_v2(
        *,
        player_name: str,
        subject_npc_name: str,
        room_name: str,
        distorted_summary: str,
        listener_replies: list[dict],
    ) -> str:
        """
        把多个 NPC 各自的黑料反应整合成一段连贯群戏对话。

        listener_replies 元素格式（供调用方组装）：
            {
                "npc_name": "老王",
                "story": "（该 NPC 单独那段3-5句的Act1+反应文本）",
                "player_judgement": "增加怀疑/减少怀疑/无感",
                "subject_judgement": "增加怀疑/减少怀疑/无感",
            }

        失败 / 列表为空时返回空串，调用方自行 fallback 到原 dialogues 拼接。
        仅做表现层整合，不修改任何记忆/数值。
        """
        if not listener_replies:
            return ""
        if len(listener_replies) < 2:
            single = listener_replies[0]
            single_text = str(single.get("story", "") or "").strip()
            return single_text

        materials_lines: list[str] = []
        for item in listener_replies:
            name = str(item.get("npc_name", "同事") or "同事").strip() or "同事"
            story = str(item.get("story", "") or "").strip()
            pj = str(item.get("player_judgement", "无感") or "无感").strip() or "无感"
            sj = str(item.get("subject_judgement", "无感") or "无感").strip() or "无感"
            materials_lines.append(
                f"【{name}】（对玩家：{pj}；对{subject_npc_name}：{sj}）\n{story}"
            )
        materials_block = "\n\n".join(materials_lines)

        system_prompt = PromptRegistry.get_template("blackmail_group_merge_system_prompt")
        user_prompt = PromptRegistry.render(
            "blackmail_group_merge_user_prompt",
            player_name=player_name,
            room_name=room_name,
            subject_npc_name=subject_npc_name,
            distorted_summary=distorted_summary,
            materials_block=materials_block,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.85,
                max_tokens=520,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).replace("\r\n", "\n").replace("\r", "\n").strip()
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="BLACKMAIL_GROUP_MERGE",
                context={
                    "subject": subject_npc_name,
                    "room": room_name,
                    "listener_count": len(listener_replies),
                },
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=cleaned,
                status="success",
                elapsed_ms=_elapsed,
            )
            return cleaned
        except Exception as e:
            AILogger.log_call(
                call_type="BLACKMAIL_GROUP_MERGE",
                context={
                    "subject": subject_npc_name,
                    "room": room_name,
                    "listener_count": len(listener_replies),
                },
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output="",
                status="fallback",
                elapsed_ms=0,
            )
            return ""

    # ==========================================
    # 涌现行为可视化优化（V2：夜间结盟密谋对话）
    # ==========================================

    @staticmethod
    async def generate_alliance_conspiracy_dialogue_v2(
        *,
        npc_a_name: str,
        npc_a_personality: str,
        npc_a_public_impression: str,
        npc_b_name: str,
        npc_b_personality: str,
        npc_b_public_impression: str,
        target_name: str,
        room_name: str,
        alliance_reason: str = "",
    ) -> str:
        """
        生成两人夜间结盟密谋对话（小助理通过通风管道偷拍视角）。
        必须自然暴露"投谁"和"为什么"。
        失败返回空串，调用方 fallback 到含 target_name 的模板文本。
        """
        npc_a_personality = (npc_a_personality or "").strip() or "（性格不详）"
        npc_b_personality = (npc_b_personality or "").strip() or "（性格不详）"
        npc_a_public_impression = (npc_a_public_impression or "").strip() or "（公开形象不详）"
        npc_b_public_impression = (npc_b_public_impression or "").strip() or "（公开形象不详）"
        alliance_reason = (alliance_reason or "").strip()

        system_prompt = PromptRegistry.get_template("alliance_conspiracy_system_prompt")
        reason_line = f"他们盯上{target_name}的理由参考：{alliance_reason}\n" if alliance_reason else ""
        user_prompt = PromptRegistry.render(
            "alliance_conspiracy_user_prompt",
            npc_a_name=npc_a_name,
            room_name=room_name,
            npc_b_name=npc_b_name,
            npc_a_personality=npc_a_personality,
            npc_a_public_impression=npc_a_public_impression,
            npc_b_personality=npc_b_personality,
            npc_b_public_impression=npc_b_public_impression,
            target_name=target_name,
            reason_line=reason_line,
        )

        try:
            _start = AILogger.start_timer()
            response = await _client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=420,
                timeout=8,
            )
            raw = str(response.choices[0].message.content or "").strip()
            cleaned = re.sub(r"<[^>]+>", "", raw).replace("\r\n", "\n").replace("\r", "\n").strip()
            _elapsed = AILogger.elapsed_since(_start)
            AILogger.log_call(
                call_type="ALLIANCE_CONSPIRACY",
                context={
                    "npc_a": npc_a_name,
                    "npc_b": npc_b_name,
                    "target": target_name,
                    "room": room_name,
                },
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=raw,
                final_output=cleaned,
                status="success",
                elapsed_ms=_elapsed,
            )
            return cleaned
        except Exception as e:
            AILogger.log_call(
                call_type="ALLIANCE_CONSPIRACY",
                context={
                    "npc_a": npc_a_name,
                    "npc_b": npc_b_name,
                    "target": target_name,
                    "room": room_name,
                },
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_reply=f"ERROR: {str(e)}",
                final_output="",
                status="fallback",
                elapsed_ms=0,
            )
            return ""
