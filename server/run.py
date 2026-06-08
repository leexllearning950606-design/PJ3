"""开发/生产启动入口。"""
import sys
import os

# 修复 Windows GBK 控制台 Unicode 编码崩溃 (必须在所有 import 之前)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 确保项目根目录在 sys.path 中，且 CWD 为项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import uvicorn
from config import config
from server.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "server.run:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=True,
        reload_dirs=["agents", "server", "state", "graph", "utils"],
    )
