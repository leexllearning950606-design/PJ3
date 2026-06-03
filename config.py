import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """全局配置，从环境变量加载。"""

    # --- LLM: DeepSeek (OpenAI 兼容) ---
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # --- ComfyUI ---
    COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8000")
    COMFYUI_TIMEOUT = int(os.getenv("COMFYUI_TIMEOUT", "300"))
    COMFYUI_POLL_INTERVAL = 2
    COMFYUI_INPUT_DIR = os.getenv("COMFYUI_INPUT_DIR", "./comfyui_input")
    COMFYUI_CHECKPOINT = os.getenv(
        "COMFYUI_CHECKPOINT", "juggernautXL_v9.safetensors"
    )
    COMFYUI_REFINER_CHECKPOINT = os.getenv(
        "COMFYUI_REFINER_CHECKPOINT", ""
    )  # 动漫模型无 Refiner，留空跳过
    COMFYUI_CONTROLNET_DEPTH = os.getenv(
        "COMFYUI_CONTROLNET_DEPTH", "diffusers_xl_depth_full.safetensors"
    )
    COMFYUI_LORA_SHINKAI = os.getenv(
        "COMFYUI_LORA_SHINKAI", ""
    )
    COMFYUI_VAE = os.getenv(
        "COMFYUI_VAE", ""
    )  # Anime VAE: kl-f8-anime2.vae.pt (空=使用 checkpoint 内置 VAE)

    # --- ComfyUI 自动启动 ---
    COMFYUI_PATH = os.getenv("COMFYUI_PATH", "D:\\ComfyUI_windows_portable")
    COMFYUI_STARTUP_WAIT = int(os.getenv("COMFYUI_STARTUP_WAIT", "30"))  # 等待就绪最长秒数

    # --- 动漫生成参数 (Animagine XL 4.0) ---
    ANIME_SAMPLER = "euler_ancestral"       # 官方推荐 Euler a（非普通 Euler）
    ANIME_SCHEDULER = "normal"              # Euler a 配合 normal scheduler
    ANIME_STEPS = 28                        # 官方推荐 28 步
    ANIME_CFG = 5.0                         # 官方推荐 CFG 4-7，取 5
    ANIME_DEPTH_CN_STRENGTH = 0.25
    ANIME_DEPTH_CN_END = 0.55
    ANIME_LORA_WEIGHT = 0.55

    # --- Hires Fix 高分辨率修复 ---
    ANIME_HIRES_ENABLED = True
    ANIME_HIRES_FACTOR = 1.5                # 放大倍数: 1024→1536
    ANIME_HIRES_DENOISE = 0.40              # img2img denoise
    ANIME_HIRES_STEPS = 20                  # img2img 步数

    # --- 多 Seed 生成 + 质量筛选 ---
    ANIME_MULTI_SEED_COUNT = 4              # 一次生成几张变体
    ANIME_QUALITY_OVEREXPOSE_THRESHOLD = 0.05   # 过曝像素占比 > 5% → 淘汰
    ANIME_QUALITY_UNDEREXPOSE_THRESHOLD = 0.40  # 过暗像素占比 > 40% → 淘汰
    ANIME_QUALITY_LOW_STD_THRESHOLD = 25        # 像素标准差 < 25 → 淘汰(纯色/噪点)

    # --- 用户偏好 ---
    USER_PREFS_PATH = os.getenv("USER_PREFS_PATH", "./user_prefs.json")

    # --- Blender ---
    BLENDER_EXECUTABLE_PATH = os.getenv("BLENDER_EXECUTABLE_PATH", "blender")
    BLENDER_OUTPUT_DIR = os.getenv("BLENDER_OUTPUT_DIR", "./output/blender")
    BLENDER_TIMEOUT = int(os.getenv("BLENDER_TIMEOUT", "300"))
    BLENDER_MAX_RETRIES = 3  # 脚本执行失败最大重试次数

    # --- Web 服务器 ---
    SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8080"))
    WEB_MODE = os.getenv("WEB_MODE", "true").lower() in ("1", "true", "yes")

    # --- 输出 ---
    OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")


config = Config()
