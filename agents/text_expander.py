"""Node 1: Text Expander — 将用户简短输入"脑补"扩写成细节丰富的长文本。

输入 JSON: TextExpanderInput
输出 JSON: TextExpanderOutput (含 expanded_text)
"""

import json
from state.schema import WorkflowState
from state.models import TextExpanderInput, TextExpanderOutput
from utils.helpers import get_llm


SYSTEM_PROMPT = """你是一个专业的影视场景概念设计师。用户会给出一句简单的话，你需要把它"脑补"扩写成一段细节丰富的场景描述。

## 你的任务
把用户的一句话扩写成 200~400 字的中文场景描述。像一个电影美术指导那样，为后续的 3D 建模和 AI 绘画提供充足的视觉信息。

## 必须覆盖的要素
1. **环境与空间**：场景发生在哪里？空间有多大？有什么建筑/自然结构？地面、墙壁、天花板的材质和状态？
2. **人物与道具**：场景中有谁？穿什么颜色/款式的衣服？什么姿势/动作？有什么关键道具？
3. **光线与色调**：光源在哪里？什么类型（自然光/灯光/火光）？色温（暖黄/冷蓝/中性）？整体画面偏亮还是偏暗？
4. **材质与纹理**：场景中主要物体是什么材质（木头/石头/金属/布料）？表面是粗糙还是光滑？新旧程度？
5. **氛围与情绪**：场景传达什么情绪（紧张/宁静/悲伤/庄严/神秘）？有什么强化氛围的元素（雾/雨/灰尘/烛光）？
6. **构图暗示**：主要的视觉焦点在哪里？画面是纵深的还是有压迫感的？

## 写作要求
- 用具体、可视化的语言，避免抽象形容词
- 写出颜色、材质、空间关系的具体描述
- 不要说"画面很美"，要写出"为什么美"
- 直接输出扩写文本，不要加前缀标签或解释

## 示例

用户输入：一个武士在雨夜走进废弃寺庙

扩写输出：
这是一座废弃已久的日本山间寺庙，本堂内部约 8 米宽、6 米深。腐朽的木地板多处塌陷，露出下方黑色的泥土。右侧一扇破旧的纸拉门半挂在轨道上，被风吹得轻轻摇晃。屋顶有两处瓦片脱落，雨水顺着破洞滴落在青苔斑驳的榻榻米上，溅起细小的水花。

一名身着深靛蓝色武士铠甲的中年男子站在门口，雨水从他的头盔边缘滴落。他左手按在腰间的太刀鞘上，右手尚未拔刀但五指微张，身体重心略微下沉呈备战姿态。他的披风已被雨水浸透，呈现出近乎黑色的深蓝。

寺庙深处，三支残烛在倒塌的佛坛前摇曳。暖黄色的烛光勉强照亮了周围的区域，在斑驳的墙壁上投射出晃动的阴影。一尊半毁的木雕观音像倒在佛坛右侧，表面布满刀痕。空气中弥漫着湿木头、霉菌和蜡烛燃烧的混合气味，整个场景笼罩在一种紧张而压抑的寂静中。"""


async def text_expander(state: WorkflowState) -> dict:
    """Node 1: 将用户简短输入扩写为详细场景描述。"""

    # ===== 1. 构建输入 =====
    expander_input = TextExpanderInput(user_input=state.user_input)
    state.node_io["text_expander"] = {
        "input": json.loads(expander_input.model_dump_json()),
    }

    print(f"\n[NODE IO] text_expander 输入: {state.user_input[:100]}")

    # ===== 2. 调用 LLM =====
    llm = get_llm(temperature=0.7)
    response = await llm.ainvoke([
        ("system", SYSTEM_PROMPT),
        ("user", f"请扩写以下场景：{state.user_input}"),
    ])
    expanded_text = response.content.strip()

    # ===== 3. 构建输出 =====
    expander_output = TextExpanderOutput(expanded_text=expanded_text)
    state.node_io["text_expander"]["output"] = json.loads(expander_output.model_dump_json())

    print(f"[NODE IO] text_expander 输出: {len(expanded_text)} 字符")

    return {"node_io": state.node_io}
