"""ComfyUI HTTP 客户端 — 提交 prompt、轮询结果、下载图片。

提供:
  - _run_single_pass(): 提交一次 ComfyUI 任务并轮询结果
  - _poll_image(): 轮询 ComfyUI 历史记录并下载输出图片
  - _check_controlnet_available(): 检测 ControlNet 模型是否可用
  - _run_hires_pass(): Hires Fix（PIL 放大 + img2img 低 denoise 精修）
  - public_run_single_pass() / public_run_hires_pass(): 供 server/worker.py 调用的公开包装
"""

import os
import time
import asyncio
from typing import Optional
import httpx
from PIL import Image
from config import config
from utils.helpers import ensure_dir
from .comfyui_workflows import (
    _build_txt2img_workflow,
    _build_hires_fix_workflow,
    _build_img2img_controlnet_workflow,
    _build_img2img_fallback_workflow,
    POLISH_STEPS,
)

# ── 调试工具 ──

def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


# ===========================
# ComfyUI 调用工具
# ===========================

async def _run_single_pass(
    client: httpx.AsyncClient,
    image_filename: str,
    depth_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    seed: int = 42,
    denoise: float = 0.65,
    cn_strength: float = 0.25,
    steps: int = 24,
    cfg: float = 6.5,
    prefix: str = "enhanced",
    use_cn: bool = True,
    is_txt2img: bool = False,
    lora_filename: str = "",
) -> Optional[str]:
    """提交一次 ComfyUI 任务并轮询结果。返回输出图片路径。

    is_txt2img=True: EmptyLatentImage 起点
    is_txt2img=False + use_cn=True: img2img + ControlNet
    use_cn=False: 纯 img2img 回退
    """

    if is_txt2img:
        workflow = _build_txt2img_workflow(
            depth_filename=depth_filename,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            controlnet_model=config.COMFYUI_CONTROLNET_DEPTH,
            seed=seed,
            cn_strength=cn_strength,
            steps=steps,
            cfg=cfg,
            prefix=prefix,
            lora_filename=lora_filename,
            lora_weight=config.ANIME_LORA_WEIGHT,
        )
    elif use_cn:
        workflow = _build_img2img_controlnet_workflow(
            image_filename=image_filename,
            depth_filename=depth_filename,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            controlnet_model=config.COMFYUI_CONTROLNET_DEPTH,
            seed=seed,
            denoise=denoise,
            cn_strength=cn_strength,
            steps=steps,
            cfg=cfg,
            prefix=prefix,
        )
    else:
        workflow = _build_img2img_fallback_workflow(
            image_filename=image_filename,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            denoise=min(denoise, 0.35),
        )

    _mode = "txt2img" if is_txt2img else ("img2img+CN" if use_cn else "img2img")
    print(f"      [DEBUG {_ts()}] ComfyUI submit: {_mode} seed={seed} prefix={prefix}")
    try:
        resp = await client.post(
            f"{config.COMFYUI_BASE_URL}/prompt",
            json={"prompt": workflow},
        )
        if resp.status_code != 200:
            print(f"      ComfyUI 提交失败: {resp.status_code}")
            return None
        result = resp.json()
    except httpx.HTTPError as e:
        print(f"      ComfyUI HTTP 错误: {e}")
        return None

    prompt_id = result.get("prompt_id", "")
    if not prompt_id:
        print(f"      无 prompt_id")
        return None

    print(f"      [DEBUG {_ts()}] ComfyUI prompt_id={prompt_id}, 开始轮询...")
    result_path = await _poll_image(client, prompt_id, prefix)
    if result_path:
        print(f"      [DEBUG {_ts()}] ComfyUI DONE: {os.path.basename(result_path)}")
    else:
        print(f"      [DEBUG {_ts()}] ComfyUI TIMEOUT/FAIL")
    return result_path


async def _poll_image(
    client: httpx.AsyncClient,
    prompt_id: str,
    prefix: str = "enhanced",
) -> Optional[str]:
    """轮询 ComfyUI 任务并下载输出图片。"""
    history_url = f"{config.COMFYUI_BASE_URL}/history/{prompt_id}"
    start = time.time()
    last_log = start

    while time.time() - start < config.COMFYUI_TIMEOUT:
        await asyncio.sleep(config.COMFYUI_POLL_INTERVAL)

        # 每 15 秒输出一次轮询状态
        now = time.time()
        if now - last_log >= 15:
            print(f"      [DEBUG {_ts()}] poll... ({now - start:.0f}s elapsed)")
            last_log = now

        try:
            resp = await client.get(history_url)
            if resp.status_code != 200:
                continue
            history = resp.json()
        except httpx.HTTPError:
            continue

        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            for node_out in outputs.values():
                for media in node_out.get("images", []):
                    filename = media.get("filename", "")
                    subfolder = media.get("subfolder", "")
                    ftype = media.get("type", "output")
                    try:
                        r = await client.get(
                            f"{config.COMFYUI_BASE_URL}/view",
                            params={"filename": filename, "subfolder": subfolder, "type": ftype},
                        )
                        r.raise_for_status()
                        local = os.path.join(
                            ensure_dir(os.path.join(config.OUTPUT_DIR, "enhanced")),
                            f"{prefix}_{filename}",
                        )
                        with open(local, "wb") as f:
                            f.write(r.content)
                        return local
                    except httpx.HTTPError:
                        continue

    return None


def _check_controlnet_available() -> bool:
    """检测 ComfyUI 中是否加载了 ControlNet Depth 模型。"""
    model = config.COMFYUI_CONTROLNET_DEPTH
    if not model:
        return False
    try:
        import httpx as _httpx
        resp = _httpx.get(f"{config.COMFYUI_BASE_URL}/object_info", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            loader = data.get("ControlNetLoader", {})
            models = loader.get("input", {}).get("required", {}).get("control_net_name", [[]])[0]
            ok = model in models
            print(f"[NODE IO] ControlNet 模型 '{model}': {'可用' if ok else f'未找到，可用: {models}'}")
            return ok
    except Exception:
        pass
    return False


# ===========================
# Hires Fix
# ===========================

async def _run_hires_pass(
    client: httpx.AsyncClient,
    image_path: str,
    positive_prompt: str,
    negative_prompt: str,
    seed: int = 42,
    denoise: float = 0.40,
    steps: int = 20,
    prefix: str = "hires",
    comfyui_input_dir: str = "",
) -> Optional[str]:
    """Hires Fix: PIL Lanczos 放大图像 → img2img 低 denoise 精修。"""
    # PIL 放大
    img = Image.open(image_path)
    w, h = img.size
    new_w, new_h = int(w * config.ANIME_HIRES_FACTOR), int(h * config.ANIME_HIRES_FACTOR)
    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

    # 保存到 ComfyUI 输入目录
    hires_input_name = f"hires_input_{prefix}.png"
    hires_input_path = os.path.join(comfyui_input_dir, hires_input_name)
    upscaled.save(hires_input_path)
    print(f"    PIL Lanczos: {w}×{h} → {new_w}×{new_h}, {hires_input_name}")

    # 提交 hires fix workflow
    workflow = _build_hires_fix_workflow(
        image_filename=hires_input_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        denoise=denoise,
        steps=steps,
        prefix=prefix,
    )

    try:
        resp = await client.post(
            f"{config.COMFYUI_BASE_URL}/prompt",
            json={"prompt": workflow},
        )
        if resp.status_code != 200:
            print(f"      Hires Fix 提交失败: {resp.status_code}")
            return None
        result = resp.json()
    except httpx.HTTPError as e:
        print(f"      Hires Fix HTTP 错误: {e}")
        return None

    prompt_id = result.get("prompt_id", "")
    if not prompt_id:
        return None

    return await _poll_image(client, prompt_id, prefix)


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
    denoise: float = 0.65,
    cn_strength = None,  # float or None: 默认使用 config 值
    prefix: str = "enhanced",
) -> Optional[str]:
    """公开包装：调用 _run_single_pass。"""
    if cn_strength is None:
        cn_strength = config.ANIME_DEPTH_CN_STRENGTH
    return await _run_single_pass(
        client=client,
        image_filename=image_filename,
        depth_filename=depth_filename,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        denoise=denoise,
        cn_strength=cn_strength,
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
