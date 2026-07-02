"""
AI管线测试 - 测试记忆系统 + DeepSeek API调用

使用方法：
  python test_ai_pipeline.py

注意：需要在.env中配置有效的DEEPSEEK_API_KEY
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.ai_service import AIService
from backend.enums import *
from backend.game_state import GameState
from backend.memory_system import MemorySystem
from backend.state_manager import StateManager


def test_memory_system():
    """测试记忆系统（不需要API）"""
    print("=" * 50)
    print("测试记忆系统")
    print("=" * 50)

    state = GameState.new_game()
    sm = StateManager(state)
    mem = MemorySystem()

    # 测试1：身份获取
    identity = MemorySystem.get_identity("xiaoli")
    assert "变异鼠人" in identity
    assert "奋斗逼" in identity
    print(f"✅ 小李身份：{identity[:40]}...")

    # 测试2：关系翻译
    assert MemorySystem.translate_affinity(60) == "非常喜欢"
    assert MemorySystem.translate_affinity(-60) == "恨之入骨"
    assert MemorySystem.translate_suspicion(90) == "几乎确信是卧底"
    assert MemorySystem.translate_suspicion(10) == "没什么怀疑"
    print("✅ 数值翻译正确")

    # 测试3：关系账本文本
    sm.modify_suspicion("xiaoli", "player", 40)  # 怀疑度变为60
    sm.modify_affinity("xiaoli", "laowang", -30)  # 讨厌老王
    rel_text = MemorySystem.build_relationship_text(
        "xiaoli", state.relationships, state.npcs
    )
    assert "极度怀疑" in rel_text  # 对玩家
    assert "讨厌" in rel_text  # 对老王
    print(f"✅ 小李关系账本：\n{rel_text}")

    # 测试4：事件记忆
    mem.add_memory("xiaoli", "第1天，仓库：玩家以霸道总裁般的态度壁咚了老王")
    mem.add_memory("xiaoli", "第1天，投票：周姐被投出局")
    memories = mem.get_memories("xiaoli")
    assert len(memories) == 2
    print(f"✅ 小李记忆（{len(memories)}条）：{memories}")

    # 测试5：批量添加目击记忆
    mem.add_event_memory_for_witnesses(
        ["laowang", "xiaoli", "dazhuang"],
        day=2,
        room_name="茶水间",
        event_summary="玩家以资本家附体的态度给对方画饼，表现得中规中矩。",
    )
    assert len(mem.get_memories("laowang")) == 1
    assert len(mem.get_memories("xiaoli")) == 3  # 之前2条+新1条
    assert "茶水间" in mem.get_memories("dazhuang")[0]
    print("✅ 批量目击记忆正确")

    # 测试6：事件摘要生成
    summary = MemorySystem.generate_event_summary(
        "【正常】真诚的", "掏出一罐过期罐头请对方吃", "contrast", "仓库"
    )
    assert "真诚" in summary
    assert "罐头" in summary
    print(f"✅ 事件摘要：{summary}")

    # 测试7：构建完整NPC信息包
    info = mem.build_npc_info_for_ai("xiaoli", state.relationships, state.npcs)
    assert info["name"] == "小李"
    assert "变异鼠人" in info["identity"]
    assert len(info["memories"]) == 3
    assert "极度怀疑" in info["relationships"]
    print("✅ 小李AI信息包完整")

    # 测试8：记忆滚动窗口
    for i in range(15):
        mem.add_memory("dazhuang", f"记忆条目{i}")
    assert len(mem.get_memories("dazhuang")) == 10  # 最多10条
    assert "记忆条目5" in mem.get_memories("dazhuang")[0]  # 前5条被淘汰
    print("✅ 记忆滚动窗口正确（最多10条）")

    print("\n🎉 记忆系统全部测试通过！\n")


async def test_ai_service():
    """测试DeepSeek API调用（需要有效API Key）"""
    print("=" * 50)
    print("测试AI服务（DeepSeek API）")
    print("=" * 50)

    from backend.ai_service import DEEPSEEK_API_KEY

    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-你的实际API密钥":
        print("⚠️ 未配置API Key，跳过AI调用测试")
        print("  请在.env文件中设置 DEEPSEEK_API_KEY")
        return

    # 构造测试数据
    npc_infos = [
        {
            "name": "老王",
            "identity": MemorySystem.get_identity("laowang"),
            "relationships": "对玩家：略微警惕，无感\n对小李：没什么怀疑，讨厌",
            "memories": ["第1天，主办公区：玩家表现得很正常，没什么可疑的"],
        },
        {
            "name": "小李",
            "identity": MemorySystem.get_identity("xiaoli"),
            "relationships": "对玩家：有些怀疑，无感\n对老王：没什么怀疑，讨厌",
            "memories": ["第1天，主办公区：发现玩家在翻文件柜"],
        },
    ]

    print("正在调用DeepSeek API（可能需要几秒）...")

    # 测试1：普通事件
    result = await AIService.generate_event_dialogue(
        npc_infos=npc_infos,
        event_description="打印机突然发出巨响，开始疯狂吐出不明文件。",
        event_prompt="绩效排名被公开处刑了，你排名垫底。",
        room_name="主办公区",
        emotion_card_name="资本家附体的",
        emotion_card_tone="满嘴赋能、抓手、底层逻辑",
        action_card_name="熟练地甩锅给实习生",
        action_card_effect="无论发生什么，都是实习生的错",
        combo_type="crazy",
    )

    print(f"\n成功：{result['success']}")
    print(f"原始响应：\n{result.get('raw_response', '')[:500]}\n")

    for name, dialogue in result["dialogues"].items():
        reaction = result["reactions"].get(name, "?")
        aff = result["affinity_deltas"].get(name, 0)
        sus = result["suspicion_deltas"].get(name, 0)
        print(f"【{name}】{dialogue}")
        print(f"  态度：{reaction}  好感{aff:+d}  怀疑{sus:+d}")

    print(f"\n旁白：{result['narrator']}")
    print("✅ 普通事件AI生成成功")

    # 测试2：证据事件
    print("\n--- 测试证据事件 ---")
    result2 = await AIService.generate_event_dialogue(
        npc_infos=[npc_infos[0]],  # 只有老王
        event_description="你在整理货架时，发现一批罐头上的生产日期明显被涂改过。",
        event_prompt="你发现了涂改日期的铁证，但监控正对着你。",
        room_name="仓库",
        emotion_card_name="汗流浃背的",
        emotion_card_tone="极度心虚，说话结巴",
        action_card_name="大喊一声看飞碟",
        action_card_effect="极其弱智的转移注意力",
        combo_type="contrast",
        is_evidence_event=True,
        evidence_category="产品造假",
        evidence_keywords=["涂改日期", "过期销售", "以次充好"],
    )

    print(f"成功：{result2['success']}")
    for name, dialogue in result2["dialogues"].items():
        print(f"【{name}】{dialogue}")
    print(f"旁白：{result2['narrator']}")

    # 检查是否包含证据关键词
    all_text = " ".join(result2["dialogues"].values()) + result2["narrator"]
    has_keyword = any(kw in all_text for kw in ["涂改", "过期", "日期", "以次充好"])
    print(f"包含证据关键词：{'✅ 是' if has_keyword else '⚠️ 否（AI可能没融入，但不阻塞）'}")

    print("\n🎉 AI服务测试完成！")


if __name__ == "__main__":
    # 先测记忆系统（不需要API）
    test_memory_system()

    # 再测AI服务（需要API Key）
    asyncio.run(test_ai_service())
