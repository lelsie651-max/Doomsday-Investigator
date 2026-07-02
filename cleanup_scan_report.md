# 废弃模块扫描报告

扫描范围（按要求）：
- A. `backend/chat_system.py`
- B. `backend/event_templates.py`
- C. `backend/play.py`
- D. `backend/test_negotiation_behavior.py`
- E. `Godot前端工程/scripts/game_over_ui.gd`

说明：
- 本报告仅基于静态检索（grep/读文件），未执行任何删除或自动修复。
- 结果包含源码路径与 `dist/server/_internal` 打包副本命中；打包副本是否参与运行，统一标注为 **待人工 review**。

---

## A. chat_system.py 扫描结果

### 1. 被谁 import
- `backend/game_controller.py`: 第 19 行：`from .chat_system import ChatSystem`
- `backend/__init__.py`: 第 4 行：`from .chat_system import ChatSystem`
- `dist/server/_internal/backend/game_controller.py`: 第 19 行：`from .chat_system import ChatSystem`
- `dist/server/_internal/backend/__init__.py`: 第 4 行：`from .chat_system import ChatSystem`

### 2. 公共方法调用方
- `ChatSystem.generate_night_chat`：
  - `backend/game_controller.py`: 第 5884 行：`chat_data = await ChatSystem.generate_night_chat(...)`
  - `dist/server/_internal/backend/game_controller.py`: 第 5884 行同名调用（打包副本）
- `AgentChatService`：
  - 外部未检索到直接调用；仅在 `chat_system.py` 内部被 `NightChatOrchestrator` 调用
- `AgentChatService.generate_one_message`：
  - 仅 `chat_system.py` 内部调用（第 329/345/366 行）
- `NightChatOrchestrator`：
  - 仅 `chat_system.py` 内部实例化（第 451 行）

### 3. WebSocket handler
- `server.py` 的 `handlers` 映射（第 80-105 行）中，**没有** `night_chat` / `spy_chat` / `record_chat` 类型注册。
- `server.py` 虽定义了：
  - `_handle_spy_chat`（第 408 行）
  - `_handle_record_chat`（第 413 行）
  但当前未挂入 `handlers` 字典，前端无法通过消息 type 路由到这两个方法。
- 现有夜间链路是：
  - `enter_night` -> `_handle_enter_night` -> `gc.enter_night_phase_v2()`（结盟/夜访逻辑）
  - 未见触发 `gc.generate_night_chat()` 的路由。

### 4. 数据消费链（GameState / 前端）
- 数据写入点：
  - `backend/game_controller.py`: 第 64 行 `_night_chat_data: dict = {}`
  - `backend/game_controller.py`: 第 5893 行 `self._night_chat_data = chat_data`
- 读取点：
  - `backend/game_controller.py`: `spy_night_chat()`（第 6347 行）读取 `_night_chat_data["chat_messages"]` / `has_evidence` / `evidence_tag`
  - `backend/game_controller.py`: `record_chat_evidence()`（第 6401 行）读取 `_night_chat_data["evidence_tag"]`
- 前端消费：
  - `Godot前端工程/autoload/network_manager.gd` 定义 `spy_chat_result_received` / `record_chat_result_received` 信号（第 40-41 行）
  - 但 `server.py` 未注册对应 type，且当前前端 `night_ui.gd` 未见调用 `spy_chat`/`record_chat` 请求。
- 结论：`_night_chat_data` 存在后端缓存链，但与当前 WebSocket 路由/前端操作链路存在断点。
- **待人工 review**：`dist` 构建版本是否存在独立路由改动（本次未发现）。

### 5. prompts.json 模板
- `backend/prompts.json`：
  - `chat_agent_system_prompt`（`module: "chat_system"`）
  - `chat_agent_user_prompt`（`module: "chat_system"`）
- 使用检索：
  - `backend/chat_system.py` 第 54 行调用 `chat_agent_system_prompt`
  - `backend/chat_system.py` 第 98 行调用 `chat_agent_user_prompt`
  - 未检索到其他 `.py` 文件调用这两个模板。
- 共享性判断：当前仅 `chat_system.py` 使用，未见跨模块共享。

### 6. 初步结论（供人工 review）
- [ ] 完全可删
- [ ] 入口已断，代码可删但需先确认前端不消费
- [x] 还在跑，不能删（`ChatSystem.generate_night_chat` 仍被 `GameController` 调用）
- [x] 待人工 review：`_handle_spy_chat/_handle_record_chat` 已定义但未注册到 `handlers`，夜聊监听链可能为半废弃状态

---

## B. event_templates.py 扫描结果

### 1. 被谁 import
- `backend/event_system.py`: 第 17 行：`from .event_templates import EVIDENCE_HINT_TEXTS, EVENT_TEMPLATES, RESULT_TEMPLATES`
- `backend/event_system.py`: 第 172/373/401/418/439 行函数内重复导入
- `test_module4.py`: 第 4 行：`from backend.event_templates import EVIDENCE_HINT_TEXTS, EVENT_TEMPLATES, RESULT_TEMPLATES`
- `dist/server/_internal/backend/event_system.py`: 对应同名导入（第 17/172/373/401/418/439 行）

### 2. 公共方法 / 类调用方
- 本模块无类/函数，公共导出为常量：
  - `EVENT_TEMPLATES`：
    - `backend/event_system.py` 第 17/401/403/407 行
    - `test_module4.py` 第 4/8/9/12/150 行
  - `EVIDENCE_HINT_TEXTS`：
    - `backend/event_system.py` 第 17/172/193/373/387/418/430 行
    - `test_module4.py` 第 4/35/36 行
  - `RESULT_TEMPLATES`：
    - `backend/event_system.py` 第 17/439/441 行
    - `test_module4.py` 第 4/16/17/18/19 行

### 3. WebSocket handler
- `server.py` 中无直接 `event_templates` 路由。
- 间接链路：
  - 多个消息（如 `start_move`/`movement_done`/`play_cards`）进入 `GameController`
  - `GameController` 在工作阶段调用 `EventSystem`（例如第 5102/5369 行等）
  - `EventSystem` 内部使用 `event_templates` 常量。
- 即：无直接 handler -> module 映射，属于间接依赖。

### 4. 数据消费链（GameState / 前端）
- `event_templates` 产出的数据主要进入事件展示字段（非 `GameState` 持久字段）：
  - `event_name` / `description` / `prompt`
  - `has_evidence_hint` / `evidence_hint`
- 前端消费：
  - `Godot前端工程/scripts/event_popup.gd` 第 396-403 行读取上述字段并显示。
- `GameState` 中未见直接存储 `EVENT_TEMPLATES` 原始条目。
- **待人工 review**：`EventSystem` 已注明 v2 动态骨架为主、旧模板接口保留兼容（`select_event/build_event_display/resolve_event`），实际运行命中比例需运行期验证。

### 5. prompts.json 模板
- 未发现 `module: "event_templates"` 专属 prompt 模板。
- 与本模块功能相关的文本来源主要是 Python 常量字典，不走 `prompts.json`。

### 6. 初步结论（供人工 review）
- [ ] 完全可删
- [ ] 入口已断，代码可删但需先确认前端不消费
- [x] 还在跑，不能删（`EventSystem` 仍有直接导入与使用）
- [x] 待人工 review：v2 主链与旧模板兼容链并存，需确认旧接口是否仍被触发

---

## C. play.py 扫描结果

### 1. 被谁 import
- 按全项目检索 `from .play import` / `import .play` / `from backend.play import` / `import backend.play`：
  - 未命中

### 2. 公共方法 / 类调用方
- 公共符号（`CLIGame`, `QuitGame`, `phase_*`, `show_ending`）调用情况：
  - 仅 `backend/play.py` 文件内部被调用
  - 入口为 `if __name__ == "__main__": game = CLIGame(); game.run()`（第 428-430 行）

### 3. WebSocket handler
- `server.py` 无任何消息 type 路由到 `play.py`。
- `play.py` 为本地 CLI 入口，不参与 WebSocket handler 映射。

### 4. 数据消费链（GameState / 前端）
- `play.py` 通过 `GameController` 直接读取/展示状态（终端输出），未见前端 `.gd` 消费链。
- 未发现 `play.py` 生成并写入新的 `GameState` 专有字段。

### 5. prompts.json 模板
- `play.py` 未直接调用 `PromptRegistry.render(...)`，无专属 prompt 模板绑定。
- 间接会触发 `GameController/AIService` 的 prompt（运行时路径），但不属于 `play.py` 独占模板。

### 6. 初步结论（供人工 review）
- [ ] 完全可删
- [x] 入口已断，代码可删但需先确认前端不消费（前端与 WebSocket 均不依赖）
- [ ] 还在跑，不能删
- [x] 待人工 review：是否仍需保留“命令行试玩”调试入口供开发使用

---

## D. test_negotiation_behavior.py 扫描结果

### 1. 被谁 import
- 按全项目检索 `from .test_negotiation_behavior import` / `import .test_negotiation_behavior` / `from backend.test_negotiation_behavior import` / `import backend.test_negotiation_behavior`：
  - 未命中

### 2. 公共方法 / 类调用方
- `run_extortion(...)`：
  - 仅在本文件 `main()` 内调用（第 77/78 行）
- `main()`：
  - 仅在本文件 `if __name__ == "__main__": asyncio.run(main())`（第 96-97 行）触发
- 其他常量（`ACCIDENT_TEXT`, `ACT1_TEXT`）仅本文件内部使用（第 13/14/49/50 行）

### 3. WebSocket handler
- `server.py` 无消息 type 路由到该测试脚本。
- 本脚本为独立测试入口，不在服务端 handler 链上。

### 4. 数据消费链（GameState / 前端）
- 本脚本调用 `AIService.generate_npc_extortion(...)` 做行为对比打印，不写入 `GameState`，无前端 `.gd` 消费链。

### 5. prompts.json 模板
- 脚本本身不直接调用 `PromptRegistry`，但间接经过 `AIService`：
  - `backend/ai_service.py` 第 611 行：`negotiation_extortion_actor_user_prompt`
  - 同函数还调用 `act2_actor_system`（第 601 行）
- 共享性：
  - 该两类模板属于协商/剧情通用能力，非本测试脚本独占。

### 6. 初步结论（供人工 review）
- [ ] 完全可删
- [x] 入口已断，代码可删但需先确认前端不消费（前后端主链未引用）
- [ ] 还在跑，不能删
- [x] 待人工 review：是否仍用于人工回归 AI 行为稳定性（20 次抽样对比）

---

## E. game_over_ui.gd 扫描结果

### 1. 被谁 import
- 该模块为 GDScript，不适用 Python 的 `from .xxx import` 规则。
- 场景/节点引用命中：
  - `Godot前端工程/scenes/game_ui.tscn`: 第 9 行 `res://scripts/game_over_ui.gd`
  - `Godot前端工程/scenes/game_ui.tscn`: 存在 `GameOverUI` 节点（第 782 行及其子节点）
  - `Godot前端工程/scripts/game_ui.gd`: 第 9 行 `@onready var game_over_ui = $GameOverUI`
- **待人工 review**：本条与“import grep”要求语义不完全一致（语言不同）。

### 2. 公共方法 / 类调用方
- `setup(data: Dictionary)`：
  - 理论调用方应为 `game_ui.gd`；但当前检索未见 `game_over_ui.setup(...)` 实际调用。
- `_on_replay()` 为本脚本内部按钮回调。

### 3. WebSocket handler
- `server.py` 中无消息 type 路由到 `game_over_ui.gd`（前端脚本不会直接作为后端 handler 目标）。
- 与结局相关后端消息为：
  - `get_ending_summary` -> `_handle_get_ending_summary` -> 返回 `ending_summary`
- 前端 `NetworkManager` 对 `game_over` 已标注废弃并忽略（`network_manager.gd` 第 428-430 行）。

### 4. 数据消费链（GameState / 前端）
- `game_over_ui.gd` 消费字段：
  - `game_result`
  - `evidence_collected`
  - `evidence_types_count`
- 但当前主链为：
  - `game_ui.gd` 注释标明“新链路通过 ending_summary 展示结局，GameOverUI 不再使用”（第 916 行）
  - 结局展示改走 `ending_ui.gd` / `memory_view_popup.gd`（第 969/971/989 行）
- 结论：`game_over_ui.gd` 在场景中仍挂载，但功能链路疑似废弃。
- **待人工 review**：是否仍保留旧回退入口（当前看不到实际调用）。

### 5. prompts.json 模板
- 未发现与 `game_over_ui.gd` 对应的 `prompts.json` 模板。

### 6. 初步结论（供人工 review）
- [ ] 完全可删
- [x] 入口已断，代码可删但需先确认前端不消费
- [ ] 还在跑，不能删
- [x] 待人工 review：场景节点仍存在，需确认是否保留为兜底 UI

---

## 跨模块异常与模糊点（统一列出）

- `server.py` 存在 `_handle_spy_chat/_handle_record_chat` 方法，但 `handlers` 字典未注册对应消息 type：**待人工 review**（疑似半废弃链路）。
- `backend/game_controller.py` 存在 `generate_night_chat()/spy_night_chat()/record_chat_evidence()`，但当前 `enter_night_phase_v2` 不触发夜聊生成：**待人工 review**（是否预期改版后停用）。
- `event_templates.py` 在 `EventSystem v2` 背景下仍被导入并用于兼容接口与提示文本：**待人工 review**（兼容代码是否还要继续保留）。
- `game_over_ui.gd` 仍在场景树中，但主流程注释声明废弃：**待人工 review**（死代码 vs 回退入口）。
- `dist/server/_internal/*` 与源码重复命中：**待人工 review**（部署时是否真正走 dist 目录）。

