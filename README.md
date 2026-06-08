# PJ3 — Multi-Agent Anime Illustration Generation

A LangGraph-orchestrated multi-agent pipeline that generates anime illustrations from free-form Chinese text input, using Blender 3D scene construction for spatial control and Animagine XL 4.0 with ControlNet Depth conditioning for image synthesis.

## Architecture

```
User Input (Chinese)
    │
    ▼
Node 1 — Text Expander            → enriched scene description
    │
    ├──► Node 2 — Tag Translator   → Danbooru prompt
    │
    └──► Node 3 — Scene Layout     → JSON scene manifest
              │                        │
              │              Deterministic Parser → Blender Python script
              │                        │
              │              Node 4 — Blender Executor → depth map + color frame
              │                        │
              │    ┌─── error (retry < 3) ───┘
              │    │
              └────┼──► Node 5 — SDXL Enhancer → anime image
                   │         (txt2img + ControlNet Depth
                   │          + Hires Fix + Polish)
                   ▼
              Anime Image
```

## Key Features

- **Spatial Control**: LLM generates JSON scene manifest → deterministic parser → Blender depth map → ControlNet, enforcing precise multi-character layout and occlusion
- **Self-Correcting Pipeline**: Error feedback loop (max 3 retries) for automatic JSON scene revision
- **Adaptive ControlNet**: Dynamic strength/end_percent based on character count (single: 0.45/60%, multi: 0.65/80%)
- **Preference Learning**: 6-dimension aesthetic model with scene-aware filtering and injection
- **Web UI**: Vue 3 frontend with real-time SSE progress, interactive refinement, and dislike feedback

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Orchestration | LangGraph |
| LLM | DeepSeek-Chat |
| 3D Engine | Blender 5.x (headless, Cycles) |
| Image Generation | Animagine XL 4.0 + ControlNet Depth |
| Web Server | FastAPI + uvicorn |
| Frontend | Vue 3 + Pinia |

## Quick Start

### Prerequisites

- Python 3.9+
- Blender 5.x (headless)
- ComfyUI with Animagine XL 4.0 and `diffusers_xl_depth_full.safetensors`
- DeepSeek API key

### Setup

```bash
pip install -r requirements.txt
# Edit .env: DEEPSEEK_API_KEY, BLENDER_EXECUTABLE_PATH, COMFYUI_BASE_URL
```

### CLI Usage

```bash
python main.py "a girl hiding behind a cherry tree"
```

### Web UI

```bash
python -m server.run
# Open http://127.0.0.1:8080
```

## Configuration

Key parameters in `config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ANIME_DEPTH_CN_STRENGTH` | 0.65 | ControlNet depth strength (dynamically adjusted: 0.45 single, 0.65 multi) |
| `ANIME_DEPTH_CN_END` | 0.80 | ControlNet end step ratio (dynamically adjusted: 0.60 single, 0.80 multi) |
| `ANIME_STEPS` | 28 | Sampling steps |
| `ANIME_CFG` | 5.0 | CFG scale |
| `ANIME_HIRES_FACTOR` | 1.5 | Hires Fix upscale factor |
| `BLENDER_MAX_RETRIES` | 3 | Max retry attempts |

## Preference System

User aesthetic preferences stored in `user_prefs.json` across 6 dimensions: `color_tone`, `lighting`, `style`, `mood`, `composition`, `quality`. Preferences are injected with scene-compatibility awareness — incompatible tags are automatically filtered.

## Project Structure

```
PJ3/
├── main.py                  # CLI entry point
├── config.py                # Global configuration
├── agents/
│   ├── text_expander.py     # Node 1: scene expansion
│   ├── sdxl_prompt_gen.py   # Node 2: tag translation
│   ├── coder_agent.py       # Node 3: JSON scene manifest generation
│   ├── scene_parser.py      # Deterministic JSON → Blender Python translator
│   ├── blender_executor.py  # Node 4: headless Blender execution
│   ├── blender_helpers.py   # Curated Blender helper functions (35mm camera, smart layout)
│   ├── sdxl_enhancer.py     # Node 5: SDXL + adaptive ControlNet
│   ├── comfyui_client.py    # ComfyUI API client
│   ├── comfyui_workflows.py # ComfyUI workflow definitions
│   ├── prompt_rewriter.py   # LLM prompt rewriting for interactive refinement
│   ├── quality_filter.py    # Automated quality checks
│   └── error_utils.py       # Error handling utilities
├── graph/
│   └── workflow.py          # LangGraph state machine
├── state/
│   ├── schema.py            # WorkflowState definition
│   └── models.py            # Pydantic data contracts
├── server/
│   ├── app.py               # Web server entry
│   ├── worker.py            # Pipeline runner with SSE
│   ├── routes.py            # API routes
│   └── task_store.py        # Task persistence
├── utils/
│   ├── preferences.py       # Preference manager (CN↔EN mapping)
│   └── helpers.py           # LLM helpers
├── web/                     # Vue 3 frontend
├── paper/                   # ICLR 2026 paper source
└── output/                  # Generated images
```

**Contributions:**
1. **JSON scene manifest + deterministic parser**: LLM reasons about spatial layout (JSON), parser generates correct Blender code — eliminates spatial reasoning errors at the code level
2. **3D-to-2D spatial constraint pipeline**: Blender-rendered depth maps with adaptive ControlNet (strength 0.45–0.65, end 60–80%) for anime generation
3. **Self-correcting retry loop**: Error feedback to JSON revision (max 3 attempts) achieves 100% script execution success
4. **Scene-aware preference learning**: 6 aesthetic dimensions with CN↔EN mapping and scene-compatibility filtering
