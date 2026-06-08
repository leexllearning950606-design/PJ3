"""用户偏好管理器 — 记住用户的审美偏好（色调/光线/风格/氛围/构图/质量）。

原则：记住"怎么画"（审美），不记住"画什么"（内容）。
"""

import json
import os
from datetime import datetime
from typing import Optional


class PreferenceManager:
    """管理用户审美偏好。

    6 个持久化维度 (都是"怎么画"，不涉及"画什么"):
      color_tone  — 色调倾向 (暖色/冷色/高饱和/淡彩)
      lighting   — 光线风格 (柔光/逆光/金色光/阴天)
      style      — 艺术风格 (赛璐珞/水彩/厚涂/线稿)
      mood       — 氛围情绪 (温馨/忧伤/宁静/活力)
      composition — 构图倾向 (特写/中景/远景/留白)
      quality    — 质量倾向 (丰富细节/简洁构图)

    不持久化（每次 prompt 指定）:
      scene/character/pose — 这些都是"画什么"
    """

    # ---- 持久化维度 ----
    PERSIST_CATEGORIES = {
        "color_tone", "lighting", "style", "mood", "composition", "quality",
    }

    def __init__(self, prefs_path: str = "./user_prefs.json"):
        self.path = prefs_path
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 迁移旧版本数据
                    if "liked_tags" in data:
                        for old_cat in list(data["liked_tags"].keys()):
                            if old_cat not in self.PERSIST_CATEGORIES and old_cat not in {"scene", "character", "pose", "overall"}:
                                pass  # 保留未知分类
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return self._default()

    def reload(self):
        """从磁盘重新加载（用于多进程同步，如 CLI 写入后 Web 读取）。"""
        self.data = self._load()

    def _default(self) -> dict:
        return {
            "version": 2,
            "liked_tags": {
                "color_tone": [],
                "lighting": [],
                "style": [],
                "mood": [],
                "composition": [],
                "quality": [],
            },
            "disliked_tags": [],
            "history": [],
            "created": datetime.now().isoformat(),
        }

    def save(self):
        self.data["updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---- 记录偏好 ----

    def add_liked(self, tags: list, category: str):
        """添加喜欢的标签到指定分类。"""
        if category not in self.PERSIST_CATEGORIES:
            return  # 不持久化的分类忽略
        cat = self.data["liked_tags"].setdefault(category, [])
        for t in tags:
            t = t.strip().rstrip(",")
            if t and t not in cat:
                cat.append(t)
                if t in self.data["disliked_tags"]:
                    self.data["disliked_tags"].remove(t)

    def add_disliked(self, tags: list):
        """添加不喜欢的标签。"""
        for t in tags:
            t = t.strip().rstrip(",")
            if t and t not in self.data["disliked_tags"]:
                self.data["disliked_tags"].append(t)
                for cat in self.data["liked_tags"].values():
                    if t in cat:
                        cat.remove(t)

    def add_history(self, entry: dict):
        """记录一次生成历史（最多 50 条）。"""
        entry["timestamp"] = datetime.now().isoformat()
        self.data["history"].append(entry)
        if len(self.data["history"]) > 50:
            self.data["history"] = self.data["history"][-50:]

    # ---- 标签 → 分类映射 ----

    TAG_CATEGORIES: dict = {
        # ── 色调 ──
        "warm atmosphere": "color_tone", "warm color": "color_tone",
        "cool atmosphere": "color_tone", "cool color": "color_tone",
        "muted colors": "color_tone", "vivid colors": "color_tone",
        "pastel colors": "color_tone", "monochrome": "color_tone",
        "sepia": "color_tone", "high saturation": "color_tone",
        "low saturation": "color_tone", "desaturated": "color_tone",
        "warm tone": "color_tone", "cool tone": "color_tone",
        # ── 光线 ──
        "soft lighting": "lighting", "harsh lighting": "lighting",
        "sunlight": "lighting", "backlighting": "lighting", "backlight": "lighting",
        "golden hour": "lighting", "sunset": "lighting", "dusk": "lighting",
        "night": "lighting", "moonlight": "lighting", "morning": "lighting",
        "god rays": "lighting", "lens flare": "lighting", "crepuscular rays": "lighting",
        "cinematic lighting": "lighting", "dramatic lighting": "lighting",
        "warm light": "lighting", "cold light": "lighting",
        "overcast": "lighting", "cloudy": "lighting", "rainy": "lighting",
        "dappled light": "lighting", "rim lighting": "lighting",
        "dim lighting": "lighting", "bright": "lighting",
        # ── 风格 ──
        "watercolor": "style", "cel shading": "style", "line art": "style",
        "flat color": "style", "painterly": "style", "sketch": "style",
        "oil painting": "style", "ink wash": "style", "gouache": "style",
        "thick outlines": "style", "no lines": "style",
        "anime style": "style", "semi-realistic": "style", "realistic": "style",
        "minimalist": "style", "detailed": "style",
        # ── 氛围 ──
        "peaceful": "mood", "calm": "mood", "serene": "mood",
        "sad": "mood", "melancholy": "mood", "lonely": "mood",
        "energetic": "mood", "dynamic": "mood", "tense": "mood",
        "daydreaming": "mood", "nostalgic": "mood", "romantic": "mood",
        "mysterious": "mood", "gloomy": "mood", "dark": "mood",
        "cheerful": "mood", "cozy": "mood", "ethereal": "mood",
        "bittersweet": "mood", "hopeful": "mood",
        # ── 构图 ──
        "close-up": "composition", "medium shot": "composition",
        "wide shot": "composition", "full body": "composition",
        "from above": "composition", "from below": "composition",
        "from side": "composition", "facing camera": "composition",
        "looking away": "composition", "looking at viewer": "composition",
        "centered": "composition", "off-center": "composition",
        "rule of thirds": "composition", "symmetrical": "composition",
        "negative space": "composition", "depth of field": "composition",
        "blurry background": "composition", "bokeh": "composition",
        "portrait": "composition", "landscape": "composition",
        # ── 质量 ──
        "highly detailed": "quality", "intricate details": "quality",
        "simple background": "quality", "detailed background": "quality",
        "4k": "quality", "8k": "quality", "hd": "quality",
        "sharp focus": "quality", "soft focus": "quality",
        "clean lines": "quality", "rough": "quality",
        # ── 不持久化（scene/character/pose → 忽略）──
        "classroom": "_skip", "park": "_skip", "cafe": "_skip", "street": "_skip",
        "beach": "_skip", "school": "_skip", "room": "_skip", "outdoor": "_skip",
        "indoor": "_skip", "city": "_skip", "forest": "_skip", "garden": "_skip",
        "black hair": "_skip", "long hair": "_skip", "short hair": "_skip",
        "school uniform": "_skip", "glasses": "_skip", "ponytail": "_skip",
        "sitting": "_skip", "standing": "_skip", "walking": "_skip", "running": "_skip",
    }

    def auto_categorize(self, tags: list) -> dict:
        """自动将标签分配到偏好分类中。_skip 表示不持久化。

        所有标签通过 EN→CN 反向映射转为中文存储，与 LLM 路径保持一致。
        """
        result = {}
        for t in tags:
            t = t.strip().rstrip(",")
            cat = self.TAG_CATEGORIES.get(t, "")
            if cat == "":
                continue  # 未知标签跳过
            if cat == "_skip":
                continue  # 不持久化的内容标签跳过
            cn_tag = self.EN_TO_CN.get(t, t)  # EN→CN 转换，查不到则保留原样
            result.setdefault(cat, []).append(cn_tag)
        return result

    @property
    def EN_TO_CN(self) -> dict:
        """EN→CN 反向映射，从 CN_TO_EN 自动构建 + 补充条目。"""
        if not hasattr(self, "_en_to_cn_cache"):
            en_to_cn = {v: k for k, v in self.CN_TO_EN.items()}
            # 补充 TAG_CATEGORIES 中存在但 CN_TO_EN 值中缺失的英文标签
            extras = {
                "backlight": "逆光",
                "crepuscular rays": "丁达尔光",
            }
            for en_tag, cn_tag in extras.items():
                if en_tag not in en_to_cn:
                    en_to_cn[en_tag] = cn_tag
            self._en_to_cn_cache = en_to_cn
        return self._en_to_cn_cache

    def learn_from_prompt(self, prompt: str, positive: bool = True):
        """从最终接受的 prompt 中学习审美偏好。

        自动分类 → 只保留 6 个审美维度 → 持久化。
        """
        tags = [t.strip() for t in prompt.split(",")]
        skip = {
            "masterpiece", "best quality", "absurdres", "newest", "recent",
            "high score", "great score", "good score", "average score",
            "safe", "sensitive", "1girl", "1boy", "solo",
            "perfect hands", "anatomically correct hands", "defined fingers",
        }
        filtered = [t for t in tags if t.lower() not in skip]

        if positive:
            categorized = self.auto_categorize(filtered)
            for cat, cat_tags in categorized.items():
                self.add_liked(cat_tags, cat)
        else:
            self.add_disliked(filtered)

    async def learn_from_prompt_async(self, prompt: str):
        """用 LLM 分析 prompt，提取所有 6 维审美偏好。

        相比硬编码 TAG_CATEGORIES，LLM 可以识别更多样化的审美标签。
        """
        from utils.helpers import get_llm

        system = """你是 Danbooru 标签分析专家。从以下提示词中提取用户的审美偏好，按 6 个维度分类。

每个维度的标签请用**简洁中文**输出（2-4 个字），例如：

- color_tone (色调): 暖色调, 冷色调, 低饱和, 鲜艳色彩, 粉彩色, 单色, 复古棕 等
- lighting (光线): 柔光, 强光, 阳光, 逆光, 日落暖光, 夜晚, 月光, 电影感布光, 丁达尔光, 轮廓光 等
- style (风格): 水彩, 赛璐珞, 线稿, 平涂, 油画风, 素描, 动漫风, 半写实, 写实 等
- mood (氛围): 平静, 悲伤, 忧郁, 活力, 神秘, 浪漫, 怀旧, 温馨, 欢快 等
- composition (构图): 特写, 中景, 远景, 俯视, 仰视, 居中, 三分构图, 景深, 光斑虚化 等
- quality (质量): 高细节, 精致细节, 简单背景, 详细背景, 锐利对焦, 柔焦, 干净线条 等

规则：
1. 只提取审美/风格标签，不提取角色/场景/内容（如 1girl, black hair, classroom 等）
2. 如果某个维度没有对应标签，返回空数组
3. cn 用简洁中文，参考上面的示例
4. 只返回 JSON，不要任何解释"""

        try:
            llm = get_llm(temperature=0.1)
            response = await llm.ainvoke([
                ("system", system),
                ("user", f"提示词: {prompt}\n\n请分析并返回 JSON:"),
            ])
            import json
            text = response.content.strip()
            # 清理可能的 markdown 代码块
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
            result = json.loads(text)
            for cat, tags in result.items():
                if cat in self.PERSIST_CATEGORIES and isinstance(tags, list):
                    self.add_liked(tags, cat)
            print(f"  [Prefs] LLM 分析偏好: {json.dumps(result, ensure_ascii=False)}")
        except Exception as e:
            print(f"  [Prefs] LLM 分析失败，回退到硬编码分类: {e}")
            self.learn_from_prompt(prompt, positive=True)

    # ---- CN→EN 反向映射（注入 SDXL 提示词时使用）----

    CN_TO_EN = {
        # 色调
        "暖色调": "warm atmosphere", "暖色": "warm color", "暖调": "warm tone",
        "冷色调": "cool atmosphere", "冷色": "cool color", "冷调": "cool tone",
        "低饱和": "low saturation", "低饱和色": "muted colors", "鲜艳色彩": "vivid colors",
        "粉彩色": "pastel colors", "单色": "monochrome", "复古棕": "sepia",
        "高饱和": "high saturation", "去饱和": "desaturated",
        # 光线
        "柔光": "soft lighting", "强光": "harsh lighting", "阳光": "sunlight",
        "逆光": "backlighting", "日落暖光": "golden hour", "日落": "sunset",
        "黄昏": "dusk", "夜晚": "night", "月光": "moonlight", "清晨": "morning",
        "丁达尔光": "god rays", "镜头光晕": "lens flare", "体积光": "volumetric lighting",
        "电影感布光": "cinematic lighting", "戏剧性光影": "dramatic lighting",
        "暖光": "warm light", "冷光": "cold light", "阴天": "overcast",
        "多云": "cloudy", "雨天": "rainy", "斑驳光": "dappled light",
        "轮廓光": "rim lighting", "暗光": "dim lighting", "明亮": "bright",
        "斑驳阳光": "dappled sunlight", "光束": "sunbeam", "长影": "long shadows",
        # 风格
        "水彩": "watercolor", "赛璐珞": "cel shading", "线稿": "line art",
        "平涂": "flat color", "油画风": "painterly", "素描": "sketch",
        "油画": "oil painting", "水墨": "ink wash", "水粉": "gouache",
        "粗线条": "thick outlines", "无线条": "no lines", "动漫风": "anime style",
        "半写实": "semi-realistic", "写实": "realistic", "极简": "minimalist",
        "细腻": "detailed",
        # 氛围
        "平静": "peaceful", "安宁": "calm", "静谧": "serene", "悲伤": "sad",
        "忧郁": "melancholy", "孤独": "lonely", "活力": "energetic", "动感": "dynamic",
        "紧张": "tense", "出神": "daydreaming", "怀旧": "nostalgic", "浪漫": "romantic",
        "神秘": "mysterious", "阴郁": "gloomy", "黑暗": "dark", "欢快": "cheerful",
        "温馨": "cozy", "空灵": "ethereal", "苦涩": "bittersweet", "希望": "hopeful",
        "温馨氛围": "cozy atmosphere", "坚定": "determined",
        # 构图
        "特写": "close-up", "中景": "medium shot", "远景": "wide shot",
        "全身": "full body", "俯视": "from above", "仰视": "from below",
        "侧面": "from side", "正对镜头": "facing camera", "看向别处": "looking away",
        "看向观众": "looking at viewer", "居中": "centered", "偏置": "off-center",
        "三分构图": "rule of thirds", "对称": "symmetrical", "留白": "negative space",
        "景深": "depth of field", "虚化背景": "blurry background", "光斑虚化": "bokeh",
        "竖幅": "portrait", "横幅": "landscape",
        # 质量
        "高细节": "highly detailed", "精致细节": "intricate details",
        "简单背景": "simple background", "详细背景": "detailed background",
        "4K画质": "4k", "8K画质": "8k", "高清": "hd",
        "锐利对焦": "sharp focus", "柔焦": "soft focus", "干净线条": "clean lines",
        "粗犷": "rough",
        # 动作
        "奔跑": "running", "行走": "walking", "跳跃": "jumping", "追逐": "chasing",
        "悄悄靠近": "sneaking", "潜行": "stalking", "踮脚": "tiptoeing",
        "踮脚尖": "standing on tiptoes", "扑": "pouncing", "蹲伏": "crouching",
        "跪坐": "kneeling", "坐着": "sitting", "躺着": "lying", "爬行": "crawling",
        "攀爬": "climbing", "前倾": "leaning forward", "伸手": "reaching hand",
        "伸手向镜头": "reaching towards viewer", "张开双臂": "arms outstretched",
        "拿着": "holding", "抓取": "grabbing", "手插口袋": "hands in pockets",
        "手背后": "arms behind back", "抱臂": "crossed arms", "翘腿": "crossed legs",
        "双手交握": "hands clasped",
        # 表情
        "调皮": "mischievous", "顽皮": "playful", "坏笑": "sly smile",
        "咧嘴笑": "grinning", "咯咯笑": "giggling", "憋笑": "stifled laugh",
        "捂嘴": "hand over mouth", "嘘声手势": "finger to lips", "嘘": "shushing",
        "眨眼": "winking", "吐舌": "tongue out", "吹泡泡": "blowing bubble",
        "脸红": "flushed cheeks", "圆眼": "wide eyes", "睁眼": "open eyes",
        "闭眼": "closed eyes", "凝视": "staring", "回眸": "glancing back",
        "侧目": "glancing sideways", "对视": "eye contact",
    }

    # ---- 偏好注入 ----

    def get_injection_text(self) -> str:
        """生成注入到 SDXL 提示词中的偏好文本（自动 CN→EN 转换）。"""
        parts = []
        liked_en = []

        for cat in self.PERSIST_CATEGORIES:
            tags = self.data["liked_tags"].get(cat, [])
            if tags:
                # 转换为英文（SDXL 只认英文标签）
                en_tags = [self.CN_TO_EN.get(t, t) for t in tags]
                liked_en.extend(en_tags)
                parts.append(f"- 喜欢的{self._cat_name(cat)}: {', '.join(tags[:6])}")

        disliked_tags = self.data["disliked_tags"]
        if disliked_tags:
            en_disliked = [self.CN_TO_EN.get(t, t) for t in disliked_tags]
            parts.append(f"- 不喜欢的标签: {', '.join(disliked_tags[:8])}")

        if not parts:
            return ""

        header = "\n## 用户审美偏好（请根据场景选择性使用）\n"
        footer = (
            f"\n⚠️ 重要：以上是用户的审美偏好，但**不是每个标签都适合当前场景**。"
            f"请根据当前场景的实际情况，**只选用合适的标签**，不合适的标签不要强行加入。"
            f"例如：用户喜欢『温馨』，但当前场景是『深夜街角』→ 不要加入 cozy。"
            f"用户喜欢『日落暖光』，但当前场景是『阴雨天』→ 不要加入 golden hour。"
        )
        return header + "\n".join(parts) + footer

    @staticmethod
    def _cat_name(cat: str) -> str:
        names = {
            "color_tone": "色调", "lighting": "光线", "style": "风格",
            "mood": "氛围", "composition": "构图", "quality": "质量",
        }
        return names.get(cat, cat)

    # ---- 工具 ----

# 全局单例
_prefs_instance: Optional[PreferenceManager] = None


def get_prefs(path: str = "./user_prefs.json") -> PreferenceManager:
    global _prefs_instance
    if _prefs_instance is None or _prefs_instance.path != path:
        _prefs_instance = PreferenceManager(path)
    return _prefs_instance
