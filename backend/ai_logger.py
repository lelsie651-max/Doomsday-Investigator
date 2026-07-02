"""
AI调用日志记录器

每次AI调用记录：
1. 发送给AI的完整prompt（system + user）
2. AI返回的raw reply + 响应耗时
3. 系统最终呈现给玩家的内容
4. 状态标记（success / parse_error / timeout / fallback）
"""

import logging
import time
from pathlib import Path

# 日志目录
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 配置logger
_logger = logging.getLogger("ai_calls")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

if not _logger.handlers:
    # 文件handler（按天滚动可后续用TimedRotatingFileHandler替换）
    _handler = logging.FileHandler(
        LOG_DIR / "ai_calls.log", encoding="utf-8", mode="a"
    )
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)

    # 同时输出到终端（方便调试）
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter("[AI_LOG] %(message)s"))
    _logger.addHandler(_console)


class AILogger:
    """AI调用日志工具"""

    @staticmethod
    def log_call(
        call_type: str,
        context: dict,
        system_prompt: str,
        user_prompt: str,
        raw_reply: str,
        final_output: str,
        status: str,
        elapsed_ms: int,
    ):
        """
        记录一次AI调用。

        参数:
            call_type: "ACT1" / "ACT2" / "SCOUT" / "CHAT" / "BLACKMAIL"
            context: {"room": "warehouse", "npcs": ["某同事A","某同事B"], "combo": "crazy", ...}
            system_prompt: 发给AI的system prompt
            user_prompt: 发给AI的user prompt
            raw_reply: AI原始返回
            final_output: 清理后展示给玩家的内容
            status: "success" / "parse_error" / "timeout" / "fallback"
            elapsed_ms: 响应耗时（毫秒）
        """
        separator = "=" * 80
        ctx_str = " | ".join(f"{k}={v}" for k, v in context.items())

        entry = f"""
{separator}
[{call_type}] [{status}] [{elapsed_ms}ms] {ctx_str}
{separator}

--- SYSTEM PROMPT ---
{system_prompt}

--- USER PROMPT ---
{user_prompt}

--- RAW REPLY ---
{raw_reply}

--- FINAL OUTPUT ---
{final_output}

--- STATUS: {status} | ELAPSED: {elapsed_ms}ms ---
"""
        _logger.debug(entry)

    @staticmethod
    def start_timer() -> float:
        """返回当前时间戳，用于计算耗时"""
        return time.time()

    @staticmethod
    def elapsed_since(start: float) -> int:
        """返回从start到现在的毫秒数"""
        return int((time.time() - start) * 1000)
