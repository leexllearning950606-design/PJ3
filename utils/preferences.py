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
        """自动将标签分配到偏好分类中。_skip 表示不持久化。"""
        result = {}
        for t in tags:
            t = t.strip().rstrip(",")
            cat = self.TAG_CATEGORIES.get(t, "")
            if cat == "":
                continue  # 未知标签跳过
            if cat == "_skip":
                continue  # 不持久化的内容标签跳过
            result.setdefault(cat, []).append(t)
        return result

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

    # ---- 偏好注入 ----

    def get_injection_text(self) -> str:
        """生成注入到 coder_agent 系统提示词中的偏好文本。"""
        parts = []
        liked_all = []

        for cat in self.PERSIST_CATEGORIES:
            tags = self.data["liked_tags"].get(cat, [])
            if tags:
                liked_all.extend(tags)
                parts.append(f"- 喜欢的{self._cat_name(cat)}: {', '.join(tags[:6])}")

        if self.data["disliked_tags"]:
            parts.append(f"- 不喜欢的标签: {', '.join(self.data['disliked_tags'][:8])}")

        if not parts:
            return ""

        header = "\n## 用户审美偏好（自动注入）\n"
        footer = (
            f"\n在生成提示词时，请尽量包含用户喜欢的标签。"
            f"正负向提示词中加入: {', '.join(liked_all[:15])}"
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

    def summary(self) -> str:
        """打印偏好摘要。"""
        lines = ["用户审美偏好:"]
        for cat in self.PERSIST_CATEGORIES:
            tags = self.data["liked_tags"].get(cat, [])
            if tags:
                lines.append(f"  {self._cat_name(cat)}: {', '.join(tags[:5])}")
        if self.data["disliked_tags"]:
            lines.append(f"  不喜欢: {', '.join(self.data['disliked_tags'][:5])}")
        return "\n".join(lines) if len(lines) > 1 else "暂无偏好记录"


# 全局单例
_prefs_instance: Optional[PreferenceManager] = None


def get_prefs(path: str = "./user_prefs.json") -> PreferenceManager:
    global _prefs_instance
    if _prefs_instance is None or _prefs_instance.path != path:
        _prefs_instance = PreferenceManager(path)
    return _prefs_instance
