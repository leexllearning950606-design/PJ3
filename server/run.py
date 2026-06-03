"""开发/生产启动入口。"""
import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    )
