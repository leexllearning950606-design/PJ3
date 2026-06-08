"""Danbooru 提示词改写 — 通过 LLM 按分类修改标签。

提供:
  - _rewrite_prompt(): LLM 改写提示词
  - _merge_missing_tags(): 后处理，强制合并丢失的场景/环境标签
  - public_rewrite_prompt(): 供 server/worker.py 调用的公开包装
"""

from utils.helpers import get_llm


async def _rewrite_prompt(
    current_prompt: str,
    user_request: str,
    category: str,
    pref_context: str = "",
) -> str:
    """调用 LLM 根据用户要求改写 Danbooru 提示词。

    改写后强制合并场景标签，防止 LLM 遗漏导致背景泛白。
    """

    PRESERVE_RULES = {
        "光线": "只修改光线/时间/色调相关标签。场景、环境、背景、角色、姿态、服装、质量标签全部保持原样不动",
        "角色": "只修改角色外观标签（发型、服装、配饰、表情）。场景、环境、背景、光线、姿态、质量标签全部保持原样不动",
        "姿态": "只修改姿态/动作标签。角色外观、场景、环境、背景、光线、服装、质量标签全部保持原样不动",
        "风格": "只修改风格/渲染方式标签。角色、场景、环境、背景、光线、姿态、质量标签全部保持原样不动",
    }
    preserve_rule = PRESERVE_RULES.get(category, "只修改与当前分类相关的标签，场景、环境、背景、角色、光线、质量标签全部保持原样不动")

    system = f"""你是 Danbooru 标签专家。用户想修改图片的{category}。

当前提示词: {current_prompt}
"""
    if pref_context:
        system += f"\n## 用户审美偏好\n{pref_context}\n"
    system += f"""
规则：
1. {preserve_rule}
2. 保持标签顺序：角色→姿态→手部→场景→光线→质量标签（末尾）
3. 手部标签（perfect hands, anatomically correct hands, defined fingers）必须保留
4. 质量标签（newest, high score, great score, masterpiece, best quality, absurdres）保持在末尾不动
5. 场景/环境/背景标签必须完整保留
6. 只输出修改后的完整 Danbooru 标签，用逗号分隔，不要任何解释
7. rating 标签（safe/sensitive）保留不动"""

    user = user_request

    try:
        import time as _time
        _t0 = _time.time()
        print(f"    [DEBUG] 提示词改写 LLM 调用中... category={category}")
        llm = get_llm(temperature=0.3)
        response = await llm.ainvoke([
            ("system", system),
            ("user", user),
        ])
        new_prompt = response.content.strip()
        new_prompt = new_prompt.strip('"').strip("'")
        print(f"    [DEBUG] 提示词改写 LLM 完成 ({_time.time() - _t0:.1f}s)")

        if "1girl" not in new_prompt and "1boy" not in new_prompt:
            print(f"    [DEBUG] 提示词改写 回退: 缺少 1girl/1boy")
            return current_prompt

        # ---- 后处理: 强制合并原提示词中的场景/环境标签 ----
        new_prompt = _merge_missing_tags(current_prompt, new_prompt)
        return new_prompt

    except Exception as e:
        print(f"    [WARN] 提示词改写异常: {e}")
        return current_prompt


def _merge_missing_tags(original: str, rewritten: str) -> str:
    """把原提示词中可能被 LLM 遗漏的场景/环境/背景标签合并回新提示词。"""
    orig_tags = [t.strip() for t in original.split(",")]
    new_tags = [t.strip() for t in rewritten.split(",")]
    new_set = set(t.lower() for t in new_tags)

    # 这些类型的标签绝对不能从原提示词丢失
    QUALITY_TAGS = {
        "masterpiece", "best quality", "absurdres", "newest", "high score",
        "great score", "good score", "normal quality",
    }
    HAND_TAGS = {
        "perfect hands", "anatomically correct hands", "defined fingers",
    }
    RATING_TAGS = {"safe", "sensitive", "nsfw", "explicit"}

    # 已知的场景/环境关键词（常见 Danbooru 场景标签）
    SCENE_KEYWORDS = {
        "classroom", "cafe", "café", "park", "street", "beach", "school",
        "room", "outdoor", "outdoors", "indoor", "indoors", "city", "cityscape",
        "forest", "garden", "desk", "window", "tree", "trees", "sky", "cloud",
        "clouds", "building", "wall", "floor", "door", "table", "chair", "bed",
        "shelf", "river", "sea", "ocean", "mountain", "field", "meadow",
        "grass", "flower", "flowers", "road", "path", "sidewalk", "bridge",
        "fence", "roof", "stairs", "bookshelf", "blackboard", "chalkboard",
        "sofa", "couch", "curtain", "carpet", "rug", "mirror", "painting",
        "picture frame", "lamp", "balcony", "rooftop", "alley", "corridor",
        "hallway", "kitchen", "bathroom", "living room", "bedroom", "library",
        "restaurant", "shop", "store", "market", "lake", "pond", "pool",
        "fountain", "stream", "waterfall", "rain", "snow", "fog", "mist",
        "wooden", "brick", "concrete", "glass", "metal", "stone",
        "sunlight", "moonlight", "sunset", "sunrise", "dusk", "dawn", "night",
        "day", "afternoon", "morning", "evening", "twilight",
        "landscape", "scenery", "horizon", "skyline", "nature",
    }

    missing = []
    for tag in orig_tags:
        tl = tag.lower()
        # 永远保留: 质量标签、手部标签、rating
        if tl in QUALITY_TAGS or tl in HAND_TAGS or tl in RATING_TAGS:
            if tl not in new_set:
                missing.append(tag)
            continue
        # 场景标签: 含场景关键词 或 非角色/光线/风格标签的未知标签
        is_scene = any(kw in tl for kw in SCENE_KEYWORDS)
        if is_scene and tl not in new_set:
            missing.append(tag)

    if not missing:
        return rewritten

    # 把缺失标签插入到质量标签之前
    quality_pos = len(new_tags)
    for i, t in enumerate(new_tags):
        if t.lower().strip() in QUALITY_TAGS:
            quality_pos = i
            break

    merged = new_tags[:quality_pos] + missing + new_tags[quality_pos:]
    result = ", ".join(merged)
    print(f"    [Merge] 补充场景标签: {missing}")
    return result


async def public_rewrite_prompt(
    current_prompt: str,
    user_request: str,
    category: str,
    pref_context: str = "",
) -> str:
    """公开包装：调用 _rewrite_prompt。"""
    return await _rewrite_prompt(current_prompt, user_request, category, pref_context)
