"""FastAPI 路由：REST + SSE 端点。"""
import asyncio
import json
import uuid
import os
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from server.worker import run_pipeline, run_interact, run_done
from server.task_store import (
    TaskRecord, add_task_in_memory, get_task, update_task, search_tasks, finalize_task,
)
from server.comfyui_manager import comfyui
from config import config

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
    add_task_in_memory(record)

    # 创建事件队列，后台启动管线
    queue: asyncio.Queue = asyncio.Queue()
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
        await queue.put({"event": "complete", "data": {"task_id": task_id}})
    # 注意：不在这里发 complete — interactive 阶段需要 SSE 保持打开
    # complete 只在用户确认 done 或出错时发送


# ---- SSE ----

@router.get("/events/{task_id}")
async def api_events(task_id: str):
    """SSE 事件流。"""
    queue = _active_queues.get(task_id)
    if not queue:
        # 任务不存在或已完成
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
                yield "event: ping\ndata: {}\n\n"

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
    queue: asyncio.Queue = asyncio.Queue()
    _active_queues[task_id] = queue

    # 将 URL 路径转回文件系统路径
    depth_abs = ""
    if task.depth_image_url:
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
    # 将任务从内存写入历史
    finalize_task(task_id)
    # 关闭 SSE 流
    queue = _active_queues.pop(task_id, None)
    if queue:
        await queue.put({"event": "complete", "data": {"task_id": task_id}})
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
    prefs = get_prefs(config.USER_PREFS_PATH)
    return prefs.data


@router.post("/preferences")
async def api_update_prefs(req: Request):
    """更新偏好标签。"""
    body = await req.json()
    from utils.preferences import get_prefs
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
