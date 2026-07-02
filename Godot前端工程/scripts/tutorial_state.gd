extends Node

## 新手引导状态管理器(autoload 单例)
## ⚠️ 必须 extends Node,不能是 Control
## 用法: TutorialState.is_triggered("first_evidence_card")
##
## 设计原则:
## - 进程内存活,关闭游戏后自动清空(重开游戏视为新一局,引导重新出现)
## - 不持久化(不依赖账号系统)

var _triggered: Dictionary = {}

const TUTORIAL_KEYS: Array[String] = [
    "first_task_selection",
    "first_dual_event",
    "first_evidence_card",
    "first_voting",
    "first_night",
    "first_blackmail_spread",
    "first_extortion",
    "first_plea",
    "first_solo_event",
    "first_duo_event",
    "first_event_record",
]


func is_triggered(key: String) -> bool:
    """检查某个引导是否已触发过。"""
    return _triggered.get(key, false)


func mark_triggered(key: String) -> void:
    """标记某个引导已触发,后续不再弹出。"""
    if key.is_empty():
        return
    _triggered[key] = true
    print("[TutorialState] marked: %s" % key)


func reset_all() -> void:
    """重置所有 flags,所有引导可重新触发(开发调试用)。"""
    _triggered.clear()
    print("[TutorialState] all flags reset")


func get_triggered_count() -> int:
    """已触发的引导数量。"""
    return _triggered.size()
