from .enums import EvidenceType, Room


class AISafeContext(dict):
    def __repr__(self) -> str:
        return super().__repr__().replace("evidence_", "evidence-")

    def __str__(self) -> str:
        return self.__repr__()


class EvidenceConverter:
    """
    证据标签 → AI Prompt 转换器。

    核心原则：
    - 系统内部使用标签（如 evidence_day1_001_product_fake）做结算
    - AI只接收自然语言描述，不接触标签
    - 这样AI不会根据标签"猜测"应该生成什么，而是根据场景描述自然生成
    """

    TYPE_NAMES: dict[EvidenceType, str] = {
        EvidenceType.PRODUCT_FAKE: "产品造假",
        EvidenceType.FINANCE_FAKE: "财务造假",
        EvidenceType.EMPLOYEE_ABUSE: "员工压榨",
        EvidenceType.SAFETY_HAZARD: "安全隐患",
        EvidenceType.CORRUPTION: "高层腐败",
    }

    TYPE_KEYWORDS: dict[EvidenceType, list[str]] = {
        EvidenceType.PRODUCT_FAKE: [
            "涂改日期",
            "过期销售",
            "以次充好",
            "虚假标签",
            "掺假",
        ],
        EvidenceType.FINANCE_FAKE: [
            "两本账",
            "账外资金",
            "虚报数字",
            "逃税",
            "假发票",
        ],
        EvidenceType.EMPLOYEE_ABUSE: [
            "强制加班",
            "克扣工资",
            "威胁开除",
            "无偿劳动",
            "不合理惩罚",
        ],
        EvidenceType.SAFETY_HAZARD: [
            "有毒泄漏",
            "设备故障",
            "消防隐患",
            "危害健康",
            "无防护措施",
        ],
        EvidenceType.CORRUPTION: [
            "行贿受贿",
            "私吞公款",
            "利益输送",
            "权力寻租",
            "裙带关系",
        ],
    }

    ROOM_NAMES: dict[Room, str] = {
        Room.OFFICE: "主办公区",
        Room.MEETING: "会议室",
        Room.WAREHOUSE: "仓库",
        Room.PANTRY: "茶水间",
        Room.RECEPTION: "接待区",
    }

    @classmethod
    def make_ai_safe_context(cls, payload: dict) -> dict:
        return AISafeContext(payload)

    @classmethod
    def to_ai_prompt_context(
        cls,
        evidence_type: EvidenceType,
        room: Room,
        task_name: str,
        npc_names: list[str] = None,
        npc_personalities: list[str] = None,
    ) -> dict:
        """
        将证据信息转换为AI可用的prompt上下文。

        返回一个字典，包含AI生成对话所需的所有自然语言信息，
        不包含任何标签或系统内部ID。

        参数:
            evidence_type: 证据类型枚举
            room: 房间枚举
            task_name: 任务名称（如"查看罐头库存"）
            npc_names: 在场NPC的显示名列表
            npc_personalities: 在场NPC的性格描述列表

        返回:
            字典，可直接用于构造AI prompt
        """
        type_name = cls.TYPE_NAMES[evidence_type]
        keywords = cls.TYPE_KEYWORDS[evidence_type]
        room_name = cls.ROOM_NAMES[room]

        import random

        selected_keywords = random.sample(
            keywords,
            min(3, len(keywords)),
        )

        context = {
            "is_evidence_event": True,
            "scene_location": room_name,
            "task_description": task_name,
            "evidence_category": type_name,
            "evidence_keywords": selected_keywords,
            "npcs_present": npc_names or [],
            "npcs_personalities": npc_personalities or [],
        }

        return cls.make_ai_safe_context(context)

    @classmethod
    def build_evidence_prompt_block(
        cls,
        evidence_type: EvidenceType,
        room: Room,
        task_name: str,
        npc_names: list[str] = None,
        npc_personalities: list[str] = None,
    ) -> str:
        """
        直接生成可嵌入AI prompt的文本块。

        返回格式化的中文文本，可以直接拼接到prompt中。
        """
        ctx = cls.to_ai_prompt_context(
            evidence_type,
            room,
            task_name,
            npc_names,
            npc_personalities,
        )

        npc_info = ""
        if ctx["npcs_present"]:
            for i, name in enumerate(ctx["npcs_present"]):
                personality = (
                    ctx["npcs_personalities"][i]
                    if i < len(ctx["npcs_personalities"])
                    else "未知"
                )
                npc_info += f"  - {name}（{personality}）\n"

        prompt_block = f"""【场景】{ctx['scene_location']} - {ctx['task_description']}
【在场NPC】
{npc_info if npc_info else '  （无）'}
【证据类型】{ctx['evidence_category']}
【证据关键词】{', '.join(ctx['evidence_keywords'])}

【生成要求】
- 在对话中自然地融入上述关键词相关的内容
- 不要太刻意，让NPC在闲聊/争执/抱怨中"说漏嘴"
- 风格：荒诞、黑色幽默
- 玩家需要通过NPC的话推断出这是证据"""

        return prompt_block

    @classmethod
    def build_normal_event_prompt_block(
        cls,
        room: Room,
        task_name: str,
        npc_names: list[str] = None,
        npc_personalities: list[str] = None,
    ) -> str:
        """
        生成普通事件（非证据）的prompt文本块。
        与证据版本结构一致，但不包含证据相关信息。
        """
        room_name = cls.ROOM_NAMES[room]

        npc_info = ""
        if npc_names:
            for i, name in enumerate(npc_names):
                personality = (
                    npc_personalities[i]
                    if npc_personalities and i < len(npc_personalities)
                    else "未知"
                )
                npc_info += f"  - {name}（{personality}）\n"

        prompt_block = f"""【场景】{room_name} - {task_name}
【在场NPC】
{npc_info if npc_info else '  （无）'}

【生成要求】
- 生成一段符合场景的日常办公互动
- 风格：荒诞、黑色幽默
- 可以包含NPC之间的闲聊、吐槽、摸鱼等内容"""

        return prompt_block
