"""FastAPI 应用工厂 — CORS、静态文件、lifespan。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from server.routes import router
from server.comfyui_manager import comfyui


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动 ComfyUI / 关闭 ComfyUI。"""
    print("[Server] 启动中...")
    comfyui.start()

    yield

    print("[Server] 关闭中...")
    comfyui.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Anime Generator", version="1.0", lifespan=lifespan)

    # CORS — 允许 Vite dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5174", "http://127.0.0.1:5174",
            "http://localhost:5175", "http://127.0.0.1:5175",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API 路由
    app.include_router(router)

    # 静态文件 — 让 output/ 下的图片可通过 URL 访问
    import os
    output_dir = os.path.abspath("./output")
    if os.path.isdir(output_dir):
        app.mount("/output", StaticFiles(directory=output_dir), name="output")

    return app
