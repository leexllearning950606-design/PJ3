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
    └──► Node 3 — Coder Agent      → Blender Python script
              │                        │
              │                        ▼
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

- **Spatial Control**: Blender-rendered depth maps guide ControlNet, preserving occlusion and multi-character layout
- **Self-Correcting Pipeline**: Error feedback loop (max 3 retries) enables automatic Blender script repair
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
| `ANIME_DEPTH_CN_STRENGTH` | 0.45 | ControlNet depth strength |
| `ANIME_DEPTH_CN_END` | 0.75 | ControlNet end step ratio |
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
│   ├── coder_agent.py       # Node 3: Blender script generation
│   ├── blender_executor.py  # Node 4: headless Blender execution
│   ├── blender_helpers.py   # Curated Blender helper functions
│   ├── sdxl_enhancer.py     # Node 5: SDXL + ControlNet
│   ├── comfyui_client.py    # ComfyUI API client
│   ├── comfyui_workflows.py # ComfyUI workflow definitions
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
1. Blender-to-ControlNet spatial constraint pipeline for anime generation
2. Multi-agent decomposition with self-correcting retry loop (100% vs 0% single-agent)
3. Scene-aware preference learning across 6 aesthetic dimensions
