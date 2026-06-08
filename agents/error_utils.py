"""统一错误处理 — 供所有 LangGraph 管线节点使用。

提供:
  - set_node_error(): 统一替代 blender_executor._error() 和 sdxl_enhancer._fail()
  - PipelineError: 非节点工具函数的自定义异常
"""

import json
from state.schema import WorkflowState


class PipelineError(Exception):
    """管线工具函数（非节点）的自定义异常。

    在 ComfyUI 客户端、提示词改写器等工具函数中，无法返回 state dict，
    应抛出此异常，由调用方节点函数捕获后调用 set_node_error()。
    """
    pass


def set_node_error(state: WorkflowState, node_name: str, msg: str, **extra) -> dict:
    """统一的节点错误状态构建器。

    替代:
      - blender_executor._error(state, msg)
      - sdxl_enhancer._fail(state, msg)

    行为按 node_name 分发:
      - "blender_executor" → BlenderOutput 模型，设 blender_error + retry_count
        （供 LangGraph 条件边路由到 retry/error/continue）。
      - "sdxl_enhancer"    → SDXLEnhancerOutput 模型，只设 node_io
        （终端节点，无下游路由，不需要顶层状态字段）。
      - 其他               → 通用 {"error": msg} 写入 node_io。
    """
    if node_name == "blender_executor":
        from state.models import BlenderOutput

        output = BlenderOutput(
            blender_error=msg,
            retry_count=state.retry_count + 1,
        )
        state.node_io[node_name]["output"] = json.loads(output.model_dump_json())
        print(f"[NODE IO] blender_executor 失败: {msg[:200]}")
        return {
            "node_io": state.node_io,
            "blender_error": output.blender_error,
            "retry_count": output.retry_count,
        }

    elif node_name == "sdxl_enhancer":
        from state.models import SDXLEnhancerOutput

        prompt_id = extra.get("prompt_id", "")
        output = SDXLEnhancerOutput(
            prompt_id=prompt_id,
            final_image_path="",
            sdxl_error=msg,
        )
        # 保留已设置的 input，只更新 output
        existing_input = state.node_io.get(node_name, {}).get("input", {})
        state.node_io[node_name] = {
            "input": existing_input,
            "output": json.loads(output.model_dump_json()),
        }
        print(f"[NODE IO] sdxl_enhancer 失败: {msg[:300]}")
        return {"node_io": state.node_io}

    else:
        # 通用回退 — 其他节点
        existing_input = state.node_io.get(node_name, {}).get("input", {})
        state.node_io[node_name] = {
            "input": existing_input,
            "output": {"error": msg},
        }
        print(f"[NODE IO] {node_name} 失败: {msg[:300]}")
        return {"node_io": state.node_io}
