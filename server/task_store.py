"""历史任务存储 — JSON 文件读写 + 缩略图生成。"""
import json
import os
import uuid
from datetime import datetime
from typing import Optional

HISTORY_PATH = "./output/history.json"
THUMB_DIR = "./output/thumbnails"
MAX_HISTORY = 200

# 活跃任务（内存中，未确认不写入历史）
_active_tasks: dict[str, "TaskRecord"] = {}


class TaskRecord:
    """历史任务记录。"""
    def __init__(self, **kwargs):
        self.id: str = kwargs.get("id", str(uuid.uuid4())[:8])
        self.user_input: str = kwargs.get("user_input", "")
        self.status: str = kwargs.get("status", "pending")
        self.created_at: str = kwargs.get("created_at", datetime.now().isoformat())

        # 各节点输出
        self.expanded_text: Optional[str] = kwargs.get("expanded_text")
        self.sdxl_prompt: Optional[str] = kwargs.get("sdxl_prompt")
        self.sdxl_negative_prompt: Optional[str] = kwargs.get("sdxl_negative_prompt")
        self.blender_script: Optional[str] = kwargs.get("blender_script")
        self.depth_image_url: Optional[str] = kwargs.get("depth_image_url")
        self.frame_image_url: Optional[str] = kwargs.get("frame_image_url")
        self.final_image_url: Optional[str] = kwargs.get("final_image_url")
        self.grid_image_url: Optional[str] = kwargs.get("grid_image_url")
        self.selected_seed: Optional[int] = kwargs.get("selected_seed")

        # 交互历史
        self.interactions: list = kwargs.get("interactions", [])
        self.version: int = kwargs.get("version", 1)

        # 参数
        self.params: dict = kwargs.get("params", {})

        self.error_message: Optional[str] = kwargs.get("error_message")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "user_input": self.user_input,
            "status": self.status, "created_at": self.created_at,
            "expanded_text": self.expanded_text,
            "sdxl_prompt": self.sdxl_prompt,
            "sdxl_negative_prompt": self.sdxl_negative_prompt,
            "blender_script": self.blender_script,
            "depth_image_url": self.depth_image_url,
            "frame_image_url": self.frame_image_url,
            "final_image_url": self.final_image_url,
            "grid_image_url": self.grid_image_url,
            "selected_seed": self.selected_seed,
            "interactions": self.interactions,
            "version": self.version,
            "params": self.params,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskRecord":
        return cls(**d)


def load_history() -> list[TaskRecord]:
    """读取所有历史记录。"""
    if not os.path.isfile(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [TaskRecord.from_dict(item) for item in data]
    except (json.JSONDecodeError, IOError):
        return []


def save_history(tasks: list[TaskRecord]):
    """保存历史记录，保留最近 MAX_HISTORY 条。"""
    os.makedirs(os.path.dirname(HISTORY_PATH) or ".", exist_ok=True)
    tasks = tasks[-MAX_HISTORY:]
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump([t.to_dict() for t in tasks], f, ensure_ascii=False, indent=2)


def add_task_in_memory(record: "TaskRecord"):
    """添加任务到内存（不写入历史）。"""
    _active_tasks[record.id] = record


def update_task(task_id: str, **kwargs):
    """更新任务字段（先查内存，再查历史）。"""
    t = _active_tasks.get(task_id)
    if t:
        for k, v in kwargs.items():
            setattr(t, k, v)
        return

    # fallback: 查历史并更新
    tasks = load_history()
    for t in tasks:
        if t.id == task_id:
            for k, v in kwargs.items():
                setattr(t, k, v)
            break
    save_history(tasks)


def get_task(task_id: str) -> Optional["TaskRecord"]:
    """获取单个任务（先查内存，再查历史）。"""
    if task_id in _active_tasks:
        return _active_tasks[task_id]
    for t in load_history():
        if t.id == task_id:
            return t
    return None


def add_task(record: "TaskRecord"):
    """直接追加到历史文件。"""
    tasks = load_history()
    tasks.append(record)
    save_history(tasks)


def finalize_task(task_id: str):
    """将任务从内存移到历史（用户确认"满意保存"时调用）。"""
    t = _active_tasks.pop(task_id, None)
    if t:
        t.status = "done"
        add_task(t)


def delete_task(task_id: str) -> bool:
    """删除单条历史记录（同时清理 history.json 和 user_prefs.json），返回是否成功。"""
    deleted = False

    # 1. 删除 web 历史 (history.json)
    tasks = load_history()
    for t in tasks:
        if t.id == task_id:
            tasks.remove(t)
            save_history(tasks)
            deleted = True
            break

    # 2. 删除 CLI 历史 (user_prefs.json)
    from config import config
    prefs_path = config.USER_PREFS_PATH
    if os.path.isfile(prefs_path):
        try:
            with open(prefs_path, "r", encoding="utf-8") as f:
                prefs_data = json.load(f)
            old_len = len(prefs_data.get("history", []))
            prefs_data["history"] = [
                h for h in prefs_data.get("history", [])
                if task_id not in (h.get("image", "") or "")
            ]
            if len(prefs_data["history"]) < old_len:
                with open(prefs_path, "w", encoding="utf-8") as f:
                    json.dump(prefs_data, f, ensure_ascii=False, indent=2)
                deleted = True
        except (json.JSONDecodeError, IOError):
            pass

    return deleted


def search_tasks(query: str = "", page: int = 1, limit: int = 20, merge_cli: bool = False) -> tuple[list[TaskRecord], int]:
    """搜索历史 (按关键词匹配 user_input 或 sdxl_prompt)，返回 (结果, 总数)。

    当 merge_cli=True 时，同时合并 CLI (user_prefs.json) 的历史记录。"""
    tasks = load_history()

    if merge_cli:
        tasks = _merge_cli_history(tasks)

    if query:
        q = query.lower()
        tasks = [t for t in tasks if
                 (t.user_input and q in t.user_input.lower()) or
                 (t.sdxl_prompt and q in t.sdxl_prompt.lower())]
    total = len(tasks)
    start = (page - 1) * limit
    end = start + limit
    return tasks[::-1][start:end], total  # 最新在前


def _merge_cli_history(existing: list[TaskRecord]) -> list[TaskRecord]:
    """将 CLI 的 user_prefs.json history 合并到 TaskRecord 列表中。"""
    from config import config

    prefs_path = config.USER_PREFS_PATH
    if not os.path.isfile(prefs_path):
        return existing

    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs_data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return existing

    cli_history = prefs_data.get("history", [])
    if not cli_history:
        return existing

    # 已存在的 ID + 图片 URL 集合（去重）
    existing_ids = {t.id for t in existing}
    existing_prompts = {t.sdxl_prompt for t in existing if t.sdxl_prompt}
    # 图片 URL 统一去掉前导 / 再比较
    existing_images = {
        t.final_image_url.lstrip("/") for t in existing if t.final_image_url
    }

    for entry in cli_history:
        prompt = entry.get("final_prompt", "")
        # 图片路径统一格式：去掉 ./ 和 \, 统一用 /
        image = entry.get("image", "").replace("\\", "/")
        image = image.removeprefix("./").removeprefix("/")

        # 图片不存在 → 跳过（旧历史已失效）
        if image and not os.path.isfile(image):
            continue

        # 按图片 URL 去重（最可靠）
        if image and image in existing_images:
            continue
        # 按 final_prompt 去重
        if prompt and prompt in existing_prompts:
            continue
        if prompt:
            existing_prompts.add(prompt)
        if image:
            existing_images.add(image)

        cli_id = "cli_" + (entry.get("timestamp", "").replace(":", "").replace("-", "").replace("T", "")[:14] or str(abs(hash(prompt)) % 100000))

        # 跳过已有的 cli_ ID
        if cli_id in existing_ids:
            continue
        existing_ids.add(cli_id)

        image_path = entry.get("image", "")
        # 规范化路径
        if image_path:
            image_path = image_path.replace("\\", "/")
            if image_path.startswith("./"):
                image_path = image_path[2:]

        record = TaskRecord(
            id=cli_id,
            user_input=entry.get("input", ""),
            status="done",
            created_at=entry.get("timestamp", ""),
            sdxl_prompt=prompt,
            final_image_url=image_path,
            version=1,
        )
        existing.append(record)

    # 按 created_at 排序
    existing.sort(key=lambda t: t.created_at or "")
    return existing


def generate_thumbnail(image_path: str, size: tuple = (300, 300)) -> Optional[str]:
    """生成缩略图，返回缩略图路径。"""
    if not image_path or not os.path.isfile(image_path):
        return None
    os.makedirs(THUMB_DIR, exist_ok=True)
    thumb_name = f"thumb_{os.path.basename(image_path)}"
    thumb_path = os.path.join(THUMB_DIR, thumb_name)
    if os.path.isfile(thumb_path):
        return thumb_path

    try:
        from PIL import Image
        img = Image.open(image_path)
        img.thumbnail(size, Image.LANCZOS)
        img.save(thumb_path)
        return thumb_path
    except Exception as e:
        print(f"[Thumb] 生成失败: {e}")
        return None
