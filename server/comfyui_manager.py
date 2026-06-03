"""ComfyUI 进程生命周期管理 — 启动/等待就绪/关闭。"""
from __future__ import annotations
import subprocess
import time
import httpx
import asyncio
import os
import sys
from config import config


class ComfyUIManager:
    """管理 ComfyUI 子进程。"""

    def __init__(self):
        self.process: subprocess.Popen | None = None

    def start(self):
        """启动 ComfyUI 进程并等待就绪。"""
        comfy_path = config.COMFYUI_PATH
        if not comfy_path or not os.path.isdir(comfy_path):
            print(f"[ComfyUI] 路径无效或未配置: {comfy_path}")
            print("[ComfyUI] 请手动启动 ComfyUI 或设置 COMFYUI_PATH 环境变量")
            return False

        # 判断启动脚本
        if sys.platform == "win32":
            main_script = os.path.join(comfy_path, "main.py")
            python_exe = os.path.join(comfy_path, "python_embeded", "python.exe")
            if os.path.isfile(python_exe):
                cmd = [python_exe, main_script]
            else:
                cmd = [sys.executable, main_script]
        else:
            main_script = os.path.join(comfy_path, "main.py")
            cmd = [sys.executable, main_script]

        env = os.environ.copy()
        env["COMFYUI_PORT"] = str(config.COMFYUI_BASE_URL).split(":")[-1].rstrip("/")

        print(f"[ComfyUI] 启动: {' '.join(cmd)}")
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=comfy_path,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print(f"[ComfyUI] 启动失败: 找不到 {cmd[0]}")
            return False

        # 等待就绪
        return self._wait_ready()

    def _wait_ready(self, timeout: int | None = None) -> bool:
        """轮询 ComfyUI 直到就绪或超时。"""
        if timeout is None:
            timeout = config.COMFYUI_STARTUP_WAIT
        base_url = config.COMFYUI_BASE_URL
        print(f"[ComfyUI] 等待就绪 (最多 {timeout}s)...")
        for i in range(timeout):
            try:
                resp = httpx.get(f"{base_url}/system_stats", timeout=3)
                if resp.status_code == 200:
                    print(f"[ComfyUI] 就绪 ({i+1}s)")
                    return True
            except Exception:
                pass
            time.sleep(1)
        print("[ComfyUI] 启动超时！请手动检查")
        return False

    def is_ready(self) -> bool:
        """检查 ComfyUI 是否在线。"""
        try:
            resp = httpx.get(f"{config.COMFYUI_BASE_URL}/system_stats", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def stop(self):
        """终止 ComfyUI 进程。"""
        if self.process is None:
            return
        print("[ComfyUI] 正在关闭...")
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        except Exception as e:
            print(f"[ComfyUI] 关闭异常: {e}")
        self.process = None
        print("[ComfyUI] 已关闭")


# 全局单例
comfyui = ComfyUIManager()
