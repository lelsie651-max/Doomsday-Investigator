"""
勒索/祈求 AI 决策行为对比测试。
不是单元测试,而是定性观察:不同性格 NPC 面对相同情景的决策差异。
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ai_service import AIService
from backend.data_loader import DataLoader

ACCIDENT_TEXT = "阿强不小心把经理刚签完字的报销单卷进了碎纸机,办公室所有人都听见了那一声咔嚓"
ACT1_TEXT = "阿强紧张地盯着碎纸机,纸屑还在飞舞。" + ACCIDENT_TEXT

async def run_extortion(npc_id: str, runs: int = 5):
    dl = DataLoader()
    npc_profile = dl.get_npc_profile(npc_id) if hasattr(dl, "get_npc_profile") else None
    if npc_profile is None:
        # 回退方案: 直接读 npc_profiles.json
        import json
        with open("backend/data/npc_profiles.json", encoding="utf-8-sig") as f:
            all_profiles = json.load(f)
        npc_profile = all_profiles.get(npc_id, {})

    npc_name = npc_profile.get("name", npc_id)

    print(f"\n{'='*60}")
    print(f"测试 NPC: {npc_name} (ID: {npc_id})")
    print(f"  identity: {npc_profile.get('identity', '')[:50]}...")
    print(f"  aim: {npc_profile.get('aim', '')[:50]}...")
    print(f"  extortion_price: [{npc_profile.get('extortion_price_min', 20)}, "
          f"{npc_profile.get('extortion_price_max', 80)}]")
    print(f"{'='*60}")

    agree_count = 0
    method_count = {"金钱": 0, "投票": 0, "无": 0}

    for i in range(runs):
        result = await AIService.generate_npc_extortion(
            npc_profile=npc_profile,
            npc_name=npc_name,
            npc_identity=npc_profile.get("identity", ""),
            npc_aim=npc_profile.get("aim", ""),
            npc_memory_rel=f"{npc_name}对其他同事的看法:暂无明确记忆。",
            player_name="阿强",
            room_name="主办公区",
            task_text="处理报销单",
            act1_text=ACT1_TEXT,
            accident_text=ACCIDENT_TEXT,
            amount_min=npc_profile.get("extortion_price_min", 20),
            amount_max=min(npc_profile.get("extortion_price_max", 80), 50),  # 玩家钱包 50 封顶
            alive_npc_names=["老王", "小李", "阿花", "大壮", "周姐"].__iter__().__next__() if False else [n for n in ["老王","小李","阿花","大壮","周姐"] if n != npc_name],
        )
        agree = result["agree"]
        method = result["method"]
        amount = result["amount"]
        if agree:
            agree_count += 1
        method_count[method] = method_count.get(method, 0) + 1

        marker = "✅勒索" if agree else "❌不勒索"
        amount_str = f" {amount}金币" if method == "金钱" else (f" 投{result.get('target_name','?')}" if method == "投票" else "")
        print(f"  Run {i+1}: {marker} | {method}{amount_str}")
        print(f"    台词: {result['story'][:80]}...")

    print(f"\n  统计: 勒索 {agree_count}/{runs} 次")
    print(f"  方式分布: {method_count}")
    return {"npc": npc_name, "agree_rate": agree_count / runs, "methods": method_count}


async def main():
    print("\n🧪 NPC 性格驱动决策对比测试")
    print("场景: 阿强把经理报销单卷进碎纸机 → NPC 是否勒索阿强?")

    # 测试胆小型 vs 贪婪型
    ahua_result = await run_extortion("ahua", runs=20)
    zhoujie_result = await run_extortion("zhoujie", runs=20)

    print("\n" + "="*60)
    print("最终对比")
    print("="*60)
    print(f"阿花(胆小): 勒索率 {ahua_result['agree_rate']*100:.0f}%")
    print(f"周姐(贪婪): 勒索率 {zhoujie_result['agree_rate']*100:.0f}%")
    print("\n方式分布对比摘要")
    print(f"- 阿花: 金钱={ahua_result['methods'].get('金钱', 0)}, 投票={ahua_result['methods'].get('投票', 0)}, 无={ahua_result['methods'].get('无', 0)}")
    print(f"- 周姐: 金钱={zhoujie_result['methods'].get('金钱', 0)}, 投票={zhoujie_result['methods'].get('投票', 0)}, 无={zhoujie_result['methods'].get('无', 0)}")
    print()
    if zhoujie_result['agree_rate'] >= ahua_result['agree_rate']:
        print("✅ 贪婪型 NPC 勒索倾向 ≥ 胆小型,符合性格预期")
    else:
        print("⚠️ 贪婪型 NPC 勒索率反而低于胆小型,prompt 可能需要调整")
    print("\n注:20 次样本量仍属定性观察,如需统计意义可进一步增加样本。")


if __name__ == "__main__":
    asyncio.run(main())
