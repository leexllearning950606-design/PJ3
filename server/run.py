"""开发/生产启动入口。"""
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
