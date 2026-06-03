"""Blender + SDXL 高质量图片生成智能体。

数据流:
    用户简短输入 → 扩写丰富描述 → Blender 场景搭建(深度图+颜色帧)
                                 → SDXL ControlNet Depth 增强
                                 → 高质量静态图片

用法:
    python main.py "一个武士在雨夜走进废弃寺庙"
"""

import sys
import asyncio
from typing import Optional
from graph import app

# 修复 Windows GBK 控制台 Unicode 编码崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


async def main():
    if len(sys.argv) < 2:
        print("用法: python main.py \"场景描述\"")
        print("示例: python main.py \"一个武士在雨夜走进废弃寺庙\"")
        sys.exit(1)

    user_input = " ".join(sys.argv[1:])
    print(f"用户输入: {user_input}")
    print("=" * 60)

    initial_state = {"user_input": user_input}
    print("Blender + SDXL 图片生成 — JSON 数据流追踪:\n")

    final_state = None
    async for step in app.astream(initial_state):
        node_name = list(step.keys())[0]
        node_state = step[node_name]
        final_state = node_state
        _print_node_progress(node_name, node_state)

    _print_final_result(final_state)


def _print_node_progress(node_name: str, state: dict):
    """打印每个节点的执行摘要。"""
    node_io = state.get("node_io", {})
    node_data = node_io.get(node_name, {})
    node_output = node_data.get("output", {})

    labels = {
        "text_expander":    "Text Expander (简短→丰富描述)",
        "coder_agent":      "Coder Agent (描述→场景+脚本+提示词)",
        "blender_executor": "Blender Executor (深度图+颜色帧)",
        "sdxl_enhancer":    "SDXL Enhancer (ControlNet Depth 增强)",
    }
    label = labels.get(node_name, node_name)

    print(f"┌── {label}")

    if node_name == "text_expander":
        expanded = node_output.get("expanded_text", "")
        print(f"│  扩写长度: {len(expanded)} 字符")
        print(f"│  预览: {expanded[:120]}...")

    elif node_name == "coder_agent":
        print(f"│  场景: {node_output.get('scene_description', '')[:80]}")
        print(f"│  SDXL提示词: {node_output.get('sdxl_prompt', '')[:100]}")
        print(f"│  脚本长度: {len(node_output.get('blender_script', ''))} 字符")

    elif node_name == "blender_executor":
        if node_output.get("blender_error"):
            print(f"│  失败 (重试 #{state.get('retry_count', 0)})")
            print(f"│  错误: {node_output['blender_error'][:150]}")
        else:
            print(f"│  颜色帧: {node_output.get('frame_path', '(无)')}")
            print(f"│  深度图: {node_output.get('depth_path', '(无)')}")

    elif node_name == "sdxl_enhancer":
        if node_output.get("sdxl_error"):
            print(f"│  失败: {node_output['sdxl_error'][:150]}")
        else:
            paths = node_output.get("final_image_paths", [])
            if paths:
                print(f"│  增强 {len(paths)} 帧:")
                for p in paths:
                    print(f"│    {p}")
            else:
                print(f"│  最终图片: {node_output.get('final_image_path', '(无)')}")

    print(f"└{'─' * 45}")


def _print_final_result(state: Optional[dict] = None):
    print("\n" + "=" * 60)

    if state is None:
        print("工作流未产生输出。")
        return

    enhancer_out = (
        state.get("node_io", {}).get("sdxl_enhancer", {}).get("output", {})
    )
    image_path = enhancer_out.get("final_image_path") or state.get("final_image_path", "")
    all_paths = enhancer_out.get("final_image_paths", []) or state.get("final_image_paths", [])

    if all_paths:
        print(f"[OK] {len(all_paths)} 张高质量图片已生成:")
        for p in all_paths:
            print(f"  {p}")
    elif image_path:
        print(f"[OK] 高质量图片已生成: {image_path}")
    elif state.get("error_message"):
        print(f"[ERROR] 出错: {state['error_message']}")
    else:
        blender_out = state.get("node_io", {}).get("blender_executor", {}).get("output", {})
        if blender_out.get("blender_error"):
            print(f"[ERROR] Blender 失败 (重试 {state.get('retry_count', 0)} 次)")
            print(f"   {blender_out['blender_error'][:300]}")
        else:
            print("[WARN] 工作流完成但未生成图片，请检查 ComfyUI 输出。")


if __name__ == "__main__":
    asyncio.run(main())
