"""每个节点的 JSON 数据契约 — 单场景 Blender + SDXL ControlNet Depth 管线。

管线: 用户文字 → 扩写丰富描述 → Blender 深度图(空间约束) → SDXL(画面美学)
"""

from pydantic import BaseModel, Field
from typing import Optional


# ==================== Node 1: Text Expander ====================

class TextExpanderInput(BaseModel):
    """Text Expander 的 JSON 输入。"""
    user_input: str = Field(..., description="用户原始简短输入")


class TextExpanderOutput(BaseModel):
    """Text Expander 的 JSON 输出 — 扩写后的丰富场景描述。"""
    expanded_text: str = Field(..., description="脑补扩写后的详细场景描述（中文，包含环境、人物、光线、氛围等）")


# ==================== Node 2: Coder Agent ====================

class CoderInput(BaseModel):
    """Coder Agent 的 JSON 输入。"""
    user_input: str = Field(..., description="用户原始文字描述")
    blender_error: Optional[str] = Field(None, description="上一次 Blender 的错误（首次为 null）")
    previous_script: Optional[str] = Field(None, description="上一次失败的脚本")
    retry_count: int = Field(0, description="当前重试次数")


class CoderOutput(BaseModel):
    """Coder Agent 的 JSON 输出 — 只生成 Blender 脚本。"""
    scene_description: str = Field(..., description="场景描述（环境、光线、色调、氛围、人物姿态）")
    blender_script: str = Field(..., description="单摄像机 Blender 脚本，渲染一张高精度场景")


# ==================== Node 2.5: SDXL Prompt Generator ====================

class SDXLPromptInput(BaseModel):
    """SDXL Prompt Generator 的 JSON 输入。"""
    expanded_text: str = Field(..., description="text_expander 扩写后的场景描述")
    scene_description: str = Field("", description="coder_agent 的场景概述（可选）")


class SDXLPromptOutput(BaseModel):
    """SDXL Prompt Generator 的 JSON 输出。"""
    sdxl_prompt: str = Field(..., description="英文 SDXL 提示词，Danbooru 标签格式")
    sdxl_negative_prompt: str = Field(
        default="lowres, worst quality, low quality, bad anatomy, bad hands, extra fingers, missing fingers, fused fingers, mutated hands, poorly drawn face, deformed, disfigured, text, signature, watermark, blurry, jpeg artifacts, ugly",
        description="SDXL 负向提示词",
    )


# ==================== Node 3: Blender Executor ====================

class BlenderInput(BaseModel):
    """Blender Executor 的 JSON 输入。"""
    blender_script: str = Field(..., description="要执行的 Blender Python 脚本")
    retry_count: int = Field(0, description="当前重试次数")


class BlenderOutput(BaseModel):
    """Blender Executor 的 JSON 输出 — 颜色帧 + 深度图 + 角色mask（支持多摄像机）。"""
    frame_path: str = Field("", description="第一帧颜色帧路径（向后兼容）")
    depth_path: str = Field("", description="第一帧深度图路径（向后兼容）")
    frame_paths: list[str] = Field(default_factory=list, description="所有颜色帧路径")
    depth_paths: list[str] = Field(default_factory=list, description="所有深度图路径")
    blender_error: Optional[str] = Field(None, description="执行失败时的错误信息")
    retry_count: int = Field(0, description="更新后的重试次数")


# ==================== Node 4: SDXL Enhancer ====================

class SDXLEnhancerInput(BaseModel):
    """SDXL Enhancer 的 JSON 输入。"""
    frame_path: str = Field(..., description="Blender 颜色帧路径（提供 VAE 编码的初始 latent）")
    depth_path: str = Field(..., description="Blender 深度图路径（ControlNet 硬约束）")
    sdxl_prompt: str = Field(..., description="SDXL 正向提示词")
    sdxl_negative_prompt: str = Field("", description="SDXL 负向提示词")


class SDXLEnhancerOutput(BaseModel):
    """SDXL Enhancer 的 JSON 输出。"""
    prompt_id: str = Field("", description="ComfyUI 任务 ID")
    final_image_path: str = Field("", description="最终增强图片路径")
    sdxl_error: Optional[str] = Field(None, description="调用失败时的错误信息")
