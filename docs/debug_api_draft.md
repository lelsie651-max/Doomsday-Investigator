# Debug 接口请求/响应 JSON 草案（V1）

## 消息类型
- 请求：`debug_seed_work_snapshot`
- 响应：`debug_seeded`

## 请求示例
```json
{
  "type": "debug_seed_work_snapshot",
  "data": {
    "player_task_id": "task_office_001",
    "npc_task_ids": {
      "laowang": "task_office_001",
      "xiaoli": "task_office_002",
      "ahua": "task_office_003",
      "dazhuang": "task_meeting_001",
      "zhoujie": "task_meeting_001"
    },
    "hour": 0,
    "repeat_task_count": 5,
    "social_energy_left": 1,
    "social_event_used": false,
    "strict": true,
    "boss_room": "boss_office"
  }
}
```

## 成功响应示例
```json
{
  "type": "debug_seeded",
  "data": {
    "ok": true,
    "phase": "working",
    "day": 1,
    "hour": 0,
    "player_task_id": "task_office_001",
    "player_room": "office",
    "social_energy_left": 1,
    "social_event_used": false,
    "npc_rooms": {
      "laowang": "office",
      "xiaoli": "office",
      "ahua": "office",
      "dazhuang": "meeting",
      "zhoujie": "meeting"
    },
    "coworkers": {
      "room": "office",
      "npc_ids": ["laowang", "xiaoli", "ahua"],
      "npc_names": ["老王", "小李", "阿花"],
      "boss_present": false
    },
    "route_preview": {
      "event_route": "choice_required",
      "choice_variant": "duo_or_group",
      "participant_npc_ids": [],
      "observer_npc_ids": [],
      "debug_scenario_code": "S5",
      "debug_choice_source": "duo_or_group"
    }
  }
}
```

## 错误响应示例
```json
{
  "type": "error",
  "data": {
    "error_type": "debug_seed_error",
    "message": "缺少NPC任务映射: laowang, xiaoli"
  }
}
```

## 字段约定
- `strict=true`：要求 `npc_task_ids` 必须覆盖所有存活NPC。
- `repeat_task_count`：会把每个角色任务复制 N 小时，确保复测稳定。
- `route_preview`：仅用于调试，不会真正推进事件流程。
