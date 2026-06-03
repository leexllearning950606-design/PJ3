"""工具函数：LLM 工厂、文件操作等。"""

import os
from config import config
from langchain_openai import ChatOpenAI


def get_llm(temperature: float = 0.3) -> ChatOpenAI:
    """获取 DeepSeek LLM 实例 (OpenAI 兼容接口)。"""
    return ChatOpenAI(
        model=config.DEEPSEEK_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        temperature=temperature,
    )


def ensure_dir(path: str) -> str:
    """确保目录存在，返回路径。"""
    os.makedirs(path, exist_ok=True)
    return path
