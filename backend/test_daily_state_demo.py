"""
DailyStateService 独立验证 demo

用法:
    python -m backend.test_daily_state_demo

验证内容:
1. token 用量是否可控(目标输出 < 1800 token)
2. JSON 解析成功率
3. 内容质量(老王演得像不像)
4. 跨天连续性(Day 2 能否合理承接 Day 1)
5. 中期目标 today_intent 推进逻辑
6. AI 是否听话:不输出 progress_change,不预测他人今天
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime

from backend.daily_state_service import DailyStateService

OUTPUT_PATH = Path(__file__).resolve().parent / "logs" / "daily_state_demo.json"


# ===== Mock 数据:模拟 Day 1-3 的昨日记忆和关系账本 =====

MOCK_DAY1 = {
    "yesterday_memories_text": "(这是第一天,没有昨天的事件)",
    "relationship_snapshot_text": "(关系平稳,大家都还没熟)",
    "midterm_goal": {
        "id": "goal_laowang_001",
        "title": "给孙子修好防尸铃",
        "narrative": "老王这几天在偷偷攒公司里的废零件,想给孙子修一个会响的防尸铃。",
        "progress": 0,
        "completion_event_hint": "老王在某个外露细节里展示铃铛或它的成品/半成品",
    },
}

MOCK_DAY2 = {
    "yesterday_memories_text": "昨天工作时,希尔达在仓库逮住老王翻一个工具箱,当面阴阳了一句:'老王,你最近手脚很勤啊'。老王装傻笑了笑没说话,但心里很堵。",
    "relationship_snapshot_text": "他跟希尔达的关系最近变紧张了——昨天那一句让他记住了。其他人的关系基本没变。",
    "midterm_goal": {
        "id": "goal_laowang_001",
        "title": "给孙子修好防尸铃",
        "narrative": "老王这几天在偷偷攒零件,想给孙子修一个会响的防尸铃。昨天差点被希尔达撞破。",
        "progress": 25,
        "completion_event_hint": "老王在某个外露细节里展示铃铛或它的成品/半成品",
    },
}

MOCK_DAY3 = {
    "yesterday_memories_text": "昨天他在茶水间偷听到希尔达跟阿花说:'最近仓库的小工具老是不见,我看肯定有人偷'。老王心里一紧,昨晚没睡好,翻来覆去想要不要把零件先藏起来。",
    "relationship_snapshot_text": "他对希尔达已经从'不太喜欢'升级到'警惕避开'。对阿花产生了一点新的怀疑——她那天的表情有点奇怪。",
    "midterm_goal": {
        "id": "goal_laowang_001",
        "title": "给孙子修好防尸铃",
        "narrative": "零件已经攒到差一颗螺丝就够了。但仓库巡查变严,风险变大。孙子的画画比赛就在今天下班后。",
        "progress": 70,
        "completion_event_hint": "老王在某个外露细节里展示铃铛或它的成品/半成品",
    },
}


async def main():
    PLAYER_NAME = "陈大锤"  # 测试用玩家名(实际游戏中由 PlayerState.name 动态决定)
    print("=" * 80)
    print("DailyStateService Demo v0.2 - 老王 Day 1-3")
    print("=" * 80)

    results = []
    mock_days = [
        (1, MOCK_DAY1),
        (2, MOCK_DAY2),
        (3, MOCK_DAY3),
    ]

    for day, mock in mock_days:
        print(f"\n{'-' * 80}")
        print(f"--- 生成老王 Day {day} 的 daily_state ---")
        print(f"{'-' * 80}")
        result = await DailyStateService.generate_daily_state(
            npc_id="laowang",
            day=day,
            yesterday_memories_text=mock["yesterday_memories_text"],
            relationship_snapshot_text=mock["relationship_snapshot_text"],
            midterm_goal_current=mock["midterm_goal"],
            player_name=PLAYER_NAME,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        results.append(result)

    # 写到输出文件
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "demo_run_at": datetime.now().isoformat(),
                "regulation_version": "v0.2",
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\n{'=' * 80}")
    print(f"✅ Demo 完成,完整输出已写入: {OUTPUT_PATH}")
    print(f"{'=' * 80}")

    # 简单统计
    statuses = [r.get("status", "unknown") for r in results]
    status_counts = {s: statuses.count(s) for s in set(statuses)}
    print(f"\n状态分布: {status_counts}")

    # 关键检查:AI 输出中是否出现 progress_change(不该出现)
    has_progress_change = []
    for r in results:
        mg_state = r.get("midterm_goal_state", {})
        if isinstance(mg_state, dict) and "progress_change" in mg_state:
            has_progress_change.append(r.get("day"))
    if has_progress_change:
        print(f"⚠️  以下天数的输出仍包含 progress_change(应被过滤): {has_progress_change}")
    else:
        print(f"✅ 所有输出都不含 progress_change 字段(过滤生效)")


if __name__ == "__main__":
    asyncio.run(main())
