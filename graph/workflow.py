"""LangGraph 工作流 — 5 节点管线。

数据流:
    START → text_expander → sdxl_prompt_gen → coder_agent → blender_executor
                                                                   │
                                                        ┌── 错误且重试<3 ──→ coder_agent (带错误JSON)
                                                        │
                                                        └── 成功 ──→ sdxl_enhancer → END

SDXL 提示词在 sdxl_prompt_gen 中独立生成，与 Blender 脚本并行处理。
Blender 重试不会重新生成 SDXL 提示词。
"""

from langgraph.graph import StateGraph, END
from state.schema import WorkflowState
from agents import text_expander, coder_agent, sdxl_prompt_gen, blender_executor, sdxl_enhancer
from config import config


def _route_after_blender(state: WorkflowState) -> str:
    """条件边：根据 Blender 输出的 error 字段决定下一步。"""
    blender_output = state.get_node_output("blender_executor")

    if not blender_output:
        return "error"

    if blender_output.get("blender_error") is None:
        return "continue"
    elif state.retry_count < config.BLENDER_MAX_RETRIES:
        return "retry"
    else:
        return "error"


def build_graph() -> StateGraph:
    """构建工作流并编译。"""

    graph = StateGraph(WorkflowState)

    # 注册节点
    graph.add_node("text_expander", text_expander)
    graph.add_node("sdxl_prompt_gen", sdxl_prompt_gen)
    graph.add_node("coder_agent", coder_agent)
    graph.add_node("blender_executor", blender_executor)
    graph.add_node("sdxl_enhancer", sdxl_enhancer)

    # 固定边
    graph.set_entry_point("text_expander")
    graph.add_edge("text_expander", "sdxl_prompt_gen")
    graph.add_edge("sdxl_prompt_gen", "coder_agent")
    graph.add_edge("coder_agent", "blender_executor")
    graph.add_edge("sdxl_enhancer", END)

    # 条件边：blender_executor → 三个分支
    graph.add_conditional_edges(
        "blender_executor",
        _route_after_blender,
        {
            "continue": "sdxl_enhancer",
            "retry": "coder_agent",
            "error": END,
        },
    )

    return graph


app = build_graph().compile()
