"""Node 2.5: SDXL Prompt Generator — 将场景扩写翻译为 Danbooru 标签提示词。

专门负责 SDXL 提示词生成，与 Blender 脚本生成完全分离。
输入 JSON: SDXLPromptInput
输出 JSON: SDXLPromptOutput (含 sdxl_prompt, sdxl_negative_prompt)
"""

import json
from state.schema import WorkflowState
from state.models import SDXLPromptInput, SDXLPromptOutput
from utils.helpers import get_llm
from utils.preferences import get_prefs
from config import config


SYSTEM_PROMPT = """你是一个 Danbooru 标签专家，专门为 Animagine XL 4.0 模型生成动漫风格的提示词。

## 你的任务
根据用户的场景描述，生成一组精确的 Danbooru 标签，用于 AI 动漫图片生成。

模型使用 **Animagine XL 4.0**，Danbooru 标签格式。

## 提示词格式模板

```
{人数标签}, {rating}, {发色}, {发型}, {服装}, {姿态}, {表情}, {动作},
{手部姿态标签}, {场景标签}, {环境标签}, {光线标签},
newest, high score, great score, masterpiece, absurdres
```

人数标签规则：
- 单人场景：`1girl` 或 `1boy`
- 双人场景：`2girls` 或 `2boys` 或 `1girl, 1boy`
- 多人场景：`3girls` 等
- **禁止同时出现 `1girl` 和 `2girls`**，根据实际人数选择
- **双人场景禁止使用 `solo` 或 `solo focus` 标签**

**⚠️ 质量标签必须放在末尾**（Animagine XL 4.0 官方：开头放质量标签会压制角色/场景标签触发）。质量标签: `masterpiece, high score, great score, absurdres`（v4.0 用 score 标签替代 best quality）。

## 格式规则
- **Rating 标签（必填）**: `safe`, `sensitive`, `nsfw`, `explicit` 四选一，一般用 `safe`
- **Year 标签**: `newest`（2021-2024 风格），`recent`（2018-2020），`mid`（2015-2017），`early`（2011-2014）
- 角色用 Danbooru 标签: `1girl`, `black hair`, `school uniform`, `sitting`, `half-closed eyes`
- **手部正向标签**（必须包含）: `perfect hands, anatomically correct hands, defined fingers`
- **手部姿态标签**（根据场景选 1-2 个）:
  - `reaching towards viewer` — 手伸向镜头
  - `holding` — 拿着东西
  - `hands on hips` — 手叉腰
  - `peace sign` — 比 V
  - `open hand` / `clenched hand` — 张开/握拳
  - `hands on desk` / `resting head on hand` — 手放桌上/托腮
- 场景用标签: `classroom`, `desk`, `window`, `sunlight`
- 光线: `sunlight`, `soft lighting`, `warm light`（标签，不用自然语言句子）
- **禁止堆光效标签**: `god rays` + `lens flare` + `crepuscular rays` 不要同时出现，最多 1 个
- **眼睛标签（必须检查）**: 如果场景描述涉及人物，必须包含 `open eyes` 或 `closed eyes`
- 总长 40-60 tokens

## 关键原则（优先级从高到低）

### 1. 动作与互动（最重要！决定画面"在发生什么"）
- **人物的动作是画面灵魂**：场景描述中的每个动作细节，都必须转化为精确的动作标签
- **互动对象必须入标签**：人物在看什么/碰什么/靠近什么，那个对象也要出现在标签中
- 常用动作标签: `walking, running, jumping, crouching, sneaking, stalking, tiptoeing, peeking, hiding, reaching, grabbing, holding, pulling, pushing, climbing, leaning, bending, stretching, pouncing, chasing, kneeling, sitting, lying, floating, falling, dangling, leaning forward, leaning back, arching back, looking back, turning around, crouched on all fours, crawling, dangling feet, crossed legs, crossed arms, hands in pockets, arms behind back, arms crossed, hands clasped, finger to lips, shushing, winking, tongue out, sticking tongue out, blowing bubble, blowing bubbles`
- **抑制类表情/动作**: 场景写"憋笑"→ `hand over mouth, giggling, stifled laugh`；"憋泪"→ `tearing up, biting lip`；"憋气"→ `holding breath`
- **互动标签**: 和动物互动→ `playing with cat, reaching towards cat`；和人互动→ `holding hands, whispering`

### 2. 表情 → 情绪标签
- **性格形容词必须转化**：调皮→`mischievous, sly smile, grinning, playful`；悲伤→`sad, tears, downcast eyes`；温柔→`gentle smile, soft look`
- **眼神必须有**: `looking at viewer, looking away, looking up, looking down, glancing back, glancing sideways, staring, eye contact`

### 3. 场景与光线
- 不要编造场景描述中没有的特征
- 不要用自然语言句子，只用 Danbooru 标签

## 正确示例

场景: 女孩悄悄靠近墙根的橘猫，踮着脚尖，准备扑过去，手捂着嘴憋笑
标签:
```
1girl, solo, safe, brown hair, twin braids, denim shorts, white tshirt, standing on tiptoes, sneaking, stalking, reaching towards cat, hand over mouth, giggling, stifled laugh, wide eyes, mischievous, playful, orange cat, crouching, wall, ivy, sunlight, warm light, newest, high score, great score, masterpiece, absurdres
```

## 负向提示词模板

```
lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, fewer digits, cropped, worst quality, low quality, low score, bad score, average score, normal quality, jpeg artifacts, signature, watermark, username, blurry, artist name, low quality face, deformed, bad face, ugly, mutated hands, poorly drawn hands, extra hands, multiple hands, three hands, mangled fingers, fused fingers, interlocked fingers, too many fingers, long fingers, blurry hands, blurry fingers, extra arms, multiple arms, fused arms, missing arms, extra limbs, mutated hands and fingers, incorrect hand anatomy, wrong hand position
```

## 输出格式（严格遵守）

===SDXL_PROMPT===
（Danbooru 标签，40-65 tokens）

===SDXL_NEGATIVE_PROMPT===
（负向提示词）
"""

DEFAULT_NEGATIVE = (
    "lowres, worst quality, low quality, bad anatomy, bad hands, "
    "extra fingers, missing fingers, six fingers, four fingers, "
    "fused fingers, conjoined fingers, mutated hands, "
    "poorly drawn face, poorly drawn eyes, deformed, disfigured, "
    "text, signature, watermark, blurry, jpeg artifacts, ugly, "
    "plastic skin, oversaturated, overexposed, harsh lighting"
)


async def sdxl_prompt_gen(state: WorkflowState) -> dict:
    """Node 2.5: 将场景扩写翻译为 SDXL Danbooru 提示词。"""

    # ===== 1. 读取输入 =====
    expanded_text = state.get_node_output("text_expander").get(
        "expanded_text", state.user_input
    )
    scene_description = state.get_node_output("coder_agent").get(
        "scene_description", ""
    )

    prompt_input = SDXLPromptInput(
        expanded_text=expanded_text,
        scene_description=scene_description,
    )
    state.node_io["sdxl_prompt_gen"] = {
        "input": json.loads(prompt_input.model_dump_json()),
    }

    print(f"\n[NODE IO] sdxl_prompt_gen 输入: {expanded_text[:100]}...")

    # ===== 2. 构建 Prompt =====
    # 主力输入：expanded_text（最完整的场景描述）
    user_prompt = f"场景描述：{expanded_text}"

    # 注入用户偏好
    prefs = get_prefs(config.USER_PREFS_PATH)
    pref_text = prefs.get_injection_text()
    system_prompt = SYSTEM_PROMPT
    if pref_text:
        system_prompt += "\n" + pref_text
        print(f"[Prefs] 偏好已注入 sdxl_prompt_gen ({len(pref_text)} 字符)")

    # ===== 3. 调用 LLM =====
    llm = get_llm(temperature=0.5)
    response = await llm.ainvoke([
        ("system", system_prompt),
        ("user", user_prompt),
    ])
    content = response.content

    # ===== 4. 解析输出 =====
    sdxl_prompt = ""
    sdxl_negative_prompt = DEFAULT_NEGATIVE

    if "===SDXL_PROMPT===" in content:
        prompt_part = content.split("===SDXL_PROMPT===")[1]
        if "===SDXL_NEGATIVE_PROMPT===" in prompt_part:
            parts = prompt_part.split("===SDXL_NEGATIVE_PROMPT===")
            sdxl_prompt = parts[0].strip()
            sdxl_negative_prompt = parts[1].strip()
        else:
            sdxl_prompt = prompt_part.strip()

    # 回退
    if not sdxl_prompt.strip():
        sdxl_prompt = f"masterpiece, best quality, newest, amazing quality, great quality, absurdres, {scene_description or expanded_text[:200]}"
        print("[NODE IO] sdxl_prompt_gen: LLM 未产出，使用回退提示词")

    # ===== 4.5 眼睛兜底检查 =====
    PERSON_TERMS = ['girl', 'boy', 'woman', 'man', 'lady', 'person', 'people',
                    'student', 'teacher', 'child', 'kid', 'farmer', 'warrior',
                    '1girl', '1boy', '1 woman', '1 man']
    EYE_TERMS = ['eye', 'eyes']
    prompt_lower = sdxl_prompt.lower()
    has_person = any(t in prompt_lower for t in PERSON_TERMS)
    has_eye = any(t in prompt_lower for t in EYE_TERMS)
    if has_person and not has_eye:
        sdxl_prompt += ", open eyes"
        sdxl_negative_prompt += ", closed eyes"
        print(f"[NODE IO] sdxl_prompt_gen: 自动追加 open eyes")

    # ===== 5. 构建输出 =====
    prompt_output = SDXLPromptOutput(
        sdxl_prompt=sdxl_prompt,
        sdxl_negative_prompt=sdxl_negative_prompt,
    )
    state.node_io["sdxl_prompt_gen"]["output"] = json.loads(prompt_output.model_dump_json())

    print(f"[NODE IO] sdxl_prompt_gen 输出: prompt_len={len(sdxl_prompt)}, neg_len={len(sdxl_negative_prompt)}")
    print(f"[NODE IO] sdxl_prompt_gen prompt: {sdxl_prompt[:150]}...")

    return {"node_io": state.node_io}
