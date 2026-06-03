"""Node 4: SDXL Enhancer — txt2img + ControlNet Depth + FaceDetailer + HandDetailer + 可选打磨。

核心 Pipeline:
    1. 深度图分区域柔化（人物区模糊 → CN 弱约束，环境区清晰 → CN 强约束）
    2. txt2img + ControlNet Depth (CN=0.45, end=0.80)
    3. FaceDetailer 面部增强（YOLO 人脸检测 → 局部高分辨率重绘 → 贴回原图）
    4. HandDetailer 手部增强（YOLO 手部检测 → 局部高分辨率重绘 → 贴回原图）
    5. 可选 img2img 打磨 (denoise=0.15) 统一光影

输入 JSON: SDXLEnhancerInput
输出 JSON: SDXLEnhancerOutput (含 final_image_path)
"""

import json
import time
import os
import shutil
import asyncio
from typing import Optional
import httpx
from PIL import Image, ImageFilter
import numpy as np
from state.schema import WorkflowState
from state.models import SDXLEnhancerInput, SDXLEnhancerOutput
from config import config
from utils.helpers import ensure_dir


# ===========================
# 生成配置
# ===========================

# 可选打磨: img2img 低 denoise 统一画面 (动漫降低强度)
POLISH_ENABLED = True
POLISH_DENOISE = 0.10
POLISH_CN_STRENGTH = 0.20
POLISH_STEPS = 15

# Refiner: 动漫模型无 refiner，默认关闭（写实模型可手动开启）
REFINER_ENABLED = False
REFINER_DENOISE = 0.25


# ===========================
# ComfyUI Workflow 构建
# ===========================

def _build_txt2img_workflow(
    depth_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    controlnet_model: str,
    seed: int = 42,
    cn_strength: float = 0.25,
    steps: int = 24,
    cfg: float = 6.5,
    width: int = 1024,
    height: int = 1024,
    prefix: str = "generated",
    lora_filename: str = "",
    lora_weight: float = 0.75,
) -> dict:
    """动漫 txt2img + ControlNet Depth + LoRA。

    Pipeline:
      Checkpoint(Animagine XL) → [VAE Loader] → [LoRA] → CLIPTextEncode → Depth CN → KSampler → VAEDecode → SaveImage

    不再包含 OpenPose CN / FaceDetailer / HandDetailer。
    """
    wf = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": config.COMFYUI_CHECKPOINT},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": depth_filename},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
    }

    # VAE: 独立 VAE Loader（如果配置了动漫 VAE 如 kl-f8-anime2.vae.pt）
    if config.COMFYUI_VAE:
        wf["vae_loader"] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": config.COMFYUI_VAE},
        }
        vae_ref = ["vae_loader", 0]
    else:
        vae_ref = ["1", 2]  # checkpoint 内置 VAE

    # LoRA Loader (if Shinkai LoRA available)
    model_ref = ["1", 0]
    clip_ref = ["1", 1]
    if lora_filename:
        wf["lora"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": lora_filename,
                "strength_model": lora_weight,
                "strength_clip": lora_weight,
            },
        }
        model_ref = ["lora", 0]
        clip_ref = ["lora", 1]
        # Update CLIPTextEncode to use LoRA-modified CLIP
        wf["3"]["inputs"]["clip"] = clip_ref
        wf["4"]["inputs"]["clip"] = clip_ref

    # Depth ControlNet
    wf["6"] = {
        "class_type": "ControlNetLoader",
        "inputs": {"control_net_name": controlnet_model},
    }
    wf["7"] = {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": {
            "positive": ["3", 0],
            "negative": ["4", 0],
            "control_net": ["6", 0],
            "image": ["2", 0],
            "strength": cn_strength,
            "start_percent": 0.0,
            "end_percent": 0.55,  # 动漫模型对 CN 敏感度低，早停
        },
    }

    wf["8"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": config.ANIME_SAMPLER,
            "scheduler": config.ANIME_SCHEDULER,
            "denoise": 1.0,
            "positive": ["7", 0],
            "negative": ["7", 1],
            "latent_image": ["5", 0],
        },
    }
    wf["9"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["8", 0], "vae": vae_ref},
    }
    wf["10"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["9", 0], "filename_prefix": prefix},
    }

    return wf


def _build_hires_fix_workflow(
    image_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    seed: int = 42,
    denoise: float = 0.40,
    steps: int = 20,
    cfg: float = 5.0,
    prefix: str = "hires",
) -> dict:
    """Hires Fix: 像素空间 upscale 后 img2img 低 denoise 精修。

    无 ControlNet——低 denoise 足够保护结构。独立 VAE 支持。
    """
    wf = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": config.COMFYUI_CHECKPOINT},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "5": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["2", 0], "vae": ["1", 2]},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": config.ANIME_SAMPLER,
                "scheduler": config.ANIME_SCHEDULER,
                "denoise": denoise,
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
    }
    # VAE
    if config.COMFYUI_VAE:
        wf["vae_loader"] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": config.COMFYUI_VAE},
        }
        vae_ref = ["vae_loader", 0]
        wf["5"]["inputs"]["vae"] = vae_ref
    else:
        vae_ref = ["1", 2]

    wf["7"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["6", 0], "vae": vae_ref},
    }
    wf["8"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["7", 0], "filename_prefix": prefix},
    }
    return wf


def _build_img2img_controlnet_workflow(
    image_filename: str,
    depth_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    controlnet_model: str,
    seed: int = 42,
    denoise: float = 0.12,
    cn_strength: float = 0.20,
    steps: int = 15,
    cfg: float = 6.5,
    prefix: str = "polish",
) -> dict:
    """img2img + ControlNet Depth: 低 denoise 打磨已有的生成结果。(动漫简化版)"""
    wf = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": config.COMFYUI_CHECKPOINT},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        "3": {
            "class_type": "LoadImage",
            "inputs": {"image": depth_filename},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
    }
    # VAE
    if config.COMFYUI_VAE:
        wf["vae_loader"] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": config.COMFYUI_VAE},
        }
        _vae_ref = ["vae_loader", 0]
    else:
        _vae_ref = ["1", 2]
    wf["6"] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["2", 0], "vae": _vae_ref},
    }
    wf["7"] = {
        "class_type": "ControlNetLoader",
        "inputs": {"control_net_name": controlnet_model},
    }
    wf["8"] = {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": {
            "positive": ["4", 0],
            "negative": ["5", 0],
            "control_net": ["7", 0],
            "image": ["3", 0],
            "strength": cn_strength,
            "start_percent": 0.0,
            "end_percent": 0.55,
        },
    }
    wf["9"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["1", 0],
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": config.ANIME_SAMPLER,
            "scheduler": config.ANIME_SCHEDULER,
            "denoise": denoise,
            "positive": ["8", 0],
            "negative": ["8", 1],
            "latent_image": ["6", 0],
        },
    }
    wf["10"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["9", 0], "vae": _vae_ref},
    }
    wf["11"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["10", 0], "filename_prefix": prefix},
    }
    return wf


def _build_img2img_fallback_workflow(
    image_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    seed: int = 42,
    denoise: float = 0.30,
) -> dict:
    """回退: 无 ControlNet 时的纯 img2img（低 denoise 保护结构）。"""
    vae_ref = ["vae_loader", 0] if config.COMFYUI_VAE else ["1", 2]
    wf = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": config.COMFYUI_CHECKPOINT},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "5": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["2", 0], "vae": vae_ref},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": 20,
                "cfg": 5.0,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": denoise,
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": vae_ref},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "fallback"},
        },
    }
    if config.COMFYUI_VAE:
        wf["vae_loader"] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": config.COMFYUI_VAE},
        }
    return wf


def _build_refiner_workflow(
    image_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    refiner_checkpoint: str,
    seed: int = 42,
    denoise: float = 0.25,
    prefix: str = "refined",
) -> dict:
    """SDXL Refiner: img2img 细节增强（SDXL 原生的两阶段生成第2阶段）。"""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": refiner_checkpoint},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "5": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["2", 0], "vae": ["1", 2]},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": 10,
                "cfg": 5.0,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": denoise,
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": prefix},
        },
    }


# ===========================
# 深度图分区域柔化
# ===========================

def _blur_depth_full(
    depth_path: str,
    output_dir: str,
    blur_radius: float = 25.0,
    idx: int = 1,
) -> str:
    """全图高斯模糊深度图，保留空间布局信息但消除几何体细节约束。

    深度图包含人物 + 环境。重度模糊后：
    - 环境结构（墙壁/地板/家具）保留大致位置 → 弱空间约束
    - 人物 blob 变成柔和的"人形占位符" → 不限制 SDXL 画手/脸/衣服
    - 与 OpenPose 骨架配合：骨架提供精确姿态，软 blob 提供深度占位

    返回柔化后的深度图路径。
    """
    depth = Image.open(depth_path).convert('L')
    blurred = depth.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    out_path = os.path.join(output_dir, f"depth_soft_{idx:04d}.png")
    blurred.save(out_path)
    print(f"  深度图全图模糊: blur={blur_radius}px → depth_soft_{idx:04d}.png")
    return out_path


# ===========================
# 质量筛选 & 交互选择
# ===========================

def _check_frame_quality(image_path: str) -> dict:
    """规则式质量检测：过曝/过暗/低方差。

    返回 {"pass": bool, "overexposed": bool, "underexposed": bool, "low_variance": bool, "reason": str}
    """
    img = Image.open(image_path).convert('L')
    arr = np.array(img, dtype=np.float64)
    total = arr.size

    # 过曝: 像素值 > 250 占比超过阈值
    overexposed_pct = (arr > 250).sum() / total
    overexposed = overexposed_pct > config.ANIME_QUALITY_OVEREXPOSE_THRESHOLD

    # 过暗: 像素值 < 15 占比超过阈值
    underexposed_pct = (arr < 15).sum() / total
    underexposed = underexposed_pct > config.ANIME_QUALITY_UNDEREXPOSE_THRESHOLD

    # 低方差: 标准差 < 阈值（纯色或噪点图）
    std = arr.std()
    low_variance = std < config.ANIME_QUALITY_LOW_STD_THRESHOLD

    reasons = []
    if overexposed:
        reasons.append(f"过曝({overexposed_pct:.1%})")
    if underexposed:
        reasons.append(f"过暗({underexposed_pct:.1%})")
    if low_variance:
        reasons.append(f"低方差(std={std:.1f})")

    return {
        "pass": not (overexposed or underexposed or low_variance),
        "overexposed": overexposed,
        "underexposed": underexposed,
        "low_variance": low_variance,
        "reason": ", ".join(reasons) if reasons else "通过",
    }


def _create_grid_image(image_paths: list, output_dir: str, idx: int = 1) -> str:
    """将多张图片拼成 2×2 或 1×N 网格图，每格标注编号。

    返回网格图路径。
    """
    if not image_paths:
        return ""

    images = [Image.open(p).convert('RGB') for p in image_paths]
    n = len(images)

    # 确定网格布局
    if n == 1:
        cols, rows = 1, 1
    elif n == 2:
        cols, rows = 2, 1
    elif n <= 4:
        cols, rows = 2, 2
    else:
        cols = 3
        rows = (n + 2) // 3

    # 每格尺寸（取第一张图的尺寸）
    cell_w, cell_h = images[0].size
    grid_w = cell_w * cols
    grid_h = cell_h * rows

    grid = Image.new('RGB', (grid_w, grid_h), (30, 30, 30))
    from PIL import ImageDraw

    for i, img in enumerate(images):
        r, c = divmod(i, cols)
        x, y = c * cell_w, r * cell_h
        # 如果图片尺寸不一致，缩放
        if img.size != (cell_w, cell_h):
            img = img.resize((cell_w, cell_h), Image.LANCZOS)
        grid.paste(img, (x, y))

        # 标注编号
        draw = ImageDraw.Draw(grid)
        label = str(i + 1)
        bbox = draw.textbbox((0, 0), label)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # 半透明背景
        overlay = Image.new('RGBA', (tw + 20, th + 14), (0, 0, 0, 160))
        grid_rgba = grid.convert('RGBA')
        grid_rgba.paste(overlay, (x + 6, y + 6), overlay)
        grid = grid_rgba.convert('RGB')
        draw = ImageDraw.Draw(grid)
        draw.text((x + 16, y + 12), label, fill=(255, 255, 255))

    grid_path = os.path.join(output_dir, f"grid_{idx:04d}.png")
    grid.save(grid_path)
    print(f"  网格图: {grid_path} ({n} 张, {cols}×{rows})")
    return grid_path


def _interactive_select(valid_count: int, seeds: list) -> int:
    """CLI 交互：让用户选择最佳变体。非交互模式自动选第1张。

    返回选中索引 (0-based)。
    """
    # 非交互模式（管道/后台）→ 自动选第1张
    import sys
    if not sys.stdin.isatty():
        print(f"\n  [AUTO] 非交互模式，自动选择第1张 (seed={seeds[0] if seeds else '?'})")
        return 0

    print(f"\n{'─'*50}")
    print(f"  打开网格图查看 {valid_count} 张变体")
    print(f"  输入编号选择最佳图做 Hires Fix：")
    print()
    for i in range(valid_count):
        seed_str = f"seed={seeds[i]}" if i < len(seeds) else ""
        print(f"    [{i+1}]  {seed_str}")
    print(f"    [0]  全部跳过 Hires Fix（保留网格图中的最佳输出）")
    print()

    retries = 0
    while retries < 10:
        try:
            choice = input("  选择 (0-{}): ".format(valid_count)).strip()
            if choice == "0":
                print(f"  跳过 Hires Fix，输出第一张合格图")
                return 0
            idx = int(choice) - 1
            if 0 <= idx < valid_count:
                return idx
        except (ValueError, EOFError):
            pass
        retries += 1
        print(f"  无效输入，请输入 0-{valid_count} (剩余 {10 - retries} 次)")

    # 重试耗尽 → 自动选第1张
    print(f"  重试耗尽，自动选择第1张 (seed={seeds[0] if seeds else '?'})")
    return 0


# ===========================
# 主函数
# ===========================

async def sdxl_enhancer(state: WorkflowState) -> dict:
    """Node 4: 多 Seed txt2img → 质量筛选 → 2×2 网格图 → 交互选择 → Hires Fix → Polish。"""

    # ===== 1. 读取输入 =====
    blender_out = state.get_node_output("blender_executor")
    coder_out = state.get_node_output("coder_agent")

    frame_paths = blender_out.get("frame_paths", [])
    depth_paths = blender_out.get("depth_paths", [])
    if not frame_paths:
        single_frame = blender_out.get("frame_path", "")
        single_depth = blender_out.get("depth_path", "")
        if single_frame:
            frame_paths = [single_frame]
            depth_paths = [single_depth] if single_depth else [""]

    sdxl_prompt = coder_out.get("sdxl_prompt", "")
    sdxl_negative_prompt = coder_out.get(
        "sdxl_negative_prompt",
        # Animagine XL 官方 + 社区手部强化
        "lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, fewer digits, "
        "cropped, worst quality, low quality, low score, bad score, average score, normal quality, "
        "jpeg artifacts, signature, watermark, username, blurry, artist name, "
        "low quality face, deformed, bad face, ugly, "
        "mutated hands, poorly drawn hands, extra hands, multiple hands, three hands, "
        "mangled fingers, fused fingers, interlocked fingers, too many fingers, long fingers, "
        "blurry hands, blurry fingers, extra arms, multiple arms, fused arms, "
        "missing arms, extra limbs, mutated hands and fingers, "
        "incorrect hand anatomy, wrong hand position, mirrored hands, "
        "poorly drawn face, deformed, disfigured, asymmetric eyes, mismatched eyes, "
        "cross-eye, deformed eyes, missing pupils, blurry eyes, blurry face, "
        "plastic skin, oversaturated, overexposed, harsh lighting, "
        "western face, caucasian",
    )

    enhancer_input = SDXLEnhancerInput(
        frame_path=frame_paths[0] if frame_paths else "",
        depth_path=depth_paths[0] if depth_paths else "",
        sdxl_prompt=sdxl_prompt,
        sdxl_negative_prompt=sdxl_negative_prompt,
    )
    state.node_io["sdxl_enhancer"] = {
        "input": json.loads(enhancer_input.model_dump_json()),
    }

    print(f"\n[NODE IO] sdxl_enhancer (Anime): {len(frame_paths)} 帧")
    print(f"  prompt={sdxl_prompt[:150]}...")

    if state.error_message:
        return _fail(state, state.error_message)
    if not frame_paths:
        return _fail(state, "无颜色帧文件")

    # ===== 2. 检查 ControlNet =====
    use_controlnet = _check_controlnet_available()
    use_refiner = REFINER_ENABLED and _check_refiner_available()
    print(f"[NODE IO] Refiner: {'可用' if use_refiner else '跳过'}")
    comfyui_input_dir = config.COMFYUI_INPUT_DIR
    ensure_dir(comfyui_input_dir)
    output_enhanced_dir = ensure_dir(os.path.join(config.OUTPUT_DIR, "enhanced"))

    final_paths = []
    all_prompt_ids = []
    grid_path = ""

    async with httpx.AsyncClient(timeout=config.COMFYUI_TIMEOUT) as client:
        for idx, frame_path in enumerate(frame_paths):
            depth_path = depth_paths[idx] if idx < len(depth_paths) else ""

            print(f"\n{'='*50}")
            print(f"[NODE IO] 第 {idx+1}/{len(frame_paths)} 帧")
            print(f"  depth: {depth_path}")

            # ----- 回退：无 ControlNet -----
            if not use_controlnet or not depth_path or not os.path.exists(depth_path):
                frame_name = os.path.basename(frame_path)
                shutil.copy2(frame_path, os.path.join(comfyui_input_dir, frame_name))
                result = await _run_single_pass(
                    client, frame_name, "", sdxl_prompt, sdxl_negative_prompt,
                    seed=777 + idx, denoise=0.3, prefix="fallback",
                    use_cn=False,
                )
                if result:
                    final_path = os.path.join(output_enhanced_dir, f"final_{idx+1:04d}.png")
                    shutil.copy2(result, final_path)
                    final_paths.append(final_path)
                    all_prompt_ids.append(f"fallback_{idx+1}")
                continue

            # ----- 准备深度图 -----
            soft_depth_path = _blur_depth_full(
                depth_path, comfyui_input_dir,
                blur_radius=25.0, idx=idx + 1,
            )
            depth_name = os.path.basename(soft_depth_path)

            # LoRA
            lora_name = ""
            if config.COMFYUI_LORA_SHINKAI:
                lora_name = config.COMFYUI_LORA_SHINKAI
                print(f"  使用 LoRA: {lora_name}")
            else:
                print(f"  [INFO] 未配置 LoRA，使用 Animagine XL 默认风格")

            cn_strength = config.ANIME_DEPTH_CN_STRENGTH

            # ===============================================
            # Phase A: 多 Seed txt2img 生成
            # ===============================================
            n_seeds = config.ANIME_MULTI_SEED_COUNT
            base_seed = int(time.time() * 1000) % 1000000
            print(f"\n  [Phase A] 多 Seed 生成: {n_seeds} 个变体")
            variants = []

            for vi in range(n_seeds):
                seed = base_seed + vi * 777
                print(f"    [{vi+1}/{n_seeds}] seed={seed}")
                result = await _run_single_pass(
                    client, "", depth_name, sdxl_prompt, sdxl_negative_prompt,
                    seed=seed, denoise=1.0, cn_strength=cn_strength,
                    steps=config.ANIME_STEPS, cfg=config.ANIME_CFG, prefix=f"var{vi+1}",
                    use_cn=True, is_txt2img=True,
                    lora_filename=lora_name,
                )
                if result:
                    q = _check_frame_quality(result)
                    variants.append({"path": result, "seed": seed, "quality": q})
                    status = "✓" if q["pass"] else f"✗ {q['reason']}"
                    print(f"      {status}")
                else:
                    print(f"      ✗ 生成失败")

            if not variants:
                print(f"  [FAIL] 所有 Seed 生成均失败")
                continue

            # ===============================================
            # Phase B: 质量筛选
            # ===============================================
            valid = [v for v in variants if v["quality"]["pass"]]
            rejected = [v for v in variants if not v["quality"]["pass"]]
            print(f"\n  [Phase B] 质量筛选: {len(valid)}/{len(variants)} 通过")
            for r in rejected:
                print(f"    淘汰 seed={r['seed']}: {r['quality']['reason']}")

            if not valid:
                print(f"  [WARN] 全部淘汰，恢复所有变体")
                valid = variants

            # ===============================================
            # Phase C: 2×2 网格图
            # ===============================================
            print(f"\n  [Phase C] 生成网格图...")
            grid_path = _create_grid_image(
                [v["path"] for v in valid],
                output_enhanced_dir, idx=idx + 1,
            )

            # ===============================================
            # Phase D: 交互选择
            # ===============================================
            chosen_idx = _interactive_select(
                len(valid),
                [v["seed"] for v in valid],
            )
            selected = valid[chosen_idx]
            print(f"  选中 seed={selected['seed']}")

            # ===============================================
            # Phase E: Hires Fix
            # ===============================================
            if config.ANIME_HIRES_ENABLED:
                print(f"\n  [Phase E] Hires Fix: 1.5× → {int(1024*config.ANIME_HIRES_FACTOR)}×{int(1024*config.ANIME_HIRES_FACTOR)}, denoise={config.ANIME_HIRES_DENOISE}")
                hires_result = await _run_hires_pass(
                    client, selected["path"], sdxl_prompt, sdxl_negative_prompt,
                    seed=selected["seed"] + 1000,
                    denoise=config.ANIME_HIRES_DENOISE,
                    steps=config.ANIME_HIRES_STEPS,
                    prefix=f"hires_{idx+1}",
                    comfyui_input_dir=comfyui_input_dir,
                )
                if hires_result:
                    current_result = hires_result
                    print(f"    Hires Fix 完成: {current_result}")
                else:
                    print(f"    [WARN] Hires Fix 失败，使用原图")
                    current_result = selected["path"]
            else:
                current_result = selected["path"]

            # ===============================================
            # Phase F: 可选打磨
            # ===============================================
            if POLISH_ENABLED:
                polish_name = f"polish_input_{idx+1:04d}.png"
                shutil.copy2(current_result, os.path.join(comfyui_input_dir, polish_name))

                polish_seed = selected["seed"] + 500
                print(f"\n  [Phase F] 打磨: img2img, denoise={POLISH_DENOISE}, CN={POLISH_CN_STRENGTH}")
                polish_result = await _run_single_pass(
                    client, polish_name, depth_name, sdxl_prompt, sdxl_negative_prompt,
                    seed=polish_seed, denoise=POLISH_DENOISE, cn_strength=POLISH_CN_STRENGTH,
                    steps=POLISH_STEPS, prefix="polish",
                    use_cn=True, is_txt2img=False,
                    lora_filename=lora_name,
                )
                if polish_result:
                    current_result = polish_result
                else:
                    print(f"    [WARN] 打磨失败，使用之前结果")

            # ===== 可选 Refiner =====
            if use_refiner and current_result and os.path.isfile(current_result):
                refiner_name = f"refiner_input_{idx+1:04d}.png"
                shutil.copy2(current_result, os.path.join(comfyui_input_dir, refiner_name))
                refiner_seed = selected["seed"] + 800
                print(f"  Refiner: img2img 细节增强, denoise={REFINER_DENOISE}, seed={refiner_seed}")
                refiner_result = await _run_refiner_pass(
                    client, refiner_name, sdxl_prompt, sdxl_negative_prompt,
                    seed=refiner_seed, denoise=REFINER_DENOISE,
                )
                if refiner_result:
                    current_result = refiner_result
                else:
                    print(f"  [WARN] Refiner 失败，使用之前的输出结果")

            # 保存最终结果
            if current_result and os.path.isfile(current_result):
                final_path = os.path.join(output_enhanced_dir, f"final_{idx+1:04d}.png")
                shutil.copy2(current_result, final_path)
                final_paths.append(final_path)
                all_prompt_ids.append(f"frame{idx+1}")
                print(f"\n  [OK] 第 {idx+1} 帧完成: {final_path}")
            else:
                print(f"\n  [FAIL] 第 {idx+1} 帧未产生最终输出")

    if not final_paths:
        return _fail(state, "所有帧生成均失败")

    # ===== 3. 交互式后处理 =====
    current_result = final_paths[0]
    current_prompt = sdxl_prompt
    current_negative = sdxl_negative_prompt
    version = 1

    # Web 模式：跳过 CLI 交互菜单，直接返回结果
    if config.WEB_MODE:
        from utils.preferences import get_prefs
        prefs = get_prefs(config.USER_PREFS_PATH)
        prefs.learn_from_prompt(current_prompt, positive=True)
        prefs.add_history({"input": state.user_input, "final_prompt": current_prompt[:200], "image": current_result})
        prefs.save()
        print(f"\n  [Web] 跳过交互菜单，直接返回结果")

        success = SDXLEnhancerOutput(
            prompt_id=", ".join(all_prompt_ids),
            final_image_path=current_result,
            sdxl_error=None,
        )
        state.node_io["sdxl_enhancer"]["output"] = json.loads(success.model_dump_json())
        state.node_io["sdxl_enhancer"]["output"]["final_image_paths"] = final_paths
        state.node_io["sdxl_enhancer"]["output"]["grid_path"] = grid_path

        print(f"\n[NODE IO] sdxl_enhancer 成功: {current_result}")

        return {
            "node_io": state.node_io,
            "final_image_path": current_result,
            "final_image_paths": final_paths,
        }

    result = await _regenerate_loop(
        client=client,
        current_image=current_result,
        depth_name=depth_name,
        prompt=current_prompt,
        negative_prompt=current_negative,
        lora_name=lora_name,
        comfyui_input_dir=comfyui_input_dir,
        output_enhanced_dir=output_enhanced_dir,
        idx=idx,
        version=version,
    )

    # 从 loop 返回的最终结果
    final_image = result.get("image", current_result)
    final_prompt = result.get("prompt", current_prompt)
    all_prompt_ids.append(f"final_v{result.get('version', 1)}")

    # 保存偏好
    from utils.preferences import get_prefs
    prefs = get_prefs(config.USER_PREFS_PATH)
    prefs.learn_from_prompt(final_prompt, positive=True)
    prefs.add_history({"input": state.user_input, "final_prompt": final_prompt[:200], "image": final_image})
    prefs.save()
    print(f"\n  [Prefs] 偏好已保存")

    success = SDXLEnhancerOutput(
        prompt_id=", ".join(all_prompt_ids),
        final_image_path=final_image,
        sdxl_error=None,
    )
    state.node_io["sdxl_enhancer"]["output"] = json.loads(success.model_dump_json())
    state.node_io["sdxl_enhancer"]["output"]["final_image_paths"] = [final_image]
    state.node_io["sdxl_enhancer"]["output"]["grid_path"] = grid_path

    print(f"\n[NODE IO] sdxl_enhancer 成功: {final_image}")

    return {
        "node_io": state.node_io,
        "final_image_path": final_image,
        "final_image_paths": [final_image],
    }


async def _regenerate_loop(
    client: httpx.AsyncClient,
    current_image: str,
    depth_name: str,
    prompt: str,
    negative_prompt: str,
    lora_name: str,
    comfyui_input_dir: str,
    output_enhanced_dir: str,
    idx: int,
    version: int,
) -> dict:
    """交互式重生成循环。返回 {"image": path, "prompt": str, "version": int}"""
    import sys

    while True:
        choice = _interactive_result_menu(current_image, version)

        if choice == "1":
            # 满意，保存并结束
            print(f"\n  ✅ 用户满意，保存结果")
            return {"image": current_image, "prompt": prompt, "version": version}

        # 需要修改 prompt
        category = {
            "2": "光线/氛围", "3": "场景/环境", "4": "角色/服装/配饰",
            "5": "姿态/动作", "6": "风格/画风",
        }.get(choice, "光线/氛围")

        if not sys.stdin.isatty():
            print(f"\n  [AUTO] 非交互模式，自动保存")
            return {"image": current_image, "prompt": prompt, "version": version}

        print(f"\n  💡 你想改什么 {category}？(直接输入描述，回车取消)")
        try:
            user_request = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return {"image": current_image, "prompt": prompt, "version": version}

        if not user_request:
            print(f"  已取消")
            continue

        # 改写 prompt
        print(f"\n  ⏳ LLM 改写提示词...")
        new_prompt = await _rewrite_prompt(prompt, user_request, category)
        if not new_prompt or new_prompt == prompt:
            print(f"  [WARN] 提示词改写失败，保持不变")
            continue

        print(f"  旧: {prompt[:120]}...")
        print(f"  新: {new_prompt[:120]}...")

        # 重新生成 (只跑 SDXL，不跑 Blender)
        version += 1
        new_seed = int(time.time() * 1000) % 1000000
        prefix = f"reg_v{version}"

        print(f"\n  ⏳ 重新生成 (v{version}, seed={new_seed})...")

        gen_result = await _run_single_pass(
            client, "", depth_name, new_prompt, negative_prompt,
            seed=new_seed, denoise=1.0, cn_strength=config.ANIME_DEPTH_CN_STRENGTH,
            steps=config.ANIME_STEPS, cfg=config.ANIME_CFG, prefix=prefix,
            use_cn=True, is_txt2img=True,
            lora_filename=lora_name,
        )
        if not gen_result:
            print(f"  [WARN] 重生成 txt2img 失败")
            continue

        # Hires Fix
        if config.ANIME_HIRES_ENABLED:
            hires = await _run_hires_pass(
                client, gen_result, new_prompt, negative_prompt,
                seed=new_seed + 1000, denoise=config.ANIME_HIRES_DENOISE,
                steps=config.ANIME_HIRES_STEPS, prefix=f"hires_{prefix}",
                comfyui_input_dir=comfyui_input_dir,
            )
            if hires:
                gen_result = hires

        # Polish
        if POLISH_ENABLED:
            polish_name = f"polish_{prefix}.png"
            shutil.copy2(gen_result, os.path.join(comfyui_input_dir, polish_name))
            polish = await _run_single_pass(
                client, polish_name, depth_name, new_prompt, negative_prompt,
                seed=new_seed + 500, denoise=POLISH_DENOISE,
                cn_strength=POLISH_CN_STRENGTH, steps=POLISH_STEPS,
                prefix=f"polish_{prefix}", use_cn=True, is_txt2img=False,
                lora_filename=lora_name,
            )
            if polish:
                gen_result = polish

        # 保存新版本
        final_path = os.path.join(output_enhanced_dir, f"final_v{version}_{idx+1:04d}.png")
        shutil.copy2(gen_result, final_path)
        current_image = final_path
        prompt = new_prompt
        print(f"  [OK] v{version}: {final_path}")


def _interactive_result_menu(image_path: str, version: int) -> str:
    """展示交互菜单，返回用户选择 (1-6)。"""
    print(f"\n{'='*55}")
    print(f"  图片生成完成! (v{version})")
    print(f"  {image_path}")
    print()
    print(f"  [1] ✅ 满意，保存并结束")
    print(f"  [2] ☀️  换光线   — 黄昏/清晨/阴天/暖光/逆光...")
    print(f"  [3] 🎨 换场景   — 公园/咖啡馆/街道/海边...")
    print(f"  [4] ✏️  微调角色 — 短发/眼镜/换衣服/加配饰...")
    print(f"  [5] 🔄 换姿态   — 站立/走路/回头/伸手...")
    print(f"  [6] 🖼️  换风格   — 赛璐珞/水彩/厚涂/线稿...")
    print()

    import sys
    if not sys.stdin.isatty():
        print(f"  [AUTO] 非交互模式 → 自动选择[1]")
        return "1"

    try:
        choice = input("  选 (1-6): ").strip()
        if choice in ("1", "2", "3", "4", "5", "6"):
            return choice
    except (EOFError, KeyboardInterrupt):
        pass
    return "1"


async def _rewrite_prompt(
    current_prompt: str,
    user_request: str,
    category: str,
) -> str:
    """调用 LLM 根据用户要求改写 Danbooru 提示词。"""
    from utils.helpers import get_llm

    system = f"""你是 Danbooru 标签专家。用户想修改图片的{category}。

当前提示词: {current_prompt}

规则：
1. 只修改与"{category}"相关的标签，其他标签保持原样
2. 保持标签顺序：角色→姿态→手部→场景→光线→质量标签（末尾）
3. 手部标签（perfect hands, anatomically correct hands, defined fingers）必须保留
4. 质量标签（newest, high score, great score, masterpiece, best quality, absurdres）保持在末尾不动
5. 只输出修改后的完整 Danbooru 标签，用逗号分隔，不要任何解释
6. rating 标签（safe/sensitive）保留不动"""

    user = user_request

    try:
        llm = get_llm(temperature=0.3)
        response = await llm.ainvoke([
            ("system", system),
            ("user", user),
        ])
        new_prompt = response.content.strip()
        # 清理: 去掉可能的引号、前缀文字
        new_prompt = new_prompt.strip('"').strip("'")
        # 验证: 必须包含基本标签
        if "1girl" in new_prompt or "1boy" in new_prompt:
            return new_prompt
        # 如果 LLM 输出不含角色标签，可能只输出了修改部分 → 回退
        return current_prompt
    except Exception as e:
        print(f"    [WARN] 提示词改写异常: {e}")
        return current_prompt


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

    return await _poll_image(client, prompt_id, prefix)


async def _run_refiner_pass(
    client: httpx.AsyncClient,
    image_filename: str,
    positive_prompt: str,
    negative_prompt: str,
    seed: int = 42,
    denoise: float = 0.25,
    prefix: str = "refined",
) -> Optional[str]:
    """SDXL Refiner: 对生成结果做细节增强 img2img。"""
    if not config.COMFYUI_REFINER_CHECKPOINT:
        return None

    workflow = _build_refiner_workflow(
        image_filename=image_filename,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        refiner_checkpoint=config.COMFYUI_REFINER_CHECKPOINT,
        seed=seed,
        denoise=denoise,
        prefix=prefix,
    )

    try:
        resp = await client.post(
            f"{config.COMFYUI_BASE_URL}/prompt",
            json={"prompt": workflow},
        )
        if resp.status_code != 200:
            print(f"      Refiner 提交失败: {resp.status_code}")
            return None
        result = resp.json()
    except httpx.HTTPError as e:
        print(f"      Refiner HTTP 错误: {e}")
        return None

    prompt_id = result.get("prompt_id", "")
    if not prompt_id:
        return None

    return await _poll_image(client, prompt_id, prefix)


async def _poll_image(
    client: httpx.AsyncClient,
    prompt_id: str,
    prefix: str = "enhanced",
) -> Optional[str]:
    """轮询 ComfyUI 任务并下载输出图片。"""
    history_url = f"{config.COMFYUI_BASE_URL}/history/{prompt_id}"
    start = time.time()

    while time.time() - start < config.COMFYUI_TIMEOUT:
        await asyncio.sleep(config.COMFYUI_POLL_INTERVAL)

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


def _check_refiner_available() -> bool:
    """检测 ComfyUI 中是否加载了 SDXL Refiner 模型。"""
    model = config.COMFYUI_REFINER_CHECKPOINT
    if not model:
        return False
    try:
        import httpx as _httpx
        resp = _httpx.get(f"{config.COMFYUI_BASE_URL}/object_info", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            loader = data.get("CheckpointLoaderSimple", {})
            ckpts = loader.get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
            ok = model in ckpts
            print(f"[NODE IO] Refiner 模型 '{model}': {'可用' if ok else f'未找到，可用: {ckpts}'}")
            return ok
    except Exception:
        pass
    return False


def _fail(state: WorkflowState, msg: str, prompt_id: str = "") -> dict:
    output = SDXLEnhancerOutput(prompt_id=prompt_id, final_image_path="", sdxl_error=msg)
    state.node_io["sdxl_enhancer"] = {
        "input": state.node_io.get("sdxl_enhancer", {}).get("input", {}),
        "output": json.loads(output.model_dump_json()),
    }
    print(f"[NODE IO] sdxl_enhancer 失败: {msg[:300]}")
    return {"node_io": state.node_io}


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


async def public_rewrite_prompt(
    current_prompt: str,
    user_request: str,
    category: str,
) -> str:
    """公开包装：调用 _rewrite_prompt。"""
    return await _rewrite_prompt(current_prompt, user_request, category)
