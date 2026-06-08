"""LangGraph 管线包装 — 运行 pipeline 并发射 SSE 事件到 asyncio.Queue。"""
import asyncio
import os
import shutil
import time
import httpx
from config import config
from graph import app
from state.schema import WorkflowState
from agents.sdxl_enhancer import (
    public_run_single_pass,
    public_run_hires_pass,
    public_rewrite_prompt,
    _create_grid_image,
    _blur_depth_full,
    POLISH_ENABLED,
    POLISH_DENOISE,
    POLISH_CN_STRENGTH,
)
from utils.preferences import get_prefs
from server.task_store import update_task

# ── 调试工具 ──

def _ts() -> str:
    """返回当前时间戳字符串，用于调试日志。"""
    return time.strftime("%H:%M:%S", time.localtime())

def _debug(msg: str):
    """统一调试日志输出。"""
    print(f"[DEBUG {_ts()}] {msg}")


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
    _debug(f"[PKG] START task={task_id[:8]} input={user_input[:50]}...")
    state = WorkflowState(user_input=user_input)
    final_state = None  # 保存最后的状态 dict

    try:
        # ---- 节点 1: 场景扩写 ----
        _debug("[PKG] → 场景扩写 running")
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
                _debug(f"[PKG] 场景扩写 DONE ({len(expanded)} 字符)")
                update_task(task_id, expanded_text=expanded)
                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "场景扩写", "status": "done", "progress": 20,
                        "preview": expanded[:150],
                    },
                })
                await event_queue.put({
                    "event": "progress",
                    "data": {"node": "SDXL提示词生成", "status": "running", "progress": 25},
                })

            elif node_name == "sdxl_prompt_gen":
                output = _get_output(node_state, "sdxl_prompt_gen")
                prompt = output.get("sdxl_prompt", "")
                neg = output.get("sdxl_negative_prompt", "")
                _debug(f"[PKG] SDXL提示词生成 DONE ({len(prompt)}字符)")
                update_task(task_id, sdxl_prompt=prompt, sdxl_negative_prompt=neg)
                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "SDXL提示词生成", "status": "done", "progress": 35,
                        "preview": prompt[:200],
                    },
                })
                await event_queue.put({
                    "event": "progress",
                    "data": {"node": "Blender脚本生成", "status": "running", "progress": 40},
                })

            elif node_name == "coder_agent":
                output = _get_output(node_state, "coder_agent")
                script = output.get("blender_script", "")
                scene = output.get("scene_description", "")
                _debug(f"[PKG] Blender脚本生成 DONE (script={len(script)}字符)")
                update_task(task_id, blender_script=script)
                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "Blender脚本生成", "status": "done", "progress": 55,
                        "preview": scene[:150],
                    },
                })
                await event_queue.put({
                    "event": "progress",
                    "data": {"node": "场景渲染", "status": "running", "progress": 60},
                })

            elif node_name == "blender_executor":
                output = _get_output(node_state, "blender_executor")
                depth = output.get("depth_path", "")
                frame = output.get("frame_path", "")
                err = output.get("blender_error")

                if err:
                    # 不 return！LangGraph 会自动重试（条件边 → coder_agent → blender_executor）
                    retry_count = output.get("retry_count", 0)
                    _debug(f"[PKG] 场景渲染 ERROR (重试{retry_count}/{config.BLENDER_MAX_RETRIES}): {err[:100]}")
                    await event_queue.put({
                        "event": "progress",
                        "data": {
                            "node": "场景渲染", "status": "running",
                            "message": f"脚本出错，自动修复中... (重试 {retry_count}/{config.BLENDER_MAX_RETRIES})",
                            "progress": 50,
                        },
                    })
                    continue  # 继续处理 stream 中的重试

                # 转为相对 URL
                depth_url = _to_url(depth) if depth else ""
                frame_url = _to_url(frame) if frame else ""
                _debug(f"[PKG] 场景渲染 DONE depth={depth_url or '(无)'}")
                update_task(task_id, depth_image_url=depth_url, frame_image_url=frame_url)

                await event_queue.put({
                    "event": "progress",
                    "data": {
                        "node": "场景渲染", "status": "done", "progress": 75,
                        "preview_url": depth_url,
                    },
                })

        # ---- 检查 Blender 是否最终失败 ----
        blender_out = _get_output(final_state or {}, "blender_executor")
        if blender_out.get("blender_error"):
            err = blender_out["blender_error"]
            _debug(f"[PKG] 场景渲染 FAILED (重试耗尽): {err[:100]}")
            update_task(task_id, error_message=err, status="error")
            await event_queue.put({
                "event": "error",
                "data": {"node": "场景渲染", "message": f"重试{config.BLENDER_MAX_RETRIES}次后仍失败: {err}"},
            })
            return

        # ---- 节点 4: AI 图像生成 (从最终 state dict 获取输出) ----
        _debug("[PKG] → AI 图像生成 running")
        await event_queue.put({
            "event": "progress",
            "data": {"node": "AI 图像生成", "status": "running", "progress": 85},
        })

        enhancer_output = _get_output(final_state or {}, "sdxl_enhancer")
        all_paths = enhancer_output.get("final_image_paths", [])
        final_image = enhancer_output.get("final_image_path", "")

        _debug(f"[PKG] AI 图像生成 output: paths={len(all_paths)}, image={bool(final_image)}")

        if not final_image and not all_paths:
            _debug("[PKG] AI 图像生成 ERROR: 无图片输出")
            await event_queue.put({
                "event": "error",
                "data": {"node": "AI 图像生成", "message": "SDXL 未生成图片"},
            })
            return

        # 构建 URL — 复制到任务专属文件名，避免不同任务覆盖
        enhanced_dir = os.path.join(os.getcwd(), "output", "enhanced")
        os.makedirs(enhanced_dir, exist_ok=True)

        if all_paths:
            # 复制最终图片到任务专属路径
            final_out = os.path.join(enhanced_dir, f"final_{task_id}.png")
            try:
                src = all_paths[0]
                if os.path.isfile(src):
                    shutil.copy2(src, final_out)
                    final_urls = [_to_url(final_out)]
                else:
                    final_urls = [_to_url(p) for p in all_paths]
            except Exception:
                final_urls = [_to_url(p) for p in all_paths]

            # 网格图保存到 output/enhanced/
            grid_url = ""
            grid_out = os.path.join(enhanced_dir, f"grid_{task_id}.png")
            try:
                grid_path = _create_grid_image(all_paths, config.COMFYUI_INPUT_DIR, idx=0)
                if grid_path and os.path.isfile(grid_path):
                    shutil.copy2(grid_path, grid_out)
                    grid_url = _to_url(grid_out)
            except Exception:
                pass
            update_task(task_id, final_image_url=final_urls[0] if final_urls else "",
                        grid_image_url=grid_url)
        else:
            final_out = os.path.join(enhanced_dir, f"final_{task_id}.png")
            try:
                if os.path.isfile(final_image):
                    shutil.copy2(final_image, final_out)
                    final_urls = [_to_url(final_out)]
                else:
                    final_urls = [_to_url(final_image)]
            except Exception:
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
        _debug(f"[PKG] → 交互菜单 ({len(final_urls)} URLs)")
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
        import traceback
        tb = traceback.format_exc()
        _debug(f"[PKG] EXCEPTION: {e}")
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
    """交互重生成：场景变化 → 完整管线，其他 → SDXL only。"""
    _debug(f"[INTERACT] START task={task_id[:8]} action={action} desc={description[:50]}...")
    from server.task_store import get_task
    task = get_task(task_id)
    if not task:
        _debug("[INTERACT] ERROR: 任务不存在")
        await event_queue.put({
            "event": "error", "data": {"message": "任务不存在"},
        })
        return

    # 换场景必须重跑 Blender（3D 几何体变化）
    if action == "scene":
        _debug("[INTERACT] → 场景变化，重跑完整管线")
        new_input = await _rewrite_scene_description(task.user_input or "", description)
        task.version += 1
        task.interactions.append({"action": action, "description": description, "new_scene": new_input})
        update_task(task_id, version=task.version, interactions=task.interactions)
        await run_pipeline(new_input, task_id, event_queue)
        return

    category_map = {
        "lighting": "光线", "scene": "场景", "character": "角色",
        "pose": "姿态", "style": "风格",
    }
    category = category_map.get(action, action)

    # 1. 用 LLM 改写 prompt
    _debug(f"[INTERACT] → 改写prompt (category={category})")
    await event_queue.put({
        "event": "progress",
        "data": {"node": "AI 图像生成", "status": "running", "progress": 80},
    })

    # 注入用户偏好到改写上下文
    prefs = get_prefs(config.USER_PREFS_PATH)
    pref_context = prefs.get_injection_text()

    new_prompt = await public_rewrite_prompt(
        task.sdxl_prompt or "", description, category, pref_context,
    )
    _debug(f"[INTERACT] prompt改写完成: len={len(new_prompt)} old_len={len(task.sdxl_prompt or '')}")
    update_task(task_id, sdxl_prompt=new_prompt)

    # 2. 生成新 seed
    import random
    seed = random.randint(1, 2_147_483_647)
    _debug(f"[INTERACT] seed={seed}")

    # 3. 构建 ComfyUI client，执行 SDXL 生成
    async with httpx.AsyncClient(timeout=config.COMFYUI_TIMEOUT) as client:
        # 模糊深度图: 与初始生成一致，radius=25.0
        depth_name = ""
        if depth_path and os.path.isfile(depth_path):
            _debug(f"[INTERACT] 深度图模糊: {depth_path}")
            blurred = _blur_depth_full(depth_path, output_dir=config.COMFYUI_INPUT_DIR)
            depth_name = os.path.basename(blurred)
        else:
            _debug(f"[INTERACT] 无深度图 (path={depth_path}, exists={os.path.isfile(depth_path) if depth_path else 'N/A'})")

        # img2img 源图: 使用已生成的动漫图片（而非 Blender 3D 原始帧）
        comfyui_input = config.COMFYUI_INPUT_DIR
        final_img_name = ""
        if task.final_image_url:
            # URL 是相对路径如 /output/enhanced/xxx.png，需要拼接项目根目录
            url_path = task.final_image_url.lstrip("/")
            final_img_path = os.path.join(os.getcwd(), url_path)
            _debug(f"[INTERACT] 源图路径: {final_img_path} exists={os.path.isfile(final_img_path)}")
            if os.path.isfile(final_img_path):
                final_img_name = f"interact_src_{task_id}.png"
                shutil.copy2(final_img_path, os.path.join(comfyui_input, final_img_name))
                _debug(f"[INTERACT] 源图已复制: {final_img_name}")
        else:
            _debug("[INTERACT] WARNING: task.final_image_url 为空!")

        # 按操作分级的 denoise: 画质越高需要越高 denoise, 但角色一致性需要越低 denoise
        DENOISE_MAP = {
            "lighting": 0.80,    # 全局色彩变化，高自由度
            "character": 0.60,   # 保留面部特征，只改特定属性
            "pose": 0.85,        # 姿态变化需要最大创作自由
            "style": 0.75,       # 风格变化影响全图
        }
        denoise = DENOISE_MAP.get(action, 0.70)
        _debug(f"[INTERACT] ComfyUI: img2img denoise={denoise} depth={bool(depth_name)} src={bool(final_img_name)}")

        result = await public_run_single_pass(
            client=client,
            image_filename=final_img_name,
            depth_filename=depth_name,
            positive_prompt=new_prompt,
            negative_prompt=task.sdxl_negative_prompt or "",
            seed=seed,
            is_txt2img=False,       # img2img: 从动漫图出发微调
            denoise=denoise,        # 按操作分级
            cn_strength=0.25,       # 与初始生成一致
            prefix=f"v{task.version + 1}",
        )

        if not result:
            _debug("[INTERACT] ERROR: SDXL 生成返回 None")
            await event_queue.put({
                "event": "error", "data": {"message": "SDXL 生成失败"},
            })
            return

        # 4. Hires Fix (交互时跳过 — 源图已是高清，且 ComfyUI 耗时太长)
        # 5. Polish 打磨 (交互时跳过 — 微调角色/光线等不需要打磨)

    # 复制到任务专属路径，避免不同任务覆盖
    final_out = os.path.join(os.getcwd(), "output", "enhanced", f"final_{task_id}_v{task.version + 1}.png")
    os.makedirs(os.path.dirname(final_out), exist_ok=True)
    shutil.copy2(result, final_out)
    new_url = _to_url(final_out)
    task.version += 1
    task.interactions.append({
        "action": action, "description": description, "new_prompt": new_prompt,
    })
    update_task(
        task_id, final_image_url=new_url, version=task.version,
        interactions=task.interactions,
    )

    _debug(f"[INTERACT] DONE → interactive menu (v{task.version}) image={new_url}")
    await event_queue.put({
        "event": "interactive",
        "data": {
            "type": "menu", "message": "调整完成！", "image_url": new_url,
            "task_id": task_id,
        },
    })


async def run_dislike(
    task_id: str,
    reason: str,
    event_queue: asyncio.Queue,
):
    """用户不喜欢：LLM 分析原因 → 记录偏好 → 改写提示词 → 重新生成。"""
    from server.task_store import get_task
    task = get_task(task_id)
    if not task:
        await event_queue.put({
            "event": "error", "data": {"message": "任务不存在"},
        })
        return

    # 1. 用 LLM 分析用户反馈，提取不喜欢的标签
    _debug(f"[DISLIKE] START reason={reason[:80]}...")
    disliked_tags = await _analyze_dislike_reason(
        task.sdxl_prompt or "", reason,
    )

    # 2. 记录到偏好
    prefs = get_prefs(config.USER_PREFS_PATH)
    prefs.add_disliked(disliked_tags)
    prefs.add_history({
        "input": task.user_input or "",
        "final_prompt": task.sdxl_prompt[:200],
        "image": task.final_image_url or "",
        "disliked": True,
        "reason": reason,
        "disliked_tags": disliked_tags,
    })
    prefs.save()
    _debug(f"[DISLIKE] 已记录不喜欢标签: {disliked_tags}")

    # 3. 改写提示词：根据用户反馈改善
    await event_queue.put({
        "event": "progress",
        "data": {"node": "AI 图像生成", "status": "running", "progress": 80},
    })

    # 注入偏好（包含刚记录的不喜欢标签）
    pref_context = prefs.get_injection_text()
    dislike_context = f"用户不喜欢当前图片，原因: {reason}。请避免以下标签: {', '.join(disliked_tags)}" if disliked_tags else f"用户不喜欢当前图片，原因: {reason}。请改善。"
    combined_context = f"{pref_context}\n\n{dislike_context}" if pref_context else dislike_context

    new_prompt = await public_rewrite_prompt(
        task.sdxl_prompt or "", reason, "不喜欢改进", combined_context,
    )
    _debug(f"[DISLIKE] prompt改写完成: len={len(new_prompt)}")
    update_task(task_id, sdxl_prompt=new_prompt)

    # 4. 重新生成（img2img，与 interact 类似）
    import random
    seed = random.randint(1, 2_147_483_647)

    async with httpx.AsyncClient(timeout=config.COMFYUI_TIMEOUT) as client:
        # 深度图
        depth_name = ""
        from server.task_store import get_task as _get_task
        t = _get_task(task_id)
        if t:
            depth_path = t.depth_image_url
            if depth_path:
                depth_abs = os.path.join(os.getcwd(), depth_path.lstrip("/"))
                if os.path.isfile(depth_abs):
                    blurred = _blur_depth_full(depth_abs, output_dir=config.COMFYUI_INPUT_DIR)
                    depth_name = os.path.basename(blurred)

        # 源图
        src_name = ""
        if t and t.final_image_url:
            src_path = os.path.join(os.getcwd(), t.final_image_url.lstrip("/"))
            if os.path.isfile(src_path):
                src_name = f"dislike_src_{task_id}.png"
                shutil.copy2(src_path, os.path.join(config.COMFYUI_INPUT_DIR, src_name))

        _debug(f"[DISLIKE] ComfyUI: img2img denoise=0.7 seed={seed}")

        result = await public_run_single_pass(
            client=client,
            image_filename=src_name,
            depth_filename=depth_name,
            positive_prompt=new_prompt,
            negative_prompt=task.sdxl_negative_prompt or "",
            seed=seed,
            is_txt2img=False,
            denoise=0.70,
            cn_strength=0.25,
            prefix=f"dislike_v{task.version + 1}",
        )

        if not result:
            _debug("[DISLIKE] ERROR: SDXL 生成失败")
            await event_queue.put({
                "event": "error", "data": {"message": "SDXL 生成失败"},
            })
            return

        # Hires Fix 跳过 — 不喜欢重新生成同 interact，源图已是高清

    # 保存结果
    final_out = os.path.join(os.getcwd(), "output", "enhanced", f"final_{task_id}_dislike.png")
    os.makedirs(os.path.dirname(final_out), exist_ok=True)
    shutil.copy2(result, final_out)
    new_url = _to_url(final_out)

    task.version += 1
    task.interactions.append({
        "action": "dislike", "description": reason, "new_prompt": new_prompt,
        "disliked_tags": disliked_tags,
    })
    update_task(task_id, final_image_url=new_url, version=task.version,
                interactions=task.interactions)

    _debug(f"[DISLIKE] DONE → 新图片: {new_url}")
    await event_queue.put({
        "event": "interactive",
        "data": {
            "type": "menu", "message": f"已根据反馈重新生成 (避免: {', '.join(disliked_tags[:3])})",
            "image_url": new_url, "task_id": task_id,
        },
    })


async def _analyze_dislike_reason(prompt: str, reason: str) -> list[str]:
    """用 LLM 分析用户不喜欢的原因，提取对应的 Danbooru 标签。"""
    from utils.helpers import get_llm
    system = f"""你是 Danbooru 标签分析专家。用户不喜欢当前生成的图片，请从提示词中找出用户可能不喜欢的标签。

用户反馈: {reason}

当前提示词: {prompt}

请输出用户可能不喜欢的标签（每行一个），只输出标签名，不要解释。最多输出 5 个标签。
如果用户反馈不涉及具体标签，输出空。"""
    try:
        llm = get_llm(temperature=0.1)
        response = await llm.ainvoke([("system", system), ("user", reason)])
        tags = [t.strip().rstrip(",") for t in response.content.strip().split("\n") if t.strip()]
        return [t for t in tags if t and not t.startswith("#")][:5]
    except Exception as e:
        print(f"[WARN] 不喜欢分析异常: {e}")
        return []


async def run_done(task_id: str):
    """用户满意保存：持久化偏好。"""
    from server.task_store import get_task
    task = get_task(task_id)
    if not task:
        return

    update_task(task_id, status="done")

    # 记录偏好 + 历史
    if task.sdxl_prompt:
        prefs = get_prefs(config.USER_PREFS_PATH)
        await prefs.learn_from_prompt_async(task.sdxl_prompt)
        prefs.add_history({
            "input": task.user_input or "",
            "final_prompt": task.sdxl_prompt[:200],
            "image": task.final_image_url or "",
        })
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


async def _rewrite_scene_description(original_input: str, scene_request: str) -> str:
    """用 LLM 将场景修改融入原始描述，返回新的用户输入。"""
    from utils.helpers import get_llm
    system = """你是一个场景描述改写助手。用户想改变画面中的场景/环境，你需要把新的场景融入原始描述中。

规则：
1. 保持人物、动作、情绪、光线等描述不变
2. 只改变场景/环境相关的描述
3. 输出 200-400 字的中文场景描述
4. 直接输出改写后的文本，不要任何解释"""
    try:
        llm = get_llm(temperature=0.5)
        response = await llm.ainvoke([
            ("system", system),
            ("user", f"原始描述：{original_input}\n\n新场景：{scene_request}\n\n请改写："),
        ])
        return response.content.strip() or original_input
    except Exception:
        return f"{original_input}，{scene_request}"
