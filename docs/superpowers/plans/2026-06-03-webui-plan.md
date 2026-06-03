# Web 前端 UI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AI 动漫图片生成项目构建完整的 Web 前端界面 (FastAPI + Vue 3)，替代现有 CLI 操作方式。

**Architecture:** FastAPI 后端提供 REST API + SSE 事件流，包装现有 LangGraph 管线通过 asyncio.Queue 推送实时进度。Vue 3 + Vite 前端提供 4 个页面（生成/历史/偏好/对比）。前后端分离开发，Vite 代理到 FastAPI。

**Tech Stack:** Python 3.11+ · FastAPI · asyncio · httpx · Vue 3 · Vite · Pinia · vanilla CSS (暗色主题)

---

## 文件结构计划

### 新建文件

| 文件 | 职责 |
|------|------|
| `server/__init__.py` | 空文件，标记包 |
| `server/app.py` | FastAPI 应用工厂：CORS、静态文件挂载、lifespan (ComfyUI 启停) |
| `server/routes.py` | 所有 REST 端点 + SSE 流 |
| `server/worker.py` | LangGraph 管线包装 + 事件发射到 asyncio.Queue |
| `server/comfyui_manager.py` | ComfyUI 进程生命周期管理 (启动/等待就绪/关闭) |
| `server/task_store.py` | history.json 读写 + 缩略图生成 |
| `server/run.py` | 开发/生产启动入口 |
| `web/` (Vue 3 项目) | 见下方前端文件列表 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `config.py` | 新增 `COMFYUI_PATH`, `SERVER_PORT`, `SERVER_HOST` |
| `agents/sdxl_enhancer.py` | 将 `_run_single_pass`, `_run_hires_pass`, `_rewrite_prompt` 暴露为公开函数 |

### 不改文件

`agents/text_expander.py`, `agents/coder_agent.py`, `agents/blender_executor.py`, `agents/blender_helpers.py`, `graph/workflow.py`, `state/schema.py`, `state/models.py`, `utils/helpers.py`, `utils/preferences.py`, `main.py`

---

## 阶段 1：后端骨架

### Task 1: 配置更新 + 公开 SDXL 函数

**Files:**
- Modify: `config.py`
- Modify: `agents/sdxl_enhancer.py`

- [ ] **Step 1: 在 config.py 添加 ComfyUI 和服务器配置**

```python
# 在 config.py 末尾的 config = Config() 之前添加:

    # --- ComfyUI 自动启动 ---
    COMFYUI_PATH = os.getenv("COMFYUI_PATH", "D:\\ComfyUI_windows_portable")
    COMFYUI_STARTUP_WAIT = int(os.getenv("COMFYUI_STARTUP_WAIT", "30"))  # 等待就绪最长秒数

    # --- Web 服务器 ---
    SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
```

- [ ] **Step 2: 在 sdxl_enhancer.py 暴露公开函数包装**

在 `agents/sdxl_enhancer.py` 末尾添加公开包装函数，供 `server/worker.py` 调用：

```python
# ===========================
# 公开 API（供 server/worker.py 调用）
# ===========================

async def public_run_single_pass(
    client: httpx.AsyncClient,
    image_filename: str = "",
    depth_filename: str = "",
    positive_prompt: str = "",
    negative_prompt: str = "",
    seed: int = 42,
    is_txt2img: bool = False,
    prefix: str = "enhanced",
) -> Optional[str]:
    """公开包装：调用 _run_single_pass。"""
    return await _run_single_pass(
        client=client,
        image_filename=image_filename,
        depth_filename=depth_filename,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        denoise=0.65,
        cn_strength=config.ANIME_DEPTH_CN_STRENGTH,
        steps=config.ANIME_STEPS,
        cfg=config.ANIME_CFG,
        prefix=prefix,
        use_cn=bool(depth_filename),
        is_txt2img=is_txt2img,
        lora_filename=config.COMFYUI_LORA_SHINKAI,
    )


async def public_run_hires_pass(
    client: httpx.AsyncClient,
    image_path: str,
    positive_prompt: str,
    negative_prompt: str,
    seed: int = 42,
    prefix: str = "hires",
) -> Optional[str]:
    """公开包装：调用 _run_hires_pass。"""
    return await _run_hires_pass(
        client=client,
        image_path=image_path,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        denoise=config.ANIME_HIRES_DENOISE,
        steps=config.ANIME_HIRES_STEPS,
        prefix=prefix,
        comfyui_input_dir=config.COMFYUI_INPUT_DIR,
    )


async def public_rewrite_prompt(
    current_prompt: str,
    user_request: str,
    category: str,
) -> str:
    """公开包装：调用 _rewrite_prompt。"""
    return await _rewrite_prompt(current_prompt, user_request, category)
```

- [ ] **Step 3: 验证导入**

```bash
python -c "from agents.sdxl_enhancer import public_run_single_pass, public_run_hires_pass, public_rewrite_prompt; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add config.py agents/sdxl_enhancer.py
git commit -m "feat: add ComfyUI/server config + expose SDXL public API functions"
```

### Task 2: ComfyUI 生命周期管理器

**Files:**
- Create: `server/__init__.py`
- Create: `server/comfyui_manager.py`

- [ ] **Step 1: 创建空 __init__.py**

```bash
echo "" > server/__init__.py
```

- [ ] **Step 2: 创建 server/comfyui_manager.py**

```python
"""ComfyUI 进程生命周期管理 — 启动/等待就绪/关闭。"""
import subprocess
import time
import httpx
import asyncio
import os
import sys
from config import config


class ComfyUIManager:
    """管理 ComfyUI 子进程。"""

    def __init__(self):
        self.process: subprocess.Popen | None = None

    def start(self):
        """启动 ComfyUI 进程并等待就绪。"""
        comfy_path = config.COMFYUI_PATH
        if not comfy_path or not os.path.isdir(comfy_path):
            print(f"[ComfyUI] 路径无效或未配置: {comfy_path}")
            print("[ComfyUI] 请手动启动 ComfyUI 或设置 COMFYUI_PATH 环境变量")
            return False

        # 判断启动脚本
        if sys.platform == "win32":
            main_script = os.path.join(comfy_path, "main.py")
            python_exe = os.path.join(comfy_path, "python_embeded", "python.exe")
            if os.path.isfile(python_exe):
                cmd = [python_exe, main_script]
            else:
                cmd = [sys.executable, main_script]
        else:
            main_script = os.path.join(comfy_path, "main.py")
            cmd = [sys.executable, main_script]

        env = os.environ.copy()
        env["COMFYUI_PORT"] = str(config.COMFYUI_BASE_URL).split(":")[-1].rstrip("/")

        print(f"[ComfyUI] 启动: {' '.join(cmd)}")
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=comfy_path,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print(f"[ComfyUI] 启动失败: 找不到 {cmd[0]}")
            return False

        # 等待就绪
        return self._wait_ready()

    def _wait_ready(self, timeout: int | None = None) -> bool:
        """轮询 ComfyUI 直到就绪或超时。"""
        if timeout is None:
            timeout = config.COMFYUI_STARTUP_WAIT
        base_url = config.COMFYUI_BASE_URL
        print(f"[ComfyUI] 等待就绪 (最多 {timeout}s)...")
        for i in range(timeout):
            try:
                resp = httpx.get(f"{base_url}/system_stats", timeout=3)
                if resp.status_code == 200:
                    print(f"[ComfyUI] 就绪 ({i+1}s)")
                    return True
            except Exception:
                pass
            time.sleep(1)
        print("[ComfyUI] 启动超时！请手动检查")
        return False

    def is_ready(self) -> bool:
        """检查 ComfyUI 是否在线。"""
        try:
            resp = httpx.get(f"{config.COMFYUI_BASE_URL}/system_stats", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def stop(self):
        """终止 ComfyUI 进程。"""
        if self.process is None:
            return
        print("[ComfyUI] 正在关闭...")
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        except Exception as e:
            print(f"[ComfyUI] 关闭异常: {e}")
        self.process = None
        print("[ComfyUI] 已关闭")


# 全局单例
comfyui = ComfyUIManager()
```

- [ ] **Step 3: 验证语法**

```bash
python -c "from server.comfyui_manager import ComfyUIManager, comfyui; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add server/__init__.py server/comfyui_manager.py
git commit -m "feat: add ComfyUI lifecycle manager"
```

### Task 3: 任务存储 (history.json)

**Files:**
- Create: `server/task_store.py`

- [ ] **Step 1: 创建 server/task_store.py**

```python
"""历史任务存储 — JSON 文件读写 + 缩略图生成。"""
import json
import os
import uuid
import shutil
from datetime import datetime
from typing import Optional
from pathlib import Path

HISTORY_PATH = "./output/history.json"
THUMB_DIR = "./output/thumbnails"
MAX_HISTORY = 200


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


def add_task(record: TaskRecord):
    """追加一条任务到历史。"""
    tasks = load_history()
    tasks.append(record)
    save_history(tasks)


def update_task(task_id: str, **kwargs):
    """更新任务字段。"""
    tasks = load_history()
    for t in tasks:
        if t.id == task_id:
            for k, v in kwargs.items():
                setattr(t, k, v)
            break
    save_history(tasks)


def get_task(task_id: str) -> Optional[TaskRecord]:
    """获取单个任务。"""
    for t in load_history():
        if t.id == task_id:
            return t
    return None


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
```

- [ ] **Step 2: 验证语法**

```bash
python -c "from server.task_store import TaskRecord, load_history, add_task; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add server/task_store.py
git commit -m "feat: add task history store with JSON persistence and thumbnails"
```

### Task 4: 管线包装 + 事件发射

**Files:**
- Create: `server/worker.py`

- [ ] **Step 1: 创建 server/worker.py**

```python
"""LangGraph 管线包装 — 运行 pipeline 并发射 SSE 事件到 asyncio.Queue。"""
import asyncio
import os
import traceback
import httpx
from config import config
from graph import app  # 现有 LangGraph 编译后的图
from state.schema import WorkflowState
from agents.sdxl_enhancer import (
    public_run_single_pass,
    public_run_hires_pass,
    public_rewrite_prompt,
    _check_frame_quality,
    _create_grid_image,
    _interactive_select,
)
from utils.preferences import get_prefs
from server.task_store import TaskRecord, update_task


async def run_pipeline(
    user_input: str,
    task_id: str,
    event_queue: asyncio.Queue,
):
    """执行完整的生成管线，通过 event_queue 推送进度事件。"""
    state = WorkflowState(user_input=user_input)

    try:
        # ---- 节点 1: 场景扩写 ----
        await event_queue.put({
            "event": "progress",
            "data": {"node": "场景扩写", "status": "running", "progress": 0},
        })
        async for step in app.astream(state):
            node_name = list(step.keys())[0]
            node_state = step[node_name]

            if node_name == "text_expander":
                output = node_state.get_node_output("text_expander")
                expanded = output.get("expanded_text", "")
                update_task(task_id, expanded_text=expanded)
                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "场景扩写", "status": "done", "progress": 25,
                        "preview": expanded[:150],
                    },
                })

            elif node_name == "coder_agent":
                output = node_state.get_node_output("coder_agent")
                prompt = output.get("sdxl_prompt", "")
                neg = output.get("sdxl_negative_prompt", "")
                script = output.get("blender_script", "")
                update_task(task_id, sdxl_prompt=prompt,
                            sdxl_negative_prompt=neg, blender_script=script)
                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "提示词生成", "status": "done", "progress": 50,
                        "preview": prompt[:200],
                    },
                })

            elif node_name == "blender_executor":
                output = node_state.get_node_output("blender_executor")
                depth = output.get("depth_path", "")
                frame = output.get("frame_path", "")
                err = output.get("blender_error")

                if err:
                    update_task(task_id, error_message=err, status="error")
                    await event_queue.put({
                        "event": "error",
                        "data": {"node": "3D 场景渲染", "message": err},
                    })
                    return

                # 转为相对 URL
                depth_url = _to_url(depth) if depth else ""
                frame_url = _to_url(frame) if frame else ""
                update_task(task_id, depth_image_url=depth_url, frame_image_url=frame_url)

                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "3D 场景渲染", "status": "done", "progress": 75,
                        "preview_url": depth_url,
                    },
                })

        # ---- 节点 4: AI 图像生成 ----
        final_state = state
        enhancer_output = final_state.get_node_output("sdxl_enhancer")
        all_paths = enhancer_output.get("final_image_paths", [])
        final_image = enhancer_output.get("final_image_path", "")

        if not final_image and not all_paths:
            await event_queue.put({
                "event": "error",
                "data": {"node": "AI 图像生成", "message": "SDXL 未生成图片"},
            })
            return

        # 构建 URL
        if all_paths:
            final_urls = [_to_url(p) for p in all_paths]
            grid_path = _create_grid_image(all_paths, config.COMFYUI_INPUT_DIR, idx=0)
            grid_url = _to_url(grid_path) if grid_path else ""
            update_task(task_id, final_image_url=final_urls[0] if final_urls else "",
                        grid_image_url=grid_url)
        else:
            final_urls = [_to_url(final_image)]
            update_task(task_id, final_image_url=final_urls[0])

        await event_queue.put({
            "event": "progress",
            "data": {"node": "AI 图像生成", "status": "done", "progress": 100},
        })

        if all_paths and grid_path:
            await event_queue.put({
                "event": "grid",
                "data": {"image_urls": final_urls, "grid_url": grid_url},
            })

        # ---- 弹出交互菜单 ----
        update_task(task_id, status="waiting_user")
        await event_queue.put({
            "event": "interactive",
            "data": {
                "type": "menu",
                "message": "图片生成完成！选择调整或保存",
                "image_url": final_urls[0],
                "task_id": task_id,
            },
        })

    except Exception as e:
        tb = traceback.format_exc()
        update_task(task_id, error_message=str(e)[:300], status="error")
        await event_queue.put({
            "event": "error",
            "data": {"node": "系统", "message": str(e)[:300]},
        })
        print(f"[Worker ERROR] {tb}")


async def run_interact(
    task_id: str,
    action: str,        # lighting | scene | character | pose | style
    description: str,
    depth_path: str,
    event_queue: asyncio.Queue,
):
    """仅重跑 SDXL + Hires Fix（交互重生成）。"""
    from server.task_store import get_task
    task = get_task(task_id)
    if not task:
        await event_queue.put({
            "event": "error", "data": {"message": "任务不存在"},
        })
        return

    category_map = {
        "lighting": "光线", "scene": "场景", "character": "角色",
        "pose": "姿态", "style": "风格",
    }
    category = category_map.get(action, action)

    # 1. 用 LLM 改写 prompt
    await event_queue.put({
        "event": "progress",
        "data": {"node": "AI 图像生成", "status": "running", "progress": 80},
    })

    new_prompt = await public_rewrite_prompt(
        task.sdxl_prompt or "", description, category,
    )
    update_task(task_id, sdxl_prompt=new_prompt)

    # 2. 生成新 seed
    import random
    seed = random.randint(1, 2_147_483_647)

    # 3. 构建 ComfyUI client
    async with httpx.AsyncClient(timeout=config.COMFYUI_TIMEOUT) as client:
        # 4. SDXL 生成
        depth_name = os.path.basename(depth_path) if depth_path else ""
        result = await public_run_single_pass(
            client=client,
            image_filename=os.path.basename(task.frame_image_url or ""),
            depth_filename=depth_name,
            positive_prompt=new_prompt,
            negative_prompt=task.sdxl_negative_prompt or "",
            seed=seed,
            prefix=f"v{task.version + 1}",
        )

        if not result:
            await event_queue.put({
                "event": "error", "data": {"message": "SDXL 生成失败"},
            })
            return

        # 5. Hires Fix (可选)
        if config.ANIME_HIRES_ENABLED:
            await event_queue.put({
                "event": "progress",
                "data": {"node": "高分辨率修复", "status": "running", "progress": 90},
            })
            result = await public_run_hires_pass(
                client=client,
                image_path=result,
                positive_prompt=new_prompt,
                negative_prompt=task.sdxl_negative_prompt or "",
                seed=seed,
                prefix=f"v{task.version + 1}",
            ) or result

    new_url = _to_url(result)
    task.version += 1
    task.interactions.append({"action": action, "description": description, "new_prompt": new_prompt})
    update_task(task_id, final_image_url=new_url, version=task.version,
                interactions=task.interactions)

    await event_queue.put({
        "event": "interactive",
        "data": {
            "type": "menu", "message": "调整完成！", "image_url": new_url,
            "task_id": task_id,
        },
    })


async def run_done(task_id: str):
    """用户满意保存：持久化偏好。"""
    from server.task_store import get_task
    task = get_task(task_id)
    if not task:
        return

    update_task(task_id, status="done")

    # 记录偏好
    if task.sdxl_prompt:
        prefs = get_prefs(config.USER_PREFS_PATH)
        prefs.learn_from_prompt(task.sdxl_prompt, positive=True)
        prefs.save()


def _to_url(fs_path: str) -> str:
    """将文件系统路径转为相对 URL。"""
    if not fs_path:
        return ""
    # 转为相对路径: /output/comfyui/xxx.png
    cwd = os.getcwd().replace("\\", "/")
    p = fs_path.replace("\\", "/")
    if p.startswith(cwd):
        p = p[len(cwd):]
        if not p.startswith("/"):
            p = "/" + p
    return p
```

- [ ] **Step 2: 验证语法**

```bash
python -c "from server.worker import run_pipeline, run_interact, run_done; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add server/worker.py
git commit -m "feat: add pipeline wrapper with SSE event emission"
```

### Task 5: FastAPI 路由 + SSE 端点

**Files:**
- Create: `server/routes.py`

- [ ] **Step 1: 创建 server/routes.py**

```python
"""FastAPI 路由：REST + SSE 端点。"""
import asyncio
import json
import uuid
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from server.worker import run_pipeline, run_interact, run_done
from server.task_store import (
    TaskRecord, add_task, get_task, update_task, load_history, search_tasks,
)
from server.comfyui_manager import comfyui

router = APIRouter(prefix="/api")

# 活跃任务的事件队列
_active_queues: dict[str, asyncio.Queue] = {}


# ---- 生成 ----

@router.post("/generate")
async def api_generate(req: Request):
    """提交生成任务。"""
    body = await req.json()
    user_input = body.get("user_input", "").strip()
    if not user_input:
        raise HTTPException(400, "user_input 不能为空")

    task_id = str(uuid.uuid4())[:8]
    record = TaskRecord(
        id=task_id, user_input=user_input, status="running",
    )
    add_task(record)

    # 创建事件队列，后台启动管线
    queue = asyncio.Queue()
    _active_queues[task_id] = queue
    asyncio.create_task(_run_and_cleanup(task_id, user_input, queue))

    return {"task_id": task_id}


async def _run_and_cleanup(task_id: str, user_input: str, queue: asyncio.Queue):
    """后台运行管线，完成后标记。"""
    try:
        await run_pipeline(user_input, task_id, queue)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await queue.put({
            "event": "error",
            "data": {"message": str(e)[:300]},
        })
    finally:
        await queue.put({"event": "complete", "data": {"task_id": task_id}})


# ---- SSE ----

@router.get("/events/{task_id}")
async def api_events(task_id: str):
    """SSE 事件流。"""
    queue = _active_queues.get(task_id)
    if not queue:
        # 任务不存在或已完成 → 发送 complete 事件
        async def immediate():
            yield "event: complete\ndata: {}\n\n"
        return StreamingResponse(immediate(), media_type="text/event-stream")

    async def event_stream():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                event_type = event.get("event", "progress")
                data = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"
                if event_type == "complete":
                    break
            except asyncio.TimeoutError:
                # 心跳
                yield f"event: ping\ndata: {{}}\n\n"

        # 清理
        _active_queues.pop(task_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---- 交互 ----

@router.post("/tasks/{task_id}/interact")
async def api_interact(task_id: str, req: Request):
    """交互菜单操作。"""
    body = await req.json()
    action = body.get("action", "")
    description = body.get("description", "")

    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    # 创建新事件队列
    queue = asyncio.Queue()
    _active_queues[task_id] = queue

    # 后台运行重生成
    depth_abs = ""
    if task.depth_image_url:
        import os
        cwd = os.getcwd()
        depth_abs = os.path.join(cwd, task.depth_image_url.lstrip("/"))

    asyncio.create_task(_interact_and_cleanup(task_id, action, description, depth_abs, queue))

    return {"task_id": task_id, "message": "重新生成中"}


async def _interact_and_cleanup(task_id, action, description, depth_path, queue):
    try:
        await run_interact(task_id, action, description, depth_path, queue)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await queue.put({"event": "error", "data": {"message": str(e)[:300]}})


@router.post("/tasks/{task_id}/done")
async def api_done(task_id: str):
    """用户确认满意。"""
    await run_done(task_id)
    return {"task_id": task_id, "status": "done"}


# ---- 历史 ----

@router.get("/tasks")
async def api_tasks(
    search: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """历史列表。"""
    results, total = search_tasks(search, page, limit)
    return {
        "tasks": [t.to_dict() for t in results],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/tasks/{task_id}")
async def api_task_detail(task_id: str):
    """单条任务详情。"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task.to_dict()


# ---- 偏好 ----

@router.get("/preferences")
async def api_get_prefs():
    """获取当前偏好。"""
    from utils.preferences import get_prefs
    from config import config
    prefs = get_prefs(config.USER_PREFS_PATH)
    return prefs.data


@router.post("/preferences")
async def api_update_prefs(req: Request):
    """更新偏好标签。"""
    body = await req.json()
    from utils.preferences import get_prefs
    from config import config
    prefs = get_prefs(config.USER_PREFS_PATH)
    category = body.get("category", "")
    tags = body.get("tags", [])
    if category and tags:
        prefs.add_liked(tags, category)
        prefs.save()
    return prefs.data


@router.delete("/preferences")
async def api_reset_prefs():
    """重置偏好。"""
    from utils.preferences import get_prefs
    from config import config
    import os
    path = config.USER_PREFS_PATH
    if os.path.isfile(path):
        os.remove(path)
    prefs = get_prefs(path)
    prefs.data = prefs._default()
    prefs.save()
    return prefs.data


# ---- 状态 ----

@router.get("/status")
async def api_status():
    """系统状态。"""
    import sys
    return {
        "comfyui": {
            "online": comfyui.is_ready(),
            "url": config.COMFYUI_BASE_URL,
        },
        "blender": config.BLENDER_EXECUTABLE_PATH,
        "sampler": config.ANIME_SAMPLER,
        "steps": config.ANIME_STEPS,
        "cfg": config.ANIME_CFG,
    }
```

- [ ] **Step 2: 验证语法**

```bash
python -c "from server.routes import router; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add server/routes.py
git commit -m "feat: add FastAPI routes with REST + SSE endpoints"
```

### Task 6: FastAPI 应用工厂 + 启动入口

**Files:**
- Create: `server/app.py`
- Create: `server/run.py`

- [ ] **Step 1: 创建 server/app.py**

```python
"""FastAPI 应用工厂 — CORS、静态文件、lifespan。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from server.routes import router
from server.comfyui_manager import comfyui


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动 ComfyUI / 关闭 ComfyUI。"""
    # 启动
    print("[Server] 启动中...")
    comfyui.start()

    yield

    # 关闭
    print("[Server] 关闭中...")
    comfyui.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Anime Generator", version="1.0", lifespan=lifespan)

    # CORS — 允许 Vite dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API 路由
    app.include_router(router)

    # 静态文件 — 让 output/ 下的图片可通过 URL 访问
    import os
    output_dir = os.path.abspath("./output")
    if os.path.isdir(output_dir):
        app.mount("/output", StaticFiles(directory=output_dir), name="output")

    return app
```

- [ ] **Step 2: 创建 server/run.py**

```python
"""开发/生产启动入口。"""
import uvicorn
from config import config
from server.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "server.run:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=True,
    )
```

- [ ] **Step 3: 安装 uvicorn**

```bash
pip install uvicorn  # 如果尚未安装
```

- [ ] **Step 4: 验证启动（不依赖 ComfyUI）**

```bash
# 先检查导入
python -c "from server.app import create_app; app = create_app(); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/run.py
git commit -m "feat: add FastAPI app factory with CORS, static files, and lifespan"
```

---

## 阶段 2：前端核心

### Task 7: Vue 3 项目脚手架

**Files:**
- Create: `web/package.json`
- Create: `web/index.html`
- Create: `web/vite.config.js`
- Create: `web/src/main.js`
- Create: `web/src/App.vue`
- Create: `web/src/router.js`

- [ ] **Step 1: 创建 web/package.json**

```json
{
  "name": "anime-generator-ui",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.5.0",
    "vue-router": "^4.4.0",
    "pinia": "^2.2.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "vite": "^6.0.0"
  }
}
```

- [ ] **Step 2: 创建 web/vite.config.js**

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/output': 'http://127.0.0.1:8000',
    },
  },
})
```

- [ ] **Step 3: 创建 web/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anime Generator</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

- [ ] **Step 4: 创建 web/src/main.js**

```js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

- [ ] **Step 5: 创建 web/src/router.js**

```js
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'generate', component: () => import('./views/GenerateView.vue') },
  { path: '/history', name: 'history', component: () => import('./views/HistoryView.vue') },
  { path: '/history/:id', name: 'history-detail', component: () => import('./views/HistoryDetail.vue') },
  { path: '/preferences', name: 'preferences', component: () => import('./views/PreferencesView.vue') },
  { path: '/compare', name: 'compare', component: () => import('./views/CompareView.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
```

- [ ] **Step 6: 创建全局样式 web/src/style.css**

```css
:root {
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --border: #30363d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --accent: #f9ae58;
  --accent-green: #7ec699;
  --accent-red: #e05252;
  --radius: 8px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
}

#app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

button {
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  padding: 8px 16px;
  border-radius: var(--radius);
  font-size: 14px;
  transition: background 0.15s;
}
button:hover { background: #30363d; }
button:disabled { opacity: 0.4; cursor: not-allowed; }
button.primary { background: var(--accent-green); color: #000; border-color: var(--accent-green); }
button.danger { background: var(--accent-red); border-color: var(--accent-red); }

input, textarea {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 14px;
  width: 100%;
}
input:focus, textarea:focus { outline: none; border-color: var(--accent); }

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
```

- [ ] **Step 7: 创建 web/src/App.vue（最小版）**

```vue
<template>
  <TheNav />
  <main class="main-content">
    <RouterView />
  </main>
</template>

<script setup>
import TheNav from './components/TheNav.vue'
</script>

<style scoped>
.main-content {
  flex: 1;
  padding: 20px 24px;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
}
</style>
```

- [ ] **Step 8: 创建占位 views**

创建 `web/src/views/` 目录和以下占位文件 (每个只需 `<template><div>Page</div></template>`):

```bash
mkdir -p web/src/views web/src/components web/src/stores web/src/api
```

- `web/src/views/GenerateView.vue` — `<template><div class="generate-view">GenerateView</div></template>`
- `web/src/views/HistoryView.vue` — `<template><div>HistoryView</div></template>`
- `web/src/views/HistoryDetail.vue` — `<template><div>HistoryDetail</div></template>`
- `web/src/views/PreferencesView.vue` — `<template><div>PreferencesView</div></template>`
- `web/src/views/CompareView.vue` — `<template><div>CompareView</div></template>`

- [ ] **Step 9: 创建 TheNav.vue 骨架**

`web/src/components/TheNav.vue`:

```vue
<template>
  <nav class="nav">
    <div class="nav-brand">🎨 Anime Generator</div>
    <div class="nav-links">
      <RouterLink to="/">生成</RouterLink>
      <RouterLink to="/history">历史</RouterLink>
      <RouterLink to="/preferences">偏好</RouterLink>
      <RouterLink to="/compare">对比</RouterLink>
    </div>
  </nav>
</template>

<script setup>
import { RouterLink } from 'vue-router'
</script>

<style scoped>
.nav {
  display: flex; align-items: center; gap: 24px;
  padding: 12px 24px; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
.nav-brand { font-weight: 700; font-size: 16px; }
.nav-links { display: flex; gap: 16px; }
.nav-links a { color: var(--text-secondary); font-size: 14px; padding: 4px 8px; border-radius: 4px; }
.nav-links a:hover { color: var(--text-primary); text-decoration: none; }
.nav-links a.router-link-exact-active { color: var(--accent); background: var(--bg-tertiary); }
</style>
```

- [ ] **Step 10: 安装依赖 + 验证构建**

```bash
cd web && npm install && npm run dev -- --host 127.0.0.1 &
# 等待几秒后 curl http://localhost:5173 应返回 HTML
```

- [ ] **Step 11: Commit**

```bash
git add web/
git commit -m "feat: scaffold Vue 3 project with router, pinia, and base styles"
```

### Task 8: API 客户端 + Pinia Stores

**Files:**
- Create: `web/src/api/client.js`
- Create: `web/src/api/sse.js`
- Create: `web/src/stores/taskStore.js`
- Create: `web/src/stores/prefsStore.js`

- [ ] **Step 1: 创建 web/src/api/client.js**

```js
const BASE = '/api'

export async function generate(userInput) {
  const res = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_input: userInput }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()  // { task_id }
}

export async function interact(taskId, action, description) {
  const res = await fetch(`${BASE}/tasks/${taskId}/interact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, description }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function markDone(taskId) {
  const res = await fetch(`${BASE}/tasks/${taskId}/done`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchTasks(search = '', page = 1, limit = 20) {
  const params = new URLSearchParams({ search, page, limit })
  const res = await fetch(`${BASE}/tasks?${params}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchTask(taskId) {
  const res = await fetch(`${BASE}/tasks/${taskId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchPreferences() {
  const res = await fetch(`${BASE}/preferences`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updatePreferences(category, tags) {
  const res = await fetch(`${BASE}/preferences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, tags }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function resetPreferences() {
  const res = await fetch(`${BASE}/preferences`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchStatus() {
  const res = await fetch(`${BASE}/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
```

- [ ] **Step 2: 创建 web/src/api/sse.js**

```js
export function connectSSE(taskId) {
  const url = `/api/events/${taskId}`
  const source = new EventSource(url)

  const listeners = {}

  source.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.progress) listeners.progress(data)
  })
  source.addEventListener('grid', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.grid) listeners.grid(data)
  })
  source.addEventListener('interactive', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.interactive) listeners.interactive(data)
  })
  source.addEventListener('complete', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.complete) listeners.complete(data)
  })
  source.addEventListener('error', (e) => {
    let data = {}
    try { data = JSON.parse(e.data) } catch (_) {}
    if (listeners.error) listeners.error(data)
  })
  source.addEventListener('ping', () => {})

  return {
    on(event, fn) { listeners[event] = fn; return this },
    close() { source.close() },
  }
}
```

- [ ] **Step 3: 创建 web/src/stores/taskStore.js**

```js
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useTaskStore = defineStore('task', () => {
  const currentTaskId = ref(null)
  const status = ref('idle')  // idle | running | waiting_user | done | error
  const progress = ref(0)
  const nodes = ref([
    { name: '场景扩写', status: 'pending' },
    { name: '提示词生成', status: 'pending' },
    { name: '3D 场景渲染', status: 'pending' },
    { name: 'AI 图像生成', status: 'pending' },
    { name: '高分辨率修复', status: 'pending' },
  ])
  const finalImageUrl = ref('')
  const gridImageUrl = ref('')
  const gridImageUrls = ref([])
  const expandedPreview = ref('')
  const errorMessage = ref('')

  function resetNodes() {
    nodes.value.forEach(n => n.status = 'pending')
    progress.value = 0
    finalImageUrl.value = ''
    gridImageUrl.value = ''
    gridImageUrls.value = []
    expandedPreview.value = ''
    errorMessage.value = ''
  }

  function setNodeStatus(name, s) {
    const node = nodes.value.find(n => n.name === name)
    if (node) node.status = s
  }

  function handleProgress(data) {
    if (data.status === 'running') {
      setNodeStatus(data.node, 'running')
    } else if (data.status === 'done') {
      setNodeStatus(data.node, 'done')
    }
    if (data.progress) progress.value = data.progress
    if (data.preview) expandedPreview.value = data.preview
  }

  return {
    currentTaskId, status, progress, nodes,
    finalImageUrl, gridImageUrl, gridImageUrls,
    expandedPreview, errorMessage,
    resetNodes, setNodeStatus, handleProgress,
  }
})
```

- [ ] **Step 4: 创建 web/src/stores/prefsStore.js**

```js
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchPreferences, updatePreferences, resetPreferences } from '../api/client'

export const usePrefsStore = defineStore('prefs', () => {
  const data = ref({ liked_tags: {}, disliked_tags: [] })
  const loading = ref(false)

  const categories = [
    { key: 'color_tone', label: '色调' },
    { key: 'lighting', label: '光线' },
    { key: 'style', label: '风格' },
    { key: 'mood', label: '氛围' },
    { key: 'composition', label: '构图' },
    { key: 'quality', label: '质量' },
  ]

  async function load() {
    loading.value = true
    try { data.value = await fetchPreferences() } catch (e) { console.error(e) }
    finally { loading.value = false }
  }

  async function addTags(category, tags) {
    data.value = await updatePreferences(category, tags)
  }

  async function reset() {
    data.value = await resetPreferences()
  }

  return { data, loading, categories, load, addTags, reset }
})
```

- [ ] **Step 5: 验证语法**

```bash
cd web && npx vite build --emptyOutDir  # 验证构建
```

- [ ] **Step 6: Commit**

```bash
git add web/src/api/ web/src/stores/
git commit -m "feat: add API client, SSE wrapper, Pinia stores (task + prefs)"
```

### Task 9: GenerateView — 核心生成页面

**Files:**
- Create/Modify: `web/src/views/GenerateView.vue`
- Create: `web/src/components/PromptInput.vue`
- Create: `web/src/components/ProgressPanel.vue`
- Create: `web/src/components/ResultDisplay.vue`
- Create: `web/src/components/InteractiveMenu.vue`

- [ ] **Step 1: 创建 PromptInput.vue**

```vue
<template>
  <div class="prompt-input">
    <input
      v-model="text"
      type="text"
      placeholder="描述你想要生成的场景，例如：夕阳下的教室中，一位女孩靠窗发呆"
      @keyup.enter="$emit('generate', text)"
      :disabled="disabled"
    />
    <button
      class="primary"
      @click="$emit('generate', text)"
      :disabled="disabled || !text.trim()"
    >
      🚀 开始生成
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
defineProps({ disabled: Boolean })
defineEmits(['generate'])
const text = ref('')
</script>

<style scoped>
.prompt-input {
  display: flex; gap: 12px;
  padding: 16px; background: var(--bg-secondary);
  border-radius: var(--radius); border: 1px solid var(--border);
}
.prompt-input input { flex: 1; }
.prompt-input button {
  white-space: nowrap; font-weight: 600;
  padding: 10px 24px;
}
</style>
```

- [ ] **Step 2: 创建 ProgressPanel.vue**

```vue
<template>
  <div class="progress-panel">
    <div class="label">生成进度</div>
    <div class="nodes">
      <div
        v-for="node in nodes"
        :key="node.name"
        class="node"
        :class="node.status"
      >
        <span class="node-icon">
          {{ node.status === 'done' ? '✓' : node.status === 'running' ? '◉' : '○' }}
        </span>
        <span class="node-name">{{ node.name }}</span>
      </div>
    </div>
    <div class="progress-bar-track">
      <div class="progress-bar-fill" :style="{ width: progress + '%' }"></div>
    </div>
    <div v-if="expandedPreview" class="preview-box">
      <div class="label" style="margin-bottom:4px;">当前预览</div>
      <p class="preview-text">{{ expandedPreview }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  nodes: Array,
  progress: Number,
  expandedPreview: String,
})
</script>

<style scoped>
.progress-panel {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px;
  min-width: 260px;
}
.label { font-size: 11px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 8px; letter-spacing: 0.5px; }
.nodes { margin-bottom: 10px; }
.node { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
.node.pending { color: var(--text-secondary); }
.node.running { color: var(--accent); }
.node.done { color: var(--accent-green); }
.node-icon { width: 16px; text-align: center; }
.progress-bar-track {
  background: var(--bg-tertiary); border-radius: 4px; height: 6px; margin: 10px 0;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-green));
  border-radius: 4px; transition: width 0.3s;
}
.preview-box { margin-top: 10px; padding: 8px; background: var(--bg-primary); border-radius: 4px; }
.preview-text { font-size: 12px; color: var(--text-secondary); line-height: 1.5; max-height: 100px; overflow: hidden; }
</style>
```

- [ ] **Step 3: 创建 ResultDisplay.vue**

```vue
<template>
  <div class="result-display" :class="{ empty: !imageUrl }">
    <div v-if="imageUrl" class="image-wrapper">
      <img :src="imageUrl" :alt="alt" @click="$emit('lightbox', imageUrl)" />
      <div class="image-actions">
        <a :href="imageUrl" download>⬇ 下载</a>
        <button @click="$emit('lightbox', imageUrl)">🔍 放大</button>
      </div>
    </div>
    <div v-else class="placeholder">
      <div class="placeholder-icon">🖼️</div>
      <div class="placeholder-text">生成结果将在这里展示</div>
    </div>
  </div>
</template>

<script setup>
defineProps({ imageUrl: String, alt: { type: String, default: '' } })
defineEmits(['lightbox'])
</script>

<style scoped>
.result-display {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); min-height: 380px;
  display: flex; align-items: center; justify-content: center;
  flex: 1; overflow: hidden;
}
.result-display.empty { background: var(--bg-primary); }
.image-wrapper { position: relative; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.image-wrapper img { max-width: 100%; max-height: 500px; object-fit: contain; border-radius: 4px; cursor: pointer; }
.image-actions {
  position: absolute; bottom: 8px; right: 8px;
  display: flex; gap: 8px;
}
.image-actions a, .image-actions button {
  background: rgba(0,0,0,0.7); color: #fff; font-size: 12px;
  padding: 4px 10px; border-radius: 4px; border: none;
}
.placeholder { text-align: center; color: var(--text-secondary); }
.placeholder-icon { font-size: 48px; margin-bottom: 8px; }
.placeholder-text { font-size: 14px; }
</style>
```

- [ ] **Step 4: 创建 InteractiveMenu.vue**

```vue
<template>
  <div class="interactive-menu" v-if="visible">
    <span class="menu-label">调整生成：</span>
    <button v-for="opt in options" :key="opt.action"
      @click="$emit('select', opt.action)" :disabled="disabled">
      {{ opt.emoji }} {{ opt.label }}
    </button>
    <button class="primary" @click="$emit('done')" style="margin-left:auto;" :disabled="disabled">
      ✅ 满意保存
    </button>
  </div>
</template>

<script setup>
defineProps({
  visible: Boolean,
  disabled: Boolean,
})
defineEmits(['select', 'done'])

const options = [
  { action: 'lighting', emoji: '☀️', label: '换光线' },
  { action: 'scene', emoji: '🎨', label: '换场景' },
  { action: 'character', emoji: '✏️', label: '微调角色' },
  { action: 'pose', emoji: '🔄', label: '换姿态' },
  { action: 'style', emoji: '🖼️', label: '换风格' },
]
</script>

<style scoped>
.interactive-menu {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  padding: 12px 16px; background: var(--bg-secondary);
  border: 1px solid var(--border); border-radius: var(--radius);
  margin-top: 12px;
}
.menu-label { font-size: 13px; color: var(--text-secondary); margin-right: 4px; }
</style>
```

- [ ] **Step 5: 创建完整的 GenerateView.vue**

```vue
<template>
  <div class="generate-view">
    <PromptInput @generate="startGenerate" :disabled="taskStatus === 'running'" />

    <div class="generate-body">
      <ProgressPanel
        :nodes="store.nodes"
        :progress="store.progress"
        :expandedPreview="store.expandedPreview"
      />
      <ResultDisplay
        :imageUrl="store.finalImageUrl"
        @lightbox="showLightbox = $event"
      />
    </div>

    <InteractiveMenu
      :visible="taskStatus === 'waiting_user'"
      :disabled="taskStatus === 'running'"
      @select="handleInteract"
      @done="handleDone"
    />

    <!-- 交互描述输入弹窗 -->
    <div v-if="showDescInput" class="modal-overlay" @click.self="showDescInput = false">
      <div class="modal-box">
        <h3>{{ currentActionLabel }}</h3>
        <input
          v-model="descText"
          type="text"
          :placeholder="descPlaceholder"
          @keyup.enter="submitInteract"
          ref="descInput"
        />
        <div class="modal-actions">
          <button @click="showDescInput = false">取消</button>
          <button class="primary" @click="submitInteract" :disabled="!descText.trim()">确定</button>
        </div>
      </div>
    </div>

    <!-- Lightbox -->
    <div v-if="showLightbox" class="lightbox" @click="showLightbox = null">
      <img :src="showLightbox" @click.stop />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useTaskStore } from '../stores/taskStore'
import { generate, interact, markDone } from '../api/client'
import { connectSSE } from '../api/sse'
import PromptInput from '../components/PromptInput.vue'
import ProgressPanel from '../components/ProgressPanel.vue'
import ResultDisplay from '../components/ResultDisplay.vue'
import InteractiveMenu from '../components/InteractiveMenu.vue'

const store = useTaskStore()
const taskStatus = computed(() => store.status)

const showDescInput = ref(false)
const currentAction = ref('')
const descText = ref('')
const descInput = ref(null)
const showLightbox = ref(null)

const actionLabels = { lighting: '换光线', scene: '换场景', character: '微调角色', pose: '换姿态', style: '换风格' }
const currentActionLabel = computed(() => actionLabels[currentAction.value] || '')
const descPlaceholder = computed(() => {
  const placeholders = {
    lighting: '例如：黄昏的暖光、金色斜阳...',
    scene: '例如：换成海边、换成咖啡馆...',
    character: '例如：短发、戴眼镜、换白色连衣裙...',
    pose: '例如：站立回头、手托腮、伸手...',
    style: '例如：水彩风格、线稿风格...',
  }
  return placeholders[currentAction.value] || '描述你想要的变化...'
})

async function startGenerate(userInput) {
  store.resetNodes()
  store.status = 'running'
  store.errorMessage = ''

  try {
    const { task_id } = await generate(userInput)
    store.currentTaskId = task_id

    connectSSE(task_id)
      .on('progress', (data) => store.handleProgress(data))
      .on('grid', (data) => {
        store.gridImageUrl = data.grid_url
        store.gridImageUrls = data.image_urls || []
      })
      .on('interactive', (data) => {
        store.status = 'waiting_user'
        store.finalImageUrl = data.image_url
        store.progress = 100
      })
      .on('complete', () => {
        if (store.status === 'running') store.status = 'done'
      })
      .on('error', (data) => {
        store.status = 'error'
        store.errorMessage = data.message || '未知错误'
      })
  } catch (e) {
    store.status = 'error'
    store.errorMessage = e.message
  }
}

function handleInteract(action) {
  currentAction.value = action
  descText.value = ''
  showDescInput.value = true
  nextTick(() => descInput.value?.focus())
}

async function submitInteract() {
  if (!descText.value.trim()) return
  showDescInput.value = false
  store.status = 'running'

  try {
    await interact(store.currentTaskId, currentAction.value, descText.value.trim())

    // 重新连接 SSE 流
    connectSSE(store.currentTaskId)
      .on('interactive', (data) => {
        store.status = 'waiting_user'
        store.finalImageUrl = data.image_url
      })
      .on('error', (data) => {
        store.status = 'error'
        store.errorMessage = data.message || '交互失败'
      })
  } catch (e) {
    store.status = 'error'
    store.errorMessage = e.message
  }
}

async function handleDone() {
  store.status = 'done'
  try { await markDone(store.currentTaskId) } catch (e) { console.error(e) }
}
</script>

<style scoped>
.generate-view { display: flex; flex-direction: column; gap: 12px; }
.generate-body { display: flex; gap: 16px; }

.modal-overlay {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-box {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 12px; padding: 24px; min-width: 400px;
}
.modal-box h3 { margin-bottom: 12px; }
.modal-actions { display: flex; gap: 8px; margin-top: 12px; justify-content: flex-end; }

.lightbox {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.9); display: flex; align-items: center; justify-content: center;
  z-index: 200; cursor: zoom-out;
}
.lightbox img { max-width: 90%; max-height: 90%; object-fit: contain; }
</style>
```

- [ ] **Step 6: 验证整个流程（需要 FastAPI 运行）**

```bash
# Terminal 1: 启动 FastAPI
python server/run.py &

# Terminal 2: 构建前端
cd web && npx vite build
```

- [ ] **Step 7: Commit**

```bash
git add web/src/views/GenerateView.vue web/src/components/PromptInput.vue web/src/components/ProgressPanel.vue web/src/components/ResultDisplay.vue web/src/components/InteractiveMenu.vue
git commit -m "feat: implement GenerateView with full pipeline UI + SSE progress"
```

### Task 10: TheFooter 状态栏

**Files:**
- Create: `web/src/components/TheFooter.vue`

- [ ] **Step 1: 创建 TheFooter.vue**

```vue
<template>
  <footer class="footer">
    <span class="status-item" :class="{ online: status.comfyui?.online }">
      <span class="dot"></span>
      ComfyUI {{ status.comfyui?.online ? '在线' : '离线' }}
    </span>
    <span class="status-item">
      Blender {{ status.blender ? '✓' : '✗' }}
    </span>
    <span class="status-item">
      {{ status.sampler }} · {{ status.steps }} steps · CFG {{ status.cfg }}
    </span>
  </footer>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchStatus } from '../api/client'

const status = ref({ comfyui: { online: false, url: '' }, blender: '', sampler: '', steps: '', cfg: '' })

onMounted(async () => {
  try { status.value = await fetchStatus() } catch (e) { console.error(e) }
  // 每 30 秒刷新
  setInterval(async () => {
    try { status.value = await fetchStatus() } catch (_) {}
  }, 30000)
})
</script>

<style scoped>
.footer {
  display: flex; gap: 20px; align-items: center;
  padding: 8px 24px; background: var(--bg-secondary);
  border-top: 1px solid var(--border); font-size: 12px; color: var(--text-secondary);
}
.status-item { display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-red); }
.online .dot { background: var(--accent-green); }
</style>
```

- [ ] **Step 2: 更新 App.vue 加入 Footer**

在 `App.vue` 的 `<template>` 中，`</main>` 后面加 `<TheFooter />`，并在 script 中 import。

- [ ] **Step 3: Commit**

```bash
git add web/src/components/TheFooter.vue web/src/App.vue
git commit -m "feat: add system status footer with ComfyUI/Blender indicators"
```

---

## 阶段 3：辅助页面

### Task 11: HistoryView + HistoryDetail

**Files:**
- Modify: `web/src/views/HistoryView.vue`
- Modify: `web/src/views/HistoryDetail.vue`
- Create: `web/src/components/HistoryGrid.vue`
- Create: `web/src/components/HistoryCard.vue`
- Create: `web/src/components/SearchBar.vue`

- [ ] **Step 1: 创建 SearchBar.vue**

```vue
<template>
  <div class="search-bar">
    <input v-model="query" type="text" placeholder="🔍 搜索提示词或描述..." @keyup.enter="search" />
    <button @click="search">搜索</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
const emit = defineEmits(['search'])
const query = ref('')
function search() { emit('search', query.value) }
</script>

<style scoped>
.search-bar { display: flex; gap: 8px; }
.search-bar input { flex: 1; }
.search-bar button { white-space: nowrap; }
</style>
```

- [ ] **Step 2: 创建 HistoryCard.vue**

```vue
<template>
  <div class="card" @click="$emit('click')">
    <div class="card-img">
      <img v-if="imageUrl" :src="imageUrl" :alt="prompt" />
      <div v-else class="no-img">📷</div>
    </div>
    <div class="card-body">
      <div class="card-date">{{ date }}</div>
      <div class="card-prompt">{{ prompt || userInput }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  imageUrl: String, prompt: String, userInput: String, date: String,
})
defineEmits(['click'])
</script>

<style scoped>
.card {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; cursor: pointer;
  transition: border-color 0.15s;
}
.card:hover { border-color: var(--accent); }
.card-img { aspect-ratio: 1; overflow: hidden; background: var(--bg-primary); display: flex; align-items: center; justify-content: center; }
.card-img img { width: 100%; height: 100%; object-fit: cover; }
.no-img { font-size: 32px; color: var(--text-secondary); }
.card-body { padding: 10px; }
.card-date { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.card-prompt { font-size: 12px; color: var(--text-primary); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
```

- [ ] **Step 3: 创建 HistoryGrid.vue**

```vue
<template>
  <div class="history-grid">
    <HistoryCard
      v-for="task in tasks" :key="task.id"
      :imageUrl="task.final_image_url"
      :prompt="task.sdxl_prompt"
      :userInput="task.user_input"
      :date="formatDate(task.created_at)"
      @click="$emit('click', task.id)"
    />
  </div>
</template>

<script setup>
import HistoryCard from './HistoryCard.vue'
defineProps({ tasks: Array })
defineEmits(['click'])

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' })
}
</script>

<style scoped>
.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
</style>
```

- [ ] **Step 4: 创建完整的 HistoryView.vue**

```vue
<template>
  <div class="history-view">
    <h2>历史画廊</h2>
    <SearchBar @search="handleSearch" />
    <HistoryGrid :tasks="tasks" @click="goDetail" />
    <div class="pagination" v-if="total > limit">
      <button :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span>{{ page }} / {{ Math.ceil(total / limit) }}</span>
      <button :disabled="page >= Math.ceil(total / limit)" @click="goPage(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchTasks } from '../api/client'
import SearchBar from '../components/SearchBar.vue'
import HistoryGrid from '../components/HistoryGrid.vue'

const router = useRouter()
const tasks = ref([])
const total = ref(0)
const page = ref(1)
const searchQuery = ref('')
const limit = 20

async function loadTasks() {
  try {
    const result = await fetchTasks(searchQuery.value, page.value, limit)
    tasks.value = result.tasks
    total.value = result.total
  } catch (e) { console.error(e) }
}

function handleSearch(query) {
  searchQuery.value = query
  page.value = 1
  loadTasks()
}

function goPage(p) { page.value = p; loadTasks() }
function goDetail(id) { router.push(`/history/${id}`) }

onMounted(loadTasks)
</script>

<style scoped>
.history-view { display: flex; flex-direction: column; gap: 16px; }
.pagination { display: flex; gap: 12px; align-items: center; justify-content: center; margin-top: 16px; }
</style>
```

- [ ] **Step 5: 创建 HistoryDetail.vue**

```vue
<template>
  <div class="detail-view" v-if="task">
    <button @click="$router.push('/history')" class="back-btn">← 返回画廊</button>
    <div class="detail-layout">
      <div class="detail-image">
        <img :src="task.final_image_url" v-if="task.final_image_url" />
        <div v-else class="no-img">暂无图片</div>
      </div>
      <div class="detail-info">
        <h3>原始输入</h3>
        <p>{{ task.user_input }}</p>
        <h3>SDXL 提示词</h3>
        <code>{{ task.sdxl_prompt }}</code>
        <h3>负向提示词</h3>
        <code>{{ task.sdxl_negative_prompt }}</code>
        <h3>参数</h3>
        <pre>{{ JSON.stringify(task.params, null, 2) }}</pre>
        <h3>交互历史</h3>
        <ul v-if="task.interactions?.length">
          <li v-for="(i, idx) in task.interactions" :key="idx">
            {{ i.action }} → {{ i.description }}
          </li>
        </ul>
        <p v-else>无交互记录</p>
        <h3>生成时间</h3>
        <p>{{ task.created_at }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchTask } from '../api/client'

const route = useRoute()
const task = ref(null)

onMounted(async () => {
  try { task.value = await fetchTask(route.params.id) } catch (e) { console.error(e) }
})
</script>

<style scoped>
.detail-view { display: flex; flex-direction: column; gap: 16px; }
.back-btn { align-self: flex-start; }
.detail-layout { display: flex; gap: 24px; }
.detail-image { flex: 1; }
.detail-image img { max-width: 100%; border-radius: var(--radius); }
.detail-info { flex: 1; display: flex; flex-direction: column; gap: 8px; }
.detail-info h3 { font-size: 13px; color: var(--text-secondary); margin-top: 12px; margin-bottom: 2px; }
.detail-info code { font-size: 12px; background: var(--bg-tertiary); padding: 6px 10px; border-radius: 4px; word-break: break-all; display: block; }
.detail-info pre { font-size: 11px; background: var(--bg-tertiary); padding: 8px; border-radius: 4px; overflow-x: auto; }
.no-img { font-size: 32px; color: var(--text-secondary); }
</style>
```

- [ ] **Step 6: Commit**

```bash
git add web/src/views/HistoryView.vue web/src/views/HistoryDetail.vue web/src/components/HistoryGrid.vue web/src/components/HistoryCard.vue web/src/components/SearchBar.vue
git commit -m "feat: implement history gallery with search and detail view"
```

### Task 12: PreferencesView + CompareView

**Files:**
- Modify: `web/src/views/PreferencesView.vue`
- Modify: `web/src/views/CompareView.vue`
- Create: `web/src/components/PreferenceCategory.vue`

- [ ] **Step 1: 创建 PreferencesView.vue**

```vue
<template>
  <div class="prefs-view">
    <h2>用户偏好管理</h2>
    <div class="prefs-grid">
      <div v-for="cat in store.categories" :key="cat.key" class="pref-card">
        <h3>{{ cat.label }}</h3>
        <div class="tags">
          <span v-for="tag in getTags(cat.key)" :key="tag" class="tag">
            {{ tag }}
            <button class="tag-remove" @click="removeTag(cat.key, tag)">×</button>
          </span>
          <span v-if="!getTags(cat.key).length" class="empty-tag">暂无偏好</span>
        </div>
        <div class="add-tag">
          <input v-model="newTag[cat.key]" type="text" placeholder="添加标签..." @keyup.enter="addTag(cat.key)" />
          <button @click="addTag(cat.key)">+</button>
        </div>
      </div>
    </div>
    <button class="danger" @click="handleReset" style="margin-top:16px;">🔄 重置所有偏好</button>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { usePrefsStore } from '../stores/prefsStore'

const store = usePrefsStore()
const newTag = reactive({})

function getTags(catKey) {
  return store.data?.liked_tags?.[catKey] || []
}

async function addTag(catKey) {
  const t = (newTag[catKey] || '').trim()
  if (!t) return
  await store.addTags(catKey, [t])
  newTag[catKey] = ''
}

async function removeTag(catKey, tag) {
  // 通过重新设置去实现删除
  const current = getTags(catKey).filter(t => t !== tag)
  // 用 addTags + reset 组合：先 reset 当前分类，再批量添加
  // 简化方案：直接操作本地 + 保存
  if (store.data?.liked_tags) {
    store.data.liked_tags[catKey] = current
    await store.addTags(catKey, [])  // 触发 save
  }
}

async function handleReset() {
  if (confirm('确定要重置所有偏好吗？')) {
    await store.reset()
  }
}

onMounted(() => store.load())
</script>

<style scoped>
.prefs-view { display: flex; flex-direction: column; }
.prefs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; margin-top: 16px; }
.pref-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.pref-card h3 { margin-bottom: 8px; color: var(--accent); font-size: 14px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.tag { background: var(--bg-tertiary); padding: 3px 8px; border-radius: 4px; font-size: 12px; display: flex; align-items: center; gap: 4px; }
.tag-remove { background: none; border: none; color: var(--text-secondary); font-size: 14px; padding: 0; cursor: pointer; }
.tag-remove:hover { color: var(--accent-red); }
.empty-tag { font-size: 12px; color: var(--text-secondary); }
.add-tag { display: flex; gap: 4px; }
.add-tag input { padding: 5px 8px; font-size: 12px; }
.add-tag button { padding: 4px 10px; font-size: 14px; }
</style>
```

- [ ] **Step 2: 创建 CompareView.vue**

```vue
<template>
  <div class="compare-view">
    <h2>多图对比</h2>
    <p class="subtitle">从历史中选择 2-4 张图片并排比较</p>
    <div class="compare-grid" :class="'cols-' + slots.length">
      <div v-for="(slot, i) in slots" :key="i" class="slot">
        <div v-if="!slot" class="slot-empty" @click="showPickerFor = i">
          + 选择图片
        </div>
        <div v-else class="slot-filled">
          <img :src="slot.final_image_url" />
          <button class="slot-remove" @click="slots[i] = null">×</button>
          <div class="slot-info">{{ slot.sdxl_prompt?.slice(0, 60) }}...</div>
        </div>
      </div>
    </div>

    <!-- 图片选择器 -->
    <div class="picker" v-if="showPickerFor !== null">
      <h3>选择图片添加到第 {{ showPickerFor + 1 }} 格</h3>
      <div class="picker-grid">
        <div
          v-for="task in tasks" :key="task.id"
          class="picker-item"
          @click="selectForSlot(task)"
          :class="{ selected: selectedId === task.id }"
        >
          <img :src="task.final_image_url" v-if="task.final_image_url" />
          <div class="picker-prompt">{{ task.sdxl_prompt?.slice(0, 40) }}</div>
        </div>
      </div>
      <button @click="showPickerFor = null">取消</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchTasks } from '../api/client'

const slots = ref([null, null])
const tasks = ref([])
const showPickerFor = ref(null)
const selectedId = ref(null)

async function loadTasks() {
  try { const r = await fetchTasks('', 1, 50); tasks.value = r.tasks } catch (e) { console.error(e) }
}

function selectForSlot(task) {
  slots.value[showPickerFor.value] = task
  showPickerFor.value = null
}

onMounted(loadTasks)
</script>

<style scoped>
.compare-view { display: flex; flex-direction: column; gap: 16px; }
.subtitle { color: var(--text-secondary); font-size: 14px; }
.compare-grid { display: grid; gap: 12px; }
.compare-grid.cols-2 { grid-template-columns: 1fr 1fr; }
.compare-grid.cols-3 { grid-template-columns: 1fr 1fr 1fr; }
.compare-grid.cols-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.slot { aspect-ratio: 1; background: var(--bg-secondary); border: 2px dashed var(--border); border-radius: var(--radius); display: flex; align-items: center; justify-content: center; position: relative; }
.slot-empty { font-size: 18px; color: var(--text-secondary); cursor: pointer; }
.slot-filled { width: 100%; height: 100%; }
.slot-filled img { width: 100%; height: 100%; object-fit: cover; border-radius: var(--radius); }
.slot-remove { position: absolute; top: 4px; right: 4px; background: rgba(0,0,0,0.7); border: none; color: #fff; width: 24px; height: 24px; border-radius: 50%; font-size: 16px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.slot-info { position: absolute; bottom: 0; left: 0; right: 0; padding: 6px; background: rgba(0,0,0,0.7); font-size: 11px; color: #ddd; border-radius: 0 0 var(--radius) var(--radius); }
.picker { margin-top: 16px; padding: 16px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: var(--radius); }
.picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; margin: 12px 0; max-height: 300px; overflow-y: auto; }
.picker-item { cursor: pointer; border: 2px solid transparent; border-radius: 4px; overflow: hidden; }
.picker-item.selected { border-color: var(--accent); }
.picker-item img { width: 100%; aspect-ratio: 1; object-fit: cover; }
.picker-prompt { font-size: 10px; padding: 4px; color: var(--text-secondary); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
</style>
```

- [ ] **Step 3: 添加 slots 数量控制**

在 CompareView 中添加按钮来增加/减少对比格数：
```vue
<!-- 在 template 中 h2 下方添加 -->
<div class="slot-controls">
  <button @click="addSlot" :disabled="slots.length >= 4">+ 添加对比格</button>
  <button @click="removeSlot" :disabled="slots.length <= 2">- 移除对比格</button>
</div>
```

并在 script 添加:
```js
function addSlot() { if (slots.value.length < 4) slots.value.push(null) }
function removeSlot() { if (slots.value.length > 2) slots.value.pop() }
```

- [ ] **Step 4: Commit**

```bash
git add web/src/views/PreferencesView.vue web/src/views/CompareView.vue
git commit -m "feat: implement preferences management and image comparison views"
```

### Task 13: ImageLightbox 全局组件

**Files:**
- Create: `web/src/components/ImageLightbox.vue`

- [ ] **Step 1: 复用 GenerateView 中已有的 lightbox 逻辑，提取为独立组件**

```vue
<template>
  <Teleport to="body">
    <div v-if="visible" class="lightbox" @click="close">
      <img :src="src" @click.stop />
    </div>
  </Teleport>
</template>

<script setup>
defineProps({ visible: Boolean, src: String })
const emit = defineEmits(['close'])
function close() { emit('close') }
</script>

<style scoped>
.lightbox {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.9); display: flex; align-items: center; justify-content: center;
  z-index: 9999; cursor: zoom-out;
}
.lightbox img { max-width: 90%; max-height: 90%; object-fit: contain; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add web/src/components/ImageLightbox.vue
git commit -m "feat: add ImageLightbox global component"
```

### Task 14: 完整集成验证

- [ ] **Step 1: 启动后端**

```bash
python server/run.py
```
确认控制台输出 `[ComfyUI] 就绪` 和 `Uvicorn running on http://127.0.0.1:8000`

- [ ] **Step 2: 启动前端**

```bash
cd web && npm run dev
```

- [ ] **Step 3: 浏览器测试完整流程**

1. 打开 `http://localhost:5173`
2. 确认导航栏 4 个链接正常
3. 输入场景描述，点击"开始生成"
4. 观察进度面板实时更新（场景扩写 → 提示词生成 → 3D 场景渲染 → AI 图像生成）
5. 生成完成后交互菜单出现
6. 点击"换光线"→ 输入描述 → 确认 → 等待新图
7. 点击"满意保存"
8. 切换到历史页，确认刚生成的图片在列表中
9. 切换到偏好页，确认偏好被自动记录
10. 切换到底部状态栏，确认 ComfyUI 显示在线

- [ ] **Step 4: 修复发现的问题后提交**

```bash
git add .
git commit -m "feat: complete web UI integration — all pages working"
```

---

## 自检清单

- [x] Spec coverage: 每个 spec 章节都有对应任务 — 架构 (Task 4-6), API (Task 5), 前端页面 (Task 9/11/12), 存储 (Task 3), ComfyUI 自动启动 (Task 2), 管线改造 (Task 4), 交互重生成 (Task 4 worker.py run_interact)
- [x] No placeholders — 所有步骤包含完整代码
- [x] Type consistency — TaskRecord 字段名在 worker.py、routes.py、taskStore.js 中保持一致
- [x] SSE 事件字段名 (node/status/progress/preview/image_url/grid_url) 前后端一致
