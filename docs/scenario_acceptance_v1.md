# 五种情况验收表（V1）

## S1 玩家独处
- 前置布置：玩家在目标房间，且该房间无任何NPC。
- 玩家操作：正常进入该小时事件。
- 预期按钮：无 `work_mode` 选择按钮。
- 预期 route：`solo`。
- 预期记忆写入对象：仅玩家侧结果；无在场NPC见证写入。

## S2 房间内有且仅有同任务NPC
- 前置布置：玩家与1名NPC同房且同任务，其他NPC不在该房间。
- 玩家操作：正常进入该小时事件。
- 预期按钮：无 `work_mode` 选择按钮（直接双人主线）。
- 预期 route：`duo`。
- 预期记忆写入对象：`participant_npc_ids`（通常为该同任务NPC）。

## S3 房间内有且仅有1名不同任务NPC
- 前置布置：玩家与1名NPC同房但不同任务，且无同任务NPC。
- 玩家操作：正常进入该小时事件。
- 预期按钮：默认无 `work_mode` 选择按钮；若存在可传播黑料则出现 `blackmail_broadcast` 分支按钮。
- 预期 route：默认 `solo`。
- 预期记忆写入对象：默认按单人主线处理；若走黑料分支则按传播对象写入。

## S4 房间内多人，且都不同任务
- 前置布置：玩家同房有2名及以上NPC，且与玩家均不同任务。
- 玩家操作：正常进入该小时事件。
- 预期按钮：默认无 `work_mode` 选择按钮；若存在可传播黑料则出现 `blackmail_broadcast` 分支按钮。
- 预期 route：默认 `solo`。
- 预期记忆写入对象：默认按单人主线与旁观规则处理；若走黑料分支则按传播对象写入。

## S5 有同任务NPC，且房间内还有其他NPC
- 前置布置：至少1名NPC与玩家同房同任务，且至少1名其他NPC同房不同任务。
- 玩家操作：正常进入该小时事件。
- 预期按钮：默认无 `work_mode` 选择按钮；若存在可传播黑料则出现 `duo` 与 `blackmail_broadcast`。
- 预期 route：默认 `duo`。
- 预期记忆写入对象：
  - `duo`：双人参与NPC写入，其他同房NPC作为观察者轻量影响；
  - `blackmail_broadcast`：按黑料传播对象写入。

## 调试字段（前端面板用）
- `debug_scenario_code`：`S1/S2/S3/S4/S5`
- `debug_choice_source`：`solo` / `duo` / `interaction` / `solo_or_interaction` / `solo_or_blackmail` / `solo_or_blackmail_group` / `duo_or_blackmail_group`
- `debug_route`：`solo` / `duo` / `interaction` / `choice_required`
