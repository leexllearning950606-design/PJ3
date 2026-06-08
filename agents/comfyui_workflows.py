"""ComfyUI 工作流构建 — 纯数据函数，无 I/O。

提供 txt2img / hires fix / img2img+ControlNet / 纯 img2img 回退 四种工作流。
"""

from config import config


# ===========================
# 可选打磨配置
# ===========================

# 可选打磨: img2img 低 denoise 统一画面 (动漫降低强度)
POLISH_ENABLED = True
POLISH_DENOISE = 0.10
POLISH_CN_STRENGTH = 0.20
POLISH_STEPS = 15


# ===========================
# 工作流构建
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
            "end_percent": config.ANIME_DEPTH_CN_END,  # 从配置读取，多人物场景需更高值
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
            "end_percent": config.ANIME_DEPTH_CN_END,
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
