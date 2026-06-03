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


def search_tasks(query: str = "", page: int = 1, limit: int = 20) -> tuple[list[TaskRecord], int]:
    """搜索历史 (按关键词匹配 user_input 或 sdxl_prompt)，返回 (结果, 总数)。"""
    tasks = load_history()
    if query:
        q = query.lower()
        tasks = [t for t in tasks if
                 (t.user_input and q in t.user_input.lower()) or
                 (t.sdxl_prompt and q in t.sdxl_prompt.lower())]
    total = len(tasks)
    start = (page - 1) * limit
    end = start + limit
    return tasks[::-1][start:end], total  # 最新在前


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
