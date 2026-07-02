"""
⚠️  DEPRECATED MODULE — DO NOT USE FOR NEW FEATURES  ⚠️

This module is the EventSystem v1-era static template constants.
It is kept ONLY for backward compatibility with legacy fallback paths
in event_system.py.

The current main path is EventSystem v2's dynamic skeleton system
(see backend/data/skeletons/ and event_system.py's v2 builders).

DO NOT:
- Import this module in new features.
- Add new entries to EVENT_TEMPLATES / EVIDENCE_HINT_TEXTS / RESULT_TEMPLATES.
- Use this module's data structures as a reference for new event logic.

PLANNED REMOVAL:
When EventSystem v2 fallback paths are fully refactored to use
data/skeletons/ + data/fallback/ CSVs, this module will be deleted.

Last reviewed: 2026-05-13
Migration tracking: see project handoff brief section 7 (technical debt)
"""

"""
事件模板定义。
MVP阶段：10个单人事件（每房间2个），硬编码结果文本。
后续接AI时只需替换 result_templates 即可。
"""

EVENT_TEMPLATES: list[dict] = [
    {
        "id": "EVT_OFFICE_001",
        "name": "消失的报表",
        "room": "office",
        "description": "你正在工位上埋头苦干，突然发现昨天做好的销售报表不见了。电脑桌面上只剩一个空文件夹和一张便利贴，上面写着“谢谢”。",
        "prompt_to_player": "你的报表被偷了，而且小偷还留了张感谢条。你要怎么应对这件事？",
    },
    {
        "id": "EVT_OFFICE_002",
        "name": "打印机叛变",
        "room": "office",
        "description": "打印机突然发出巨响，开始疯狂吐出不明文件。仔细一看，全是公司内部的绩效排名表——你排在倒数第二，倒数第一是那个已经被吃掉的实习生。",
        "prompt_to_player": "绩效排名被公开处刑了，而且你排名垫底。在同事看到之前，你打算？",
    },
    {
        "id": "EVT_MEETING_001",
        "name": "灵魂PPT",
        "room": "meeting",
        "description": "你打开会议室的投影仪准备工作，屏幕上赫然显示着上一场会议的PPT残留——标题写着“如何在5天内找到卧底（经理专用·绝密）”。",
        "prompt_to_player": "你看到了经理的绝密PPT，上面列着所有人的可疑行为清单。你的反应是？",
    },
    {
        "id": "EVT_MEETING_002",
        "name": "录音笔风波",
        "room": "meeting",
        "description": "你在会议桌底下发现一支还在录音的录音笔。红灯一闪一闪的，不知道已经录了多久，也不知道是谁放的。",
        "prompt_to_player": "这支录音笔显然不是你的，但它可能录下了很多有用的东西。你打算怎么处理？",
    },
    {
        "id": "EVT_WAREHOUSE_001",
        "name": "罐头密码",
        "room": "warehouse",
        "description": "你在整理货架时，发现一批罐头上的生产日期明显被涂改过——原来的日期被白色涂改液盖住了，新日期是用圆珠笔手写的。字迹歪歪扭扭，还带着墨水味。",
        "prompt_to_player": "你发现了涂改日期的铁证。但仓库的监控摄像头正对着你，红灯一闪一闪。你的反应是？",
    },
    {
        "id": "EVT_WAREHOUSE_002",
        "name": "神秘纸箱",
        "room": "warehouse",
        "description": "仓库角落堆着几个没有标签的纸箱。你不小心碰倒了一个，里面哗啦啦掉出来一堆东西——全是经理从总部订购的个人用品：纯金牙签、镶钻鼠标垫、还有一本《如何用公款装修浴室》。",
        "prompt_to_player": "经理的私人包裹被你撞开了，里面全是腐败铁证。但你听到仓库门外传来脚步声。怎么办？",
    },
    {
        "id": "EVT_PANTRY_001",
        "name": "微波炉惊魂",
        "room": "pantry",
        "description": "你把午餐放进微波炉，按下启动键。三十秒后，微波炉里传出一声惨叫——打开一看，你热的不是你的饭盒，是某同事落在里面的假发。整个茶水间弥漫着一股烧焦蛋白质的味道。",
        "prompt_to_player": "你把某同事的假发烤焦了。对方在公司里出了名地记仇。你该怎么善后？",
    },
    {
        "id": "EVT_PANTRY_002",
        "name": "咖啡机审判",
        "room": "pantry",
        "description": "你去倒咖啡，发现咖啡机上贴了一张匿名纸条：“昨天是谁把咖啡豆换成了过期罐头磨成的粉？全办公室拉了一整天肚子。经理说要彻查。”",
        "prompt_to_player": "全公司都在找“咖啡投毒犯”，虽然不是你干的，但你现在手上正端着一杯咖啡。",
    },
    {
        "id": "EVT_RECEPTION_001",
        "name": "神秘访客",
        "room": "reception",
        "description": "一个戴着墨镜、穿着风衣的神秘人走进接待区，直接走向你，低声说：“我是来找那个……你懂的……那个人。”他说话时一直在偷偷环顾四周。",
        "prompt_to_player": "这个人看起来像是来找卧底接头的，但你不确定他到底是友军还是公司派来试探你的。",
    },
    {
        "id": "EVT_RECEPTION_002",
        "name": "快递炸弹",
        "room": "reception",
        "description": "你在签收今天的快递，发现其中一个包裹收件人写的是“末日调查局·XXX（你的真名）”。寄件人是“一个关心你的朋友”。包裹还在你手里，前台的监控正对着你。",
        "prompt_to_player": "有人用你的真实身份寄了个包裹到公司。你需要在被别人看到之前处理掉它。",
    },
]

EVIDENCE_HINT_TEXTS: dict[str, list[str]] = {
    "product_fake": [
        "你注意到旁边货架上有几罐罐头，生产日期的字体颜色明显和其他的不一样。",
        "地上散落着几张被撕碎的旧标签，依稀能看到一个比现在早两年的日期。",
        "角落里有一桶白色涂改液，瓶盖是开着的，旁边还有一支圆珠笔。",
    ],
    "finance_fake": [
        "你扫到桌上一份文件的角落，上面有两列数字——一列标着“内部”，一列标着“报税用”，数字差了十倍。",
        "废纸篓里有一张被揉成团的纸，展开后发现是一份写着“账外资金”的转账记录。",
        "文件柜没锁好，缝隙里露出一个红色封面的本子，封面写着“第二本账”。",
    ],
    "employee_abuse": [
        "你看到墙上贴着的排班表，上面有人用红笔写着“本月无休，违者罚款”。",
        "桌上有一份被遗忘的薪资条，实发金额只有应发的一半，备注写着“态度调整扣款”。",
        "垃圾桶里有一封被丢弃的匿名投诉信，写着“已经连续工作了三十天”。",
    ],
    "safety_hazard": [
        "你闻到一股刺鼻的化学品味道，循着味道发现墙角有一处正在渗液的裂缝。",
        "消防栓的封条上写着“上次检查：三年前”，灭火器的压力表指针已经归零。",
        "通风口传来一阵怪味，你凑近发现滤网上积了厚厚一层绿色的不明物质。",
    ],
    "corruption": [
        "你瞥见一张快递单，收件人是经理的私人地址，物品名称写着“定制纯金浴缸配件”。",
        "桌上有一通未挂断的电话，听筒里传来：“……上次那笔回扣已经到账了……”。",
        "文件堆里混着一份标着“机密”的合同，甲方和乙方的法人代表签名笔迹一模一样。",
    ],
}

RESULT_TEMPLATES: dict[str, list[dict]] = {
    "steady": [
        {
            "text": "你用冷静且专业的态度处理了这件事。周围的同事对你投来了略带敬意的目光——在这个疯人院一般的公司里，一个正常人反而显得格外可疑。",
            "affinity_delta": 5,
            "suspicion_delta": 3,
            "gold_delta": 0,
        },
        {
            "text": "你稳妥地把事情糊弄了过去。没人注意到你，也没人记住你。在这个公司里，透明人可能是最安全的身份。",
            "affinity_delta": 3,
            "suspicion_delta": -2,
            "gold_delta": 5,
        },
        {
            "text": "你的反应合情合理，完全符合一个普通打工人的行为模式。太正常了，正常到让人想在你背后贴一张“此人可能是卧底”的标签。",
            "affinity_delta": 2,
            "suspicion_delta": 5,
            "gold_delta": 0,
        },
    ],
    "contrast": [
        {
            "text": "你的反应让所有人都愣住了——这个画风怎么突然不对了？同事们面面相觑，不确定你是在演戏还是真的精神状态出了问题。但至少，没人还在想卧底的事了。",
            "affinity_delta": -3,
            "suspicion_delta": -5,
            "gold_delta": 0,
        },
        {
            "text": "你诡异的表现引起了一阵骚动。有人在背后小声嘀咕：“这人今天吃错药了吧？”但也有人觉得你挺有意思的，主动过来搭话。",
            "affinity_delta": 5,
            "suspicion_delta": 3,
            "gold_delta": 0,
        },
        {
            "text": "场面一度十分尴尬。你说出口的话和你的表情完全对不上号，空气凝固了三秒钟。然后某同事打了个哈欠，算是帮你解了围。",
            "affinity_delta": 0,
            "suspicion_delta": 0,
            "gold_delta": 0,
        },
        {
            "text": "你的迷惑行为成功转移了所有人的注意力。虽然现在大家都觉得你脑子有点问题，但好处是没人怀疑一个脑子有问题的人会是卧底。",
            "affinity_delta": -5,
            "suspicion_delta": -8,
            "gold_delta": 0,
        },
    ],
    "crazy": [
        {
            "text": "你彻底放飞自我，上演了一出让全办公室都目瞪口呆的大戏。经理从办公室探出头来看了一眼，又默默缩了回去——连他都不想掺和。你今天在公司的风评从“可能是卧底”变成了“可能是疯子”。",
            "affinity_delta": -8,
            "suspicion_delta": -15,
            "gold_delta": 0,
        },
        {
            "text": "你的行为已经超越了人类的理解范畴。在场所有同事集体陷入了沉默，然后不约而同地选择假装什么都没发生。你注意到某同事默默把手里的零食收了起来，生怕你抢。",
            "affinity_delta": -10,
            "suspicion_delta": -10,
            "gold_delta": 0,
        },
        {
            "text": "事情彻底失控了。你的发疯表演引来了经理的注意——他用八只眼睛盯着你看了整整十秒钟，然后在小本子上写了些什么。好消息是大家都被你逗笑了。坏消息是经理没笑。",
            "affinity_delta": 5,
            "suspicion_delta": 15,
            "gold_delta": 0,
        },
        {
            "text": "你的癫狂行为居然歪打正着——某同事被你吓得一个激灵，手里的文件掉了一地。文件里似乎夹着一些不该出现的东西……不过你太忙着发疯了，没来得及看清。",
            "affinity_delta": -3,
            "suspicion_delta": -5,
            "gold_delta": 10,
        },
    ],
}
