"""
末日调查员 - WebSocket 服务器

给 GameController 提供 WebSocket 接口，供 Godot 前端调用。
启动方式：python server.py
默认监听：ws://localhost:8765

通讯协议：
  前端 → 后端：{"type": "消息类型", "data": {参数}}
  后端 → 前端：{"type": "响应类型", "data": {结果}}
"""

import asyncio
import json
import logging
import os
import sys
import ctypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets
from backend.game_controller import GameController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DoomsdayServer")

HOST = "localhost"
PORT = 8765


class GameServer:
    def __init__(self):
        self.connections: dict[str, GameController] = {}

    async def handler(self, websocket):
        conn_id = str(id(websocket))
        gc = GameController()
        self.connections[conn_id] = gc
        logger.info(f"新连接：{conn_id}，来自 {websocket.remote_address}")

        try:
            async for raw_message in websocket:
                try:
                    message = json.loads(raw_message)
                    msg_type = message.get("type", "")
                    msg_data = message.get("data", {})
                    logger.info(f"← 收到 [{msg_type}]：{json.dumps(msg_data, ensure_ascii=False)}")

                    response = await self.route_message(gc, msg_type, msg_data)

                    resp_json = json.dumps(response, ensure_ascii=False)
                    await websocket.send(resp_json)
                    logger.info(f"→ 发送 [{response.get('type', '?')}]：{resp_json}")

                except json.JSONDecodeError:
                    error_resp = self._error("invalid_json", "消息格式错误，请发送JSON")
                    await websocket.send(json.dumps(error_resp, ensure_ascii=False))

                except Exception as e:
                    logger.error(f"处理消息时出错：{e}", exc_info=True)
                    error_resp = self._error("internal_error", f"服务器内部错误：{str(e)}")
                    await websocket.send(json.dumps(error_resp, ensure_ascii=False))


        except websockets.exceptions.ConnectionClosed:
            logger.info(f"连接断开：{conn_id}")
        finally:
            del self.connections[conn_id]

    async def route_message(self, gc: GameController, msg_type: str, data: dict) -> dict:
        """
        消息路由（异步版）。
        """
        handlers = {
            "new_game": self._handle_new_game,
            "select_tasks": self._handle_select_tasks,
            "start_move": self._handle_start_move,
            "movement_done": self._handle_movement_done,
            "choose_work_mode": self._handle_choose_work_mode,
            "debug_seed_work_snapshot": self._handle_debug_seed_work_snapshot,
            "play_cards": self._handle_play_cards,
            "use_record_card": self._handle_use_record_card,
            "use_blame_card": self._handle_use_blame_card,
            "use_blackmail": self._handle_use_blackmail,
            "scout_room": self._handle_scout_room,
            "scout_dispatch": self._handle_scout_dispatch,
            "record_scout": self._handle_record_scout,
            "skip_record": self._handle_skip_record,
            "cast_vote": self._handle_cast_vote,
            "enter_night": self._handle_enter_night,
            "night_open_door": self._handle_night_open_door,
            "night_respond": self._handle_night_respond,
            "night_seek_alliance": self._handle_night_seek_alliance,
            "night_scout": self._handle_night_scout,
            "buy_item": self._handle_buy_item,
            "get_shop": self._handle_get_shop,
            "next_day": self._handle_next_day,
            "respond_negotiation": self._handle_respond_negotiation,
            "get_status": self._handle_get_status,
            "get_ending_summary": self._handle_get_ending_summary,
        }

        handler = handlers.get(msg_type)
        if handler is None:
            return self._error("unknown_type", f"未知消息类型：{msg_type}")

        # 支持同步和异步handler
        result = handler(gc, data)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def _handle_new_game(self, gc: GameController, data: dict) -> dict:
        gc.new_game()
        task_data = gc.start_task_selection()
        return {"type": "game_started", "data": task_data}

    async def _handle_select_tasks(self, gc: GameController, data: dict) -> dict:
        task_ids = data.get("task_ids", [])
        if not isinstance(task_ids, list):
            return self._error("invalid_params", "task_ids 必须是数组")

        result = await gc.submit_task_selection(task_ids)
        if "error" in result:
            return self._error("select_tasks_failed", result["error"])

        return {"type": "work_started", "data": result}

    async def _handle_play_cards(self, gc: GameController, data: dict) -> dict:
        """打出卡牌（异步：调用DeepSeek AI）"""
        emotion = data.get("emotion", "")
        action = data.get("action", "")
        solo_action = data.get("solo_action", "")
        mode = str(data.get("mode", "")).strip().lower()

        if mode == "solo_action" or solo_action:
            action_id = str(solo_action or action).strip()
            if not action_id:
                return self._error("play_cards_error", "请选择1张单人行为牌")
            result = await gc.play_solo_action_with_ai(action_id)
            if "error" in result:
                return self._error("play_cards_error", result["error"])
            return {"type": "card_result", "data": result}

        if not emotion or not action:
            return self._error("play_cards_error", "请选择情绪卡和行动卡")

        # 优先使用异步AI版本
        try:
            result = await gc.play_cards_with_ai_v2(emotion, action)
        except Exception as e:
            logger.warning(f"AI出牌异常，降级到硬编码：{e}")
            result = gc.play_cards(emotion, action)

        if "error" in result:
            return self._error("play_cards_error", result["error"])

        return {
            "type": "card_result",
            "data": result,
        }

    async def _handle_respond_negotiation(self, gc: GameController, data: dict) -> dict:
        """
        处理玩家对协商弹窗(祈求/勒索)的同意/拒绝响应。

        前端 → 后端: {"type": "respond_negotiation", "data": {"agree": true/false}}
        后端 → 前端: {"type": "negotiation_result", "data": {...}}
        """
        agree = bool(data.get("agree", False))
        try:
            result = await gc.respond_to_negotiation(agree=agree)
        except Exception as e:
            logger.warning(f"[respond_negotiation] 异常: {e}")
            return self._error("respond_negotiation_error", str(e))

        if not result.get("success", False):
            return self._error(
                "respond_negotiation_error",
                result.get("error", "unknown_error"),
            )

        return {
            "type": "negotiation_result",
            "data": result,
        }

    async def _handle_start_move(self, gc: GameController, data: dict) -> dict:
        """开始移动阶段并预请求Act 1"""
        task_index = data.get("task_index", 0)
        if not isinstance(task_index, int):
            return self._error("invalid_params", "task_index 必须是整数")
        result = await gc.start_movement_phase(task_index)
        if "error" in result:
            return self._error("start_move_error", result["error"])
        return {"type": "movement_data", "data": result}

    async def _handle_movement_done(self, gc: GameController, data: dict) -> dict:
        """移动动画完成后获取Act 1结果"""
        result = await gc.get_act1_after_movement()
        if "error" in result:
            return self._error("movement_done_error", result["error"])
        if result.get("_response_type") == "card_result":
            result.pop("_response_type", None)
            return {"type": "card_result", "data": result}
        return {"type": "event_ready", "data": result}

    async def _handle_choose_work_mode(self, gc: GameController, data: dict) -> dict:
        """处理工作阶段的“单干/交流”选择。"""
        mode = str(data.get("mode", "")).strip().lower()
        target_npc = str(data.get("target_npc", "")).strip()
        card_id = str(data.get("card_id", "")).strip()
        result = await gc.choose_work_mode(mode=mode, target_npc_id=target_npc, card_id=card_id)
        if "error" in result:
            return self._error("choose_work_mode_error", result["error"])
        if result.get("_response_type") == "card_result":
            result.pop("_response_type", None)
            return {"type": "card_result", "data": result}
        return {"type": "event_ready", "data": result}

    def _handle_debug_seed_work_snapshot(self, gc: GameController, data: dict) -> dict:
        """Debug专用：强制布置当前工作场景，便于复测五种状况。"""
        result = gc.debug_seed_work_snapshot(data)
        if "error" in result:
            return self._error("debug_seed_error", result["error"])
        return {"type": "debug_seeded", "data": result}

    async def _handle_use_record_card(self, gc: GameController, data: dict) -> dict:
        """使用记录卡 - 自动查找第一张空白卡"""
        record_type = str(data.get("record_type", "evidence")).strip().lower()
        blank_card = None
        for rc in gc.state.player.record_cards:
            if rc.status.value == "blank":
                blank_card = rc
                break

        if blank_card is None:
            return self._error("record_card_error", "没有空白记录卡了")

        result = await gc.use_record_card(blank_card.id, record_type=record_type)
        if not result.get("success", False):
            return self._error("record_card_error", result.get("message", "记录失败"))

        # 缓存下一个事件（record_card_used后前端会发skip_record推进）
        # 注意：当前版本record_card_used不自动推进，由前端手动skip
        return {
            "type": "record_card_used",
            "data": {
                "record_result": result,
                "remaining_blank": sum(
                    1 for rc in gc.state.player.record_cards
                    if rc.status.value == "blank"
                ),
                "evidence_count": result.get("evidence_count", len(gc.state.evidence_collected)),
                "valid_evidence_count": gc._valid_evidence_count(),
                "recorded_cards_count": gc._recorded_cards_count(),
            },
        }

    def _handle_use_blame_card(self, gc: GameController, data: dict) -> dict:
        """使用嫁祸卡"""
        target = data.get("target_npc", "")
        if not target:
            return self._error("blame_error", "请选择替罪羊")
        result = gc.use_blame_card(target)
        if not result.get("success"):
            return self._error("blame_error", result.get("message", ""))
        return {"type": "blame_card_used", "data": result}

    async def _handle_use_blackmail(self, gc: GameController, data: dict) -> dict:
        """使用记录卡威胁NPC"""
        card_id = data.get("card_id", "")
        target = data.get("target_npc", "")
        if not card_id or not target:
            return self._error("blackmail_error", "请指定记录卡和目标NPC")
        try:
            result = await gc.use_card_as_blackmail(card_id, target)
        except Exception as e:
            logger.warning(f"威胁异常：{e}")
            return self._error("blackmail_error", str(e)[:50])
        if not result.get("success"):
            return self._error("blackmail_error", result.get("message", ""))
        return {"type": "blackmail_result", "data": result}

    async def _handle_scout_room(self, gc: GameController, data: dict) -> dict:
        """侦察房间（兼容旧同步入口）"""
        target = data.get("target_room", "")
        target_npc_id = str(data.get("target_npc_id", "")).strip()
        if not target:
            return self._error("scout_error", "请选择目标房间")
        try:
            result = await gc.scout_room(target, target_npc_id=target_npc_id)
        except Exception as e:
            logger.warning(f"侦察异常：{e}")
            return self._error("scout_error", f"侦察出错：{str(e)[:50]}")
        if not result.get("success"):
            return self._error("scout_error", result.get("message", ""))
        return {"type": "scout_result", "data": result}

    async def _handle_scout_dispatch(self, gc: GameController, data: dict) -> dict:
        """异步派出小助理（不等待结果）"""
        target = data.get("target_room", "")
        target_npc_id = str(data.get("target_npc_id", "")).strip()
        if not target:
            return self._error("scout_error", "请选择目标房间")
        try:
            result = await gc.dispatch_scout(target, target_npc_id=target_npc_id)
        except Exception as e:
            logger.warning(f"派遣侦察异常：{e}")
            return self._error("scout_error", f"派遣失败：{str(e)[:50]}")
        if not result.get("success"):
            return self._error("scout_error", result.get("message", ""))
        return {"type": "scout_dispatched", "data": result}

    def _handle_record_scout(self, gc: GameController, data: dict) -> dict:
        """记录小助理带回的信息为证据 / 黑料。"""
        tag = data.get("evidence_tag", "")
        record_type = str(data.get("record_type", "evidence") or "evidence").strip().lower()
        if record_type not in {"evidence", "blackmail"}:
            record_type = "evidence"
        result = gc.record_scout_evidence_v2(tag, record_type=record_type)
        if not result.get("success"):
            return self._error("record_scout_error", result.get("message", ""))
        if "evidence_count" not in result:
            result["evidence_count"] = len(gc.state.evidence_collected)
        result["valid_evidence_count"] = gc._valid_evidence_count()
        result["recorded_cards_count"] = gc._recorded_cards_count()
        return {"type": "record_scout_result", "data": result}

    async def _handle_skip_record(self, gc: GameController, data: dict) -> dict:
        """跳过记录卡，推进下一小时"""
        result = await gc.advance_to_next_hour()
        if "error" in result:
            return self._error("skip_record_error", result["error"])

        # 缓存下一个事件的描述（供AI使用）
        event = result.get("event")
        if event:
            gc._last_event_description = event.get("description", "")
            gc._last_event_prompt = event.get("prompt", "")

        return {
            "type": "hour_advanced",
            "data": result,
        }

    async def _handle_cast_vote(self, gc: GameController, data: dict) -> dict:
        target_npc = data.get("target_npc")
        if not target_npc:
            return self._error("invalid_params", "cast_vote 需要 target_npc")

        result = await gc.submit_vote_v2(target_npc)
        if "error" in result:
            return self._error("cast_vote_failed", result["error"])

        return {"type": "vote_result", "data": result}

    async def _handle_enter_night(self, gc: GameController, data: dict) -> dict:
        """进入夜间并返回结盟状态数据。"""
        result = await gc.enter_night_phase_v2()
        if result.get("phase") == "game_over":
            result["game_over"] = True
            result["game_result"] = self._safe_get_attr(gc.state, "game_result", "")
            return {"type": "night_phase_data", "data": result}

        return {"type": "night_phase_data", "data": result}

    def _handle_night_open_door(self, gc: GameController, data: dict) -> dict:
        npc_id = str(data.get("npc_id", "")).strip()
        open_door = bool(data.get("open_door", npc_id != ""))
        result = gc.night_open_door(npc_id, open_door)
        if not result.get("success"):
            return self._error("night_open_door_failed", result.get("message", "开门失败"))
        return {"type": "door_result", "data": result}

    def _handle_night_respond(self, gc: GameController, data: dict) -> dict:
        npc_id = str(data.get("npc_id", "")).strip()
        agree = bool(data.get("agree", False))
        result = gc.night_respond(npc_id, agree)
        if not result.get("success"):
            return self._error("night_respond_failed", result.get("message", "回应失败"))
        return {"type": "alliance_result", "data": result}

    async def _handle_night_seek_alliance(self, gc: GameController, data: dict) -> dict:
        target_npc_id = str(data.get("target_npc_id", "")).strip()
        vote_target_id = str(data.get("vote_target_id", "")).strip()
        if not target_npc_id or not vote_target_id:
            return self._error("invalid_params", "night_seek_alliance 需要 target_npc_id 和 vote_target_id")
        result = await gc.night_seek_alliance(target_npc_id, vote_target_id)
        if not result.get("success"):
            return self._error("night_seek_failed", result.get("message", "结盟失败"))
        return {"type": "seek_result", "data": result}

    async def _handle_night_scout(self, gc: GameController, data: dict) -> dict:
        target_npc_id = str(data.get("target_npc_id", "")).strip()
        if not target_npc_id:
            return self._error("invalid_params", "night_scout 需要 target_npc_id")
        result = await gc.night_scout(target_npc_id)
        if not result.get("success"):
            return self._error("night_scout_failed", result.get("message", "巡视失败"))
        return {"type": "scout_result", "data": result}

    def _handle_buy_item(self, gc: GameController, data: dict) -> dict:
        """商城购买"""
        item_key = data.get("item_key", "")
        if not item_key:
            return self._error("shop_error", "请指定商品")
        result = gc.buy_item(item_key)
        if not result.get("success"):
            return self._error("shop_error", result.get("message", ""))
        return {"type": "buy_result", "data": result}

    def _handle_get_shop(self, gc: GameController, data: dict) -> dict:
        """获取商城数据"""
        return {"type": "shop_data", "data": gc.get_shop_data()}

    def _handle_next_day(self, gc: GameController, data: dict) -> dict:
        """进入下一天。

        注意: game_over 类型已废弃,改由前端主动发送 get_ending_summary
        走新链路 EndingUI 展示。这里 game_over 时仍返回 new_day 类型,
        并附带 game_over/game_result 字段供前端识别。
        """
        result = gc.proceed_to_next_day()
        if gc.state and gc.state.game_over:
            result["game_over"] = True
            result["game_result"] = self._safe_get_attr(gc.state, "game_result", "")
        return {"type": "new_day", "data": result}

    def _handle_get_status(self, gc: GameController, data: dict) -> dict:
        return {"type": "game_status", "data": gc.get_game_status()}

    async def _handle_get_ending_summary(self, gc: GameController, data: dict) -> dict:
        """前端请求结算界面数据。"""
        try:
            summary = gc.build_ending_summary()
        except Exception as e:
            logger.warning(f"[get_ending_summary] 异常: {e}")
            return self._error("get_ending_summary_error", str(e))

        return {
            "type": "ending_summary",
            "data": summary,
        }

    def _error(self, error_type: str, message: str) -> dict:
        return {
            "type": "error",
            "data": {
                "error_type": error_type,
                "message": message,
            },
        }

    def _safe_get_attr(self, obj, attr: str, default):
        """安全 getattr。"""
        return getattr(obj, attr, default) if obj else default


async def main():
    server = GameServer()

    logger.info("末日调查员 WebSocket 服务器启动中...")
    logger.info(f"监听地址：ws://{HOST}:{PORT}")
    logger.info("等待 Godot 前端连接...\n")

    async with websockets.serve(server.handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError as e:
        # Windows 下常见: 端口被已运行实例占用（WinError/Errno 10048）
        is_port_in_use = (
            getattr(e, "winerror", None) == 10048
            or getattr(e, "errno", None) == 10048
            or "10048" in str(e)
        )
        if is_port_in_use:
            msg = (
                f"端口 {PORT} 已被占用。\n\n"
                "末日调查员后端可能已经在运行，请勿重复启动。"
            )
            logger.error(msg)
            try:
                ctypes.windll.user32.MessageBoxW(0, msg, "末日调查员后端", 0x00000010)
            except Exception:
                pass
        else:
            raise
    except KeyboardInterrupt:
        logger.info("服务器已停止")
