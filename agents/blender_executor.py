"""Node 3: Blender Executor — 执行单摄像机脚本，输出颜色帧 + 深度图。

输入 JSON: BlenderInput
输出 JSON: BlenderOutput (含 frame_path, depth_path)
"""

import json
import subprocess
import tempfile
import os
import glob as glob_mod
from state.schema import WorkflowState
from state.models import BlenderInput, BlenderOutput
from config import config


async def blender_executor(state: WorkflowState) -> dict:
    """Node 3: 执行 Blender 脚本，输出 1 张颜色帧 + 1 张深度图。"""

    # ===== 1. 读取输入 =====
    prev_output = state.get_node_output("coder_agent")
    blender_script = prev_output.get("blender_script", "")

    blender_input = BlenderInput(
        blender_script=blender_script,
        retry_count=state.retry_count,
    )
    state.node_io["blender_executor"] = {
        "input": json.loads(blender_input.model_dump_json()),
    }

    print(f"\n[NODE IO] blender_executor 输入: retry={blender_input.retry_count}, 脚本长度={len(blender_script)}")

    # ===== 2. 校验 =====
    if not blender_script.strip():
        return _error(state, "Blender 脚本为空")

    # ===== 3. 注入 helper 函数 + 用户脚本 =====
    helpers_path = os.path.join(os.path.dirname(__file__), "blender_helpers.py")
    with open(helpers_path, "r", encoding="utf-8") as hf:
        helpers_code = hf.read()

    combined_script = helpers_code + "\n\n# ===== 用户生成脚本 =====\n\n" + blender_script

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(combined_script)
        script_path = f.name

    # 保存脚本副本用于调试
    debug_path = os.path.join(config.BLENDER_OUTPUT_DIR, "_last_script.py")
    try:
        import shutil as _shutil
        _shutil.copy2(script_path, debug_path)
    except Exception:
        pass

    try:
        result = subprocess.run(
            [config.BLENDER_EXECUTABLE_PATH, "--background", "--python", script_path],
            capture_output=True, text=True, timeout=config.BLENDER_TIMEOUT,
            encoding="utf-8", errors="replace",
            cwd=os.getcwd(),
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        print(f"[NODE IO] Blender stdout:\n{stdout[-1200:] if stdout else '(空)'}")
        if stderr:
            print(f"[NODE IO] Blender stderr:\n{stderr[-800:] if stderr else '(空)'}")

        if "Traceback" in stderr or "Error" in stderr:
            error_msg = stderr.splitlines()[-1] if stderr.splitlines() else stderr
            return _error(state, f"脚本异常: {error_msg[:300]}")

        if result.returncode != 0:
            return _error(state, stderr or stdout or "Blender 执行返回非零")

        # ===== 4. 从 stdout 解析颜色帧和深度图 =====
        frame_path = _parse_frame(stdout)
        depth_path = _parse_depth(stdout)
        frame_paths = _parse_all_frames(stdout)
        depth_paths = _parse_all_depths(stdout)

        # 回退：glob 搜索
        if not frame_path:
            frame_path = _find_file("frame_0001.png")
        if not depth_path:
            depth_path = _find_file("depth_0001.png")
        if not frame_paths:
            frame_paths = _find_all_files("frame_", "png")
        if not depth_paths:
            depth_paths = _find_all_files("depth_", "png")

        # 确保第一帧也在列表中
        if frame_path and frame_path not in frame_paths:
            frame_paths.insert(0, frame_path)
        if depth_path and depth_path not in depth_paths:
            depth_paths.insert(0, depth_path)

        if not frame_path:
            error_detail = stderr[-300:] or stdout[-300:]
            return _error(
                state,
                f"脚本执行完毕但未渲染帧。Blender输出尾部: {error_detail}",
            )

        # ===== 5. 成功 =====
        success = BlenderOutput(
            frame_path=frame_path,
            depth_path=depth_path,
            frame_paths=frame_paths,
            depth_paths=depth_paths,
            blender_error=None,
            retry_count=state.retry_count,
        )
        state.node_io["blender_executor"]["output"] = json.loads(success.model_dump_json())

        print(f"[NODE IO] blender_executor 成功: frame={frame_path}, depth={depth_path}")

        return {
            "node_io": state.node_io,
            "blender_error": None,
        }

    except subprocess.TimeoutExpired:
        return _error(state, f"Blender 执行超时 ({config.BLENDER_TIMEOUT}秒)")
    except FileNotFoundError:
        return _error(state, f"找不到 Blender: '{config.BLENDER_EXECUTABLE_PATH}'")
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _error(state: WorkflowState, msg: str) -> dict:
    """构建错误返回。"""
    output = BlenderOutput(
        blender_error=msg,
        retry_count=state.retry_count + 1,
    )
    state.node_io["blender_executor"]["output"] = json.loads(output.model_dump_json())
    print(f"[NODE IO] blender_executor 失败: {msg[:200]}")
    return {
        "node_io": state.node_io,
        "blender_error": output.blender_error,
        "retry_count": output.retry_count,
    }


def _parse_frame(stdout: str) -> str:
    """从 Blender stdout 解析 frame_0001.png 路径。"""
    for line in stdout.splitlines():
        if "Saved:" in line and "frame_" in line and ".png" in line:
            path = line.split("Saved:", 1)[1].strip().strip("'").strip('"')
            if os.path.isfile(path):
                return os.path.abspath(path)
    return ""


def _parse_depth(stdout: str) -> str:
    """从 Blender stdout 解析 depth_0001.png 路径。"""
    for line in stdout.splitlines():
        if "Saved:" in line and "depth_" in line and ".png" in line:
            path = line.split("Saved:", 1)[1].strip().strip("'").strip('"')
            if os.path.isfile(path):
                return os.path.abspath(path)
    return ""


def _parse_all_frames(stdout: str) -> list[str]:
    """从 Blender stdout 解析所有 frame_NNNN.png 路径。"""
    paths = []
    for line in stdout.splitlines():
        if "Saved:" in line and "frame_" in line and ".png" in line:
            path = line.split("Saved:", 1)[1].strip().strip("'").strip('"')
            if os.path.isfile(path) and path not in paths:
                paths.append(os.path.abspath(path))
    return sorted(paths)


def _parse_all_depths(stdout: str) -> list[str]:
    """从 Blender stdout 解析所有 depth_NNNN.png 路径。"""
    paths = []
    for line in stdout.splitlines():
        if "Saved:" in line and "depth_" in line and ".png" in line:
            path = line.split("Saved:", 1)[1].strip().strip("'").strip('"')
            if os.path.isfile(path) and path not in paths:
                paths.append(os.path.abspath(path))
    return sorted(paths)


def _find_file(filename: str) -> str:
    """在 Blender 输出目录搜索单个文件。"""
    path = os.path.join(config.BLENDER_OUTPUT_DIR, filename)
    if os.path.isfile(path):
        return os.path.abspath(path)
    return ""


def _find_all_files(prefix: str, ext: str) -> list[str]:
    """在输出目录搜索所有匹配前缀的文件。"""
    pattern = os.path.join(config.BLENDER_OUTPUT_DIR, f"{prefix}*.{ext}")
    matches = sorted(glob_mod.glob(pattern))
    return [os.path.abspath(m) for m in matches]
