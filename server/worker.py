"""LangGraph 管线包装 — 运行 pipeline 并发射 SSE 事件到 asyncio.Queue。"""
import asyncio
import os
import traceback
import httpx
from config import config
from graph import app
from state.schema import WorkflowState
from agents.sdxl_enhancer import (
    public_run_single_pass,
    public_run_hires_pass,
    public_rewrite_prompt,
    _check_frame_quality,
    _create_grid_image,
)
from utils.preferences import get_prefs
from server.task_store import TaskRecord, update_task


def _get_output(node_state: dict, node_name: str) -> dict:
    """从 astream 返回的 dict 中提取节点的 output。"""
    node_io = node_state.get("node_io", {})
    return node_io.get(node_name, {}).get("output", {})


async def run_pipeline(
    user_input: str,
    task_id: str,
    event_queue: asyncio.Queue,
):
    """执行完整的生成管线，通过 event_queue 推送进度事件。"""
    state = WorkflowState(user_input=user_input)
    final_state = None  # 保存最后的状态 dict

    try:
        # ---- 节点 1: 场景扩写 ----
        await event_queue.put({
            "event": "progress",
            "data": {"node": "场景扩写", "status": "running", "progress": 0},
        })

        async for step in app.astream(state):
            node_name = list(step.keys())[0]
            node_state = step[node_name]
            final_state = node_state  # 每次更新

            if node_name == "text_expander":
                output = _get_output(node_state, "text_expander")
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
                output = _get_output(node_state, "coder_agent")
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
                output = _get_output(node_state, "blender_executor")
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

        # ---- 节点 4: AI 图像生成 (从最终 state dict 获取输出) ----
        enhancer_output = _get_output(final_state or {}, "sdxl_enhancer")
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
            # 网格图保存到 output/enhanced/（可被静态文件服务访问）
            import shutil
            grid_out = os.path.join(os.getcwd(), "output", "enhanced", f"grid_{task_id}.png")
            try:
                grid_path = _create_grid_image(all_paths, config.COMFYUI_INPUT_DIR, idx=0)
                if grid_path and os.path.isfile(grid_path):
                    os.makedirs(os.path.dirname(grid_out), exist_ok=True)
                    shutil.copy2(grid_path, grid_out)
                    grid_path = grid_out
            except Exception:
                grid_path = ""
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

    # 3. 构建 ComfyUI client，执行 SDXL 生成
    async with httpx.AsyncClient(timeout=config.COMFYUI_TIMEOUT) as client:
        depth_name = os.path.basename(depth_path) if depth_path else ""
        frame_name = os.path.basename(task.frame_image_url or "") if task.frame_image_url else ""

        result = await public_run_single_pass(
            client=client,
            image_filename=frame_name,
            depth_filename=depth_name,
            positive_prompt=new_prompt,
            negative_prompt=task.sdxl_negative_prompt or "",
            seed=seed,
            is_txt2img=not bool(depth_name),
            prefix=f"v{task.version + 1}",
        )

        if not result:
            await event_queue.put({
                "event": "error", "data": {"message": "SDXL 生成失败"},
            })
            return

        # 4. Hires Fix (可选)
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
    task.interactions.append({
        "action": action, "description": description, "new_prompt": new_prompt,
    })
    update_task(
        task_id, final_image_url=new_url, version=task.version,
        interactions=task.interactions,
    )

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
    # 先转为绝对路径，处理 ./ 等相对路径
    p = os.path.abspath(fs_path).replace("\\", "/")
    cwd = os.getcwd().replace("\\", "/")
    if p.startswith(cwd):
        p = p[len(cwd):]
        if not p.startswith("/"):
            p = "/" + p
    return p
