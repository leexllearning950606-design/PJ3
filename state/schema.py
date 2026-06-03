"""WorkflowState — Blender + SDXL 图片生成数据流。"""

import json
from dataclasses import dataclass, field
from typing import Optional, Annotated, Any
from langgraph.graph.message import add_messages


@dataclass
class WorkflowState:
    """Blender + SDXL 图片生成工作流状态。

    数据流设计：
    用户输入 → 扩写丰富描述 → Blender 脚本 + SDXL 提示词 → 深度图渲染 → SDXL ControlNet 增强

    每个节点的 JSON I/O 存储在 node_io 字典中。
    """

    # ==================== 用户输入 ====================
    user_input: str = ""

    # ==================== 节点 JSON I/O 追踪 ====================
    node_io: dict[str, Any] = field(default_factory=dict)
    """结构:
    {
      "text_expander":    { "input": {...}, "output": {...} },
      "coder_agent":      { "input": {...}, "output": {...} },
      "blender_executor": { "input": {...}, "output": {...} },
      "sdxl_enhancer":    { "input": {...}, "output": {...} }
    }
    """

    # ==================== 条件路由 ====================
    blender_error: Optional[str] = None
    retry_count: int = 0

    # ==================== 最终输出 ====================
    final_image_path: str = ""
    error_message: str = ""

    # ==================== 消息日志 ====================
    messages: Annotated[list, add_messages] = field(default_factory=list)

    # ==================== JSON 工具方法 ====================

    def get_node_input(self, node_name: str) -> dict:
        return self.node_io.get(node_name, {}).get("input", {})

    def get_node_output(self, node_name: str) -> dict:
        return self.node_io.get(node_name, {}).get("output", {})

    def get_previous_output(self) -> dict:
        nodes_order = [
            "text_expander", "coder_agent",
            "blender_executor", "sdxl_enhancer",
        ]
        for node in reversed(nodes_order):
            output = self.get_node_output(node)
            if output:
                return output
        return {}

    def dump_json(self) -> str:
        return json.dumps(
            {
                "user_input": self.user_input,
                "node_io": self.node_io,
                "retry_count": self.retry_count,
                "final_image_path": self.final_image_path,
                "error_message": self.error_message,
            },
            ensure_ascii=False,
            indent=2,
        )
