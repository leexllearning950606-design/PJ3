# 动漫风格管线设计 — 新海诚风格

**日期**: 2026-06-02
**状态**: 设计已确认

## 目标

将项目从写实风格 (Juggernaut XL v9) 切换为新海诚风格动漫生成 (Animagine XL 4.0 + Shinkai LoRA)。

核心场景：教室/农田等，人物特定姿态（手托腮、靠手臂发呆、写字等）。

## 关键决策

1. **Blender 只出场景深度图** — 删除人形创建和摆姿（add_humanoid/render_skeleton），保留教室/桌椅/窗户/灯光的 3D 搭建
2. **人物交给动漫模型自由生成** — Animagine XL 4.0 在深度图约束下自动生成人物
3. **动画风格通过 LoRA 锁定** — 下载新海诚风格 LoRA，权重 ~0.75
4. **提示词格式从自然语言改为 Danbooru 标签** — 动漫模型不识别自然语言

## 架构变化

### 删除
- `blender_helpers.py`: `add_humanoid()`, `render_skeleton()`, `render_character_mask()`
- `sdxl_enhancer.py`: OpenPose ControlNet 链, FaceDetailer, HandDetailer
- `coder_agent.py`: 姿态 rotation_euler 代码生成, 骨架渲染调用

### 保留
- `text_expander` (LLM 场景描述扩展)
- `coder_agent` (LLM 生成 Blender 脚本 + SDXL 提示词 — 提示词格式需改)
- Blender 场景搭建 (房间、桌椅、窗户、灯光)
- Blender 深度图渲染 (Depth CN 弱约束空间布局)
- Depth ControlNet (强度降低到 0.20-0.30)
- Polish pass (可选 img2img)

### 新增
- ComfyUI LoRA Loader 节点 (Shinkai LoRA, weight=0.70-0.85)
- Danbooru 标签格式提示词 (Quality Tags + Year Tag + 角色/场景/风格标签)
- 动漫优化采样参数 (Euler a, CFG 6.0-7.0, Steps 24-28)

## 新数据流

```
用户输入: "教室中，女孩靠窗发呆"
    │
    ▼
text_expander (LLM) → 场景描述
    │
    ▼
coder_agent (LLM)
    ├─ Blender 脚本 (空场景 + 灯光 + 相机)
    └─ Danbooru 标签 SDXL 提示词
    │
    ▼
blender_executor → depth_0001.png (空教室深度图)
    │
    ▼
sdxl_enhancer (ComfyUI)
    ├─ Animagine XL 4.0 + Shinkai LoRA(0.75)
    ├─ Depth CN (strength=0.25, end_percent=0.55)
    └─ KSampler (euler_a, normal, steps=24, cfg=6.5)
    │
    ▼
final_image.png (新海诚风格动漫图)
```

## 提示词格式

### Positive (Danbooru 标签)
```
masterpiece, best quality, newest, amazing quality,
1girl, solo, black hair, school uniform,
{姿态标签: sitting, chair, resting chin on hand / daydreaming / writing},
{场景标签: classroom, desk, by window, sunlight, ray of light},
shinkai makoto style, cinematic lighting, beautiful detailed background,
depth of field, lens flare
```

### Negative
```
lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit,
fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts,
signature, watermark, username, blurry, artist name, nsfw
```

## 采样参数

| 参数 | 旧 (写实) | 新 (动漫) |
|------|-----------|-----------|
| Checkpoint | juggernautXL_v9 | animagine-xl-4.0-opt |
| LoRA | 无 | Shinkai Makoto (0.75) |
| Sampler | dpmpp_2m | euler_a |
| Scheduler | karras | normal |
| Steps | 30 | 24 |
| CFG | 5.5 | 6.5 |
| Depth CN strength | 0.35 | 0.25 |
| Depth CN end_percent | 0.60 | 0.55 |
| OpenPose CN | 0.55 | 删除 |
| FaceDetailer | Yes | 删除 |
| HandDetailer | Yes | 删除 |

## 涉及文件

| 文件 | 改动 |
|------|------|
| `.env` | COMFYUI_CHECKPOINT → animagine-xl-4.0-opt.safetensors, 新增 COMFYUI_LORA |
| `config.py` | 新增动漫默认值 (ANIME_SAMPLER, ANIME_SCHEDULER, ANIME_CFG 等) |
| `sdxl_enhancer.py` | 删除 OpenPose CN 链 + FaceDet/HandDet, 新增 LoRA Loader, 改采样参数 |
| `coder_agent.py` | 提示词格式从自然语言改为 Danbooru 标签, 删除姿态代码生成 |
| `blender_helpers.py` | 删除 add_humanoid/render_skeleton/render_character_mask |

## 需要下载

- **新海诚 LoRA** (~200MB): 从 Civitai/HuggingFace 搜索 "shinkai makoto style animagine xl" → 放到 `D:\ComfyUI_Models\loras\`

## 验证

1. 下载并放置 Shinkai LoRA 到正确目录
2. 运行 `python main.py "在教室中，一位女孩靠在自己手臂上发呆，一束阳光，刚好打在脸庞"`
3. 检查生成的动漫图片风格是否接近《你的名字》
4. 检查场景布局是否合理（教室/窗户/桌椅位置）
5. 调节 LoRA 权重 (0.5-1.0) 找到最佳风格强度
