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
import httpx
from PIL import Image, ImageFilter
from state.schema import WorkflowState
from state.models import SDXLEnhancerInput, SDXLEnhancerOutput
from config import config
from utils.helpers import ensure_dir

# ---- 拆分后的内部模块 ----
from .comfyui_workflows import (
    POLISH_ENABLED, POLISH_DENOISE, POLISH_CN_STRENGTH, POLISH_STEPS,
)
from .comfyui_client import (
    _run_single_pass,
    _run_hires_pass,
    _check_controlnet_available,
)
from .quality_filter import (
    _check_frame_quality,
    _create_grid_image,
    _interactive_select,
)
from .error_utils import set_node_error


# ===========================
# 深度图分区域柔化
# ===========================

def _blur_depth_full(
    depth_path: str,
    output_dir: str,
    blur_radius: float = 15.0,
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


def _get_blob_count(state: WorkflowState) -> int:
    """从场景 JSON 中解析人物 blob 数量，用于动态调整 CN 参数。"""
    try:
        coder_out = state.get_node_output("coder_agent")
        script = coder_out.get("blender_script", "")
        if script.strip().startswith("{"):
            scene_json = json.loads(script)
            return len(scene_json.get("blobs", []))
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return 1  # 默认当作单人


# ===========================
# 主函数
# ===========================

async def sdxl_enhancer(state: WorkflowState) -> dict:
    """Node 4: 多 Seed txt2img → 质量筛选 → 2×2 网格图 → 交互选择 → Hires Fix → Polish。"""

    # ===== 1. 读取输入 =====
    blender_out = state.get_node_output("blender_executor")
    prompt_out = state.get_node_output("sdxl_prompt_gen")

    frame_paths = blender_out.get("frame_paths", [])
    depth_paths = blender_out.get("depth_paths", [])
    if not frame_paths:
        single_frame = blender_out.get("frame_path", "")
        single_depth = blender_out.get("depth_path", "")
        if single_frame:
            frame_paths = [single_frame]
            depth_paths = [single_depth] if single_depth else [""]

    sdxl_prompt = prompt_out.get("sdxl_prompt", "")
    sdxl_negative_prompt = prompt_out.get(
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
        return set_node_error(state, "sdxl_enhancer", state.error_message)
    if not frame_paths:
        return set_node_error(state, "sdxl_enhancer", "无颜色帧文件")

    # ===== 2. 检查 ControlNet =====
    use_controlnet = _check_controlnet_available()
    print(f"[NODE IO] ControlNet: {'可用' if use_controlnet else '跳过'}")
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
                blur_radius=15.0, idx=idx + 1,
            )
            depth_name = os.path.basename(soft_depth_path)

            # LoRA
            lora_name = ""
            if config.COMFYUI_LORA_SHINKAI:
                lora_name = config.COMFYUI_LORA_SHINKAI
                print(f"  使用 LoRA: {lora_name}")
            else:
                print(f"  [INFO] 未配置 LoRA，使用 Animagine XL 默认风格")

            # 动态 CN 参数：根据人物数量调整空间约束强度
            blob_count = _get_blob_count(state)
            if blob_count >= 2:
                cn_strength = 0.65      # 多人：强空间约束防合并
                cn_end = 0.80           # 引导到 80%，留 20% 给风格
            else:
                cn_strength = 0.45      # 单人：宽松约束
                cn_end = 0.60           # 引导到 60%，留 40% 给画风
            # 运行时覆盖 config（workflow builder 从 config 读取）
            config.ANIME_DEPTH_CN_END = cn_end
            print(f"  CN: strength={cn_strength}, end={cn_end} (blobs={blob_count})")
            seed = int(time.time() * 1000) % 1000000

            if config.WEB_MODE:
                # Web 模式: 单种子直出，跳过 4 选 1 和网格图
                print(f"\n  [Web] 单种子生成: seed={seed}")
                result = await _run_single_pass(
                    client, "", depth_name, sdxl_prompt, sdxl_negative_prompt,
                    seed=seed, denoise=1.0, cn_strength=cn_strength,
                    steps=config.ANIME_STEPS, cfg=config.ANIME_CFG, prefix="gen",
                    use_cn=True, is_txt2img=True,
                    lora_filename=lora_name,
                )
                if not result:
                    print(f"  [FAIL] 生成失败")
                    continue
                selected_seed = seed
                current_result = result
            else:
                # CLI 模式: 多种子 + 质量筛选 + 网格图 + 交互选择
                n_seeds = config.ANIME_MULTI_SEED_COUNT
                base_seed = seed
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

                valid = [v for v in variants if v["quality"]["pass"]]
                if not valid:
                    valid = variants

                grid_path = _create_grid_image(
                    [v["path"] for v in valid],
                    output_enhanced_dir, idx=idx + 1,
                )

                chosen_idx = _interactive_select(
                    len(valid),
                    [v["seed"] for v in valid],
                )
                selected = valid[chosen_idx]
                selected_seed = selected["seed"]
                current_result = selected["path"]
                print(f"  选中 seed={selected_seed}")

            # ===============================================
            # Phase E: Hires Fix (Web + CLI 共用)
            # ===============================================
            if config.ANIME_HIRES_ENABLED:
                print(f"\n  [Phase E] Hires Fix: 1.5× → {int(1024*config.ANIME_HIRES_FACTOR)}×{int(1024*config.ANIME_HIRES_FACTOR)}, denoise={config.ANIME_HIRES_DENOISE}")
                hires_result = await _run_hires_pass(
                    client, current_result, sdxl_prompt, sdxl_negative_prompt,
                    seed=selected_seed + 1000,
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

            # ===============================================
            # Phase F: 打磨 (Web + CLI 共用)
            # ===============================================
            if POLISH_ENABLED:
                polish_name = f"polish_input_{idx+1:04d}.png"
                shutil.copy2(current_result, os.path.join(comfyui_input_dir, polish_name))

                polish_seed = selected_seed + 500
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

            # 保存最终结果 — 用 uuid 防覆盖
            if current_result and os.path.isfile(current_result):
                import uuid
                uid = str(uuid.uuid4())[:8]
                final_path = os.path.join(output_enhanced_dir, f"final_{uid}.png")
                shutil.copy2(current_result, final_path)
                final_paths.append(final_path)
                all_prompt_ids.append(f"frame{idx+1}")
                print(f"\n  [OK] 第 {idx+1} 帧完成: {final_path}")
            else:
                print(f"\n  [FAIL] 第 {idx+1} 帧未产生最终输出")

    if not final_paths:
        return set_node_error(state, "sdxl_enhancer", "所有帧生成均失败")

    # ===== 3. 交互式后处理 =====
    current_result = final_paths[0]
    current_prompt = sdxl_prompt
    current_negative = sdxl_negative_prompt
    version = 1

    # Web 模式：跳过 CLI 交互菜单，直接返回结果
    if config.WEB_MODE:
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


# ===========================
# 重导出 — 保持向后兼容
# ===========================

# server/worker.py 需要这些符号:
from .comfyui_workflows import (  # noqa: E402, F401
    POLISH_ENABLED, POLISH_DENOISE, POLISH_CN_STRENGTH,
)
from .comfyui_client import (  # noqa: E402, F401
    public_run_single_pass,
    public_run_hires_pass,
)
from .prompt_rewriter import public_rewrite_prompt  # noqa: E402, F401  # exported for server/worker.py
