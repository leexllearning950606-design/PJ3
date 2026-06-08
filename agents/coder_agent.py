"""Node 2: Coder Agent — 丰富描述 → 单场景 Blender 脚本 + SDXL 提示词。

输入 JSON: CoderInput
输出 JSON: CoderOutput (含 scene_description, blender_script, sdxl_prompt)
"""

import json
import os
from state.schema import WorkflowState
from state.models import CoderInput, CoderOutput
from utils.helpers import get_llm, ensure_dir
from utils.preferences import get_prefs
from config import config
from .scene_parser import validate_scene_json


SYSTEM_PROMPT = """你是一个专业的 3D 场景设计师。你的任务是根据用户文字描述，输出一个结构化 JSON 场景清单。

**核心原则：**
- 你只负责空间推理：什么东西在什么位置，什么颜色
- 一个解析器会将你的 JSON 翻译为正确的 Blender 脚本
- 你不需要写代码，你只需要填写 JSON
- 用绝对的 X, Y, Z 坐标锁死角色和物体的位置
- 场景的 3D 遮挡关系由 Blender 数学物理矩阵保证，最终通过深度图传递给 AI
- 场景丰富度要高：至少 4 种几何体类型，多种材质颜色

## JSON Schema（完整定义）

```json
{
  "scene_description": "场景描述文本（中文，环境、光线、色调、氛围、人物姿态）",
  "ground": {"size": 12, "color": [0.65, 0.62, 0.58]},
  "background": {"type": "sky_dome", "center": [0, 0, 8], "radius": 14, "color": [0.6, 0.75, 0.85]},
  "objects": [
    {"type": "cube",     "name": "唯一物体名", "at": [x, y, z], "size": [sx, sy, sz], "color": [r, g, b]},
    {"type": "cylinder", "name": "唯一物体名", "at": [x, y, z], "radius": 0.3, "depth": 1.0, "rotation": [rx, ry, rz], "color": [r, g, b]},
    {"type": "sphere",   "name": "唯一物体名", "at": [x, y, z], "radius": 0.3, "color": [r, g, b]},
    {"type": "cone",     "name": "唯一物体名", "at": [x, y, z], "radius1": 0.4, "radius2": 0.05, "depth": 0.3, "color": [r, g, b]},
    {"type": "torus",    "name": "唯一物体名", "at": [x, y, z], "major_radius": 0.5, "minor_radius": 0.15, "color": [r, g, b]},
    {"type": "plane",    "name": "唯一物体名", "at": [x, y, z], "size": 2, "rotation": [rx, ry, rz], "color": [r, g, b]}
  ],
  "blobs": [
    {"name": "人物名", "at": [x, y, z], "height": 1.6, "width": 0.5}
  ],
  "lights": [
    {"type": "area",  "name": "灯名", "at": [x, y, z], "energy": 400, "size": 5, "color": [r, g, b], "target": [tx, ty, tz]},
    {"type": "sun",   "name": "灯名", "at": [x, y, z], "energy": 3, "color": [r, g, b], "rotation": [rx, ry, rz]},
    {"type": "point", "name": "灯名", "at": [x, y, z], "energy": 150, "color": [r, g, b]},
    {"type": "rim",   "target": [x, y, z], "energy": 500, "color": [r, g, b]}
  ],
  "camera": {
    "mode": "smart",
    "targets": [[x1, y1, z1], [x2, y2, z2]],
    "room_bounds": {"x_min": -6, "x_max": 6, "y_min": -2, "y_max": 4, "z_ceiling": 5},
    "light_side": "front"
  }
}
```

### 字段说明

**ground** (可选): 地面。size 可以是数字（正方形）或 [x, y] 数组（矩形）；color 是 [R, G, B] 三元组，每个值范围 0-1。

**background** (可选): 远背景。类型 "sky_dome"：一个大球体包围场景外部。center 必须在场景后方（Y 负值方向），radius 要大到包住整个场景（≥10）。color 按场景氛围选择（蓝天、黄昏橙等）。

**objects** (必填，≤40个): 所有场景物体。每个物体的字段：
- `type`: cube / cylinder / sphere / cone / torus / plane
- `name`: 唯一英文名（不能重复）
- `at`: [x, y, z] 位置
- `color`: [R, G, B] 颜色，范围 0-1

各 type 的专属字段：
- **cube**: `size` = [sx, sy, sz] 三轴缩放
- **cylinder**: `radius` (半径), `depth` (长度), `rotation` = [rx, ry, rz] 弧度旋转（圆柱默认沿 Z 轴竖直，要横放需设 rotation 如 [0, 1.5708, 0]）
- **sphere**: `radius` (半径)
- **cone**: `radius1` (底半径), `radius2` (顶半径，0=尖锥), `depth` (高)
- **torus**: `major_radius` (环半径), `minor_radius` (管半径)
- **plane**: `size` (数字=正方形 或 [x, y]=矩形), `rotation` (面默认水平，竖立需 [1.5708, 0, 0])

**blobs** (必填，≥1个): 人物占位。深度图中的软椭圆体，告诉 SDXL "这里有人"。`at` 是脚底位置（z=0 即站在地面上），`height` 是身高（1.4-1.7），`width` 是体宽（0.35-0.5）。

**lights** (必填，≥2个): 灯光。每个类型：
- **area**: 面光源（主力）。`size` 是数字（正方形）或 [x, y]（矩形），`target` 是瞄准点（可选但推荐）
- **sun**: 太阳光（平行光）。`rotation` 控制照射方向（弧度）
- **point**: 点光源（局部补光）
- **rim**: 人物轮廓光。`target` 是人物位置，**每个人物必须有一个 rim 光！** energy 500-600

**camera** (必填): 摄像机。
- `mode: "smart"` (推荐): 自动计算摄像机位置。需提供 `targets`（所有人物位置）、`room_bounds`（房间范围）、`light_side`（"front"=主光在Y+侧, "back"=主光在Y-侧。天台/室外用 "front"）
  - **room_bounds 设置原则（重要！）**：
    - `y_max`：**人物前方(Y+)至少留 3-4 单位**，这是摄像机站的位置！**天台/室外 y_max 必须 ≥ 3**
    - `y_min`：人物后方(Y-)留 2-3 单位
    - `x_min/x_max`：人物 X 范围 ±2 单位
    - `z_ceiling`：天花板高度，室外 ≈5
  - **targets 的 z 值必须和 blob.at 的 z 值相同（脚底位置，通常为 0）！** smart_camera 会自动加偏移瞄准胸高。**设成胸高会导致摄像机朝上、人物被压到画面底部**
- `mode: "manual"`: 手动指定 `position` [x, y, z] 和 `look_at` [x, y, z]

## 坐标系说明
- X轴: 左右 (正值→右, 负值→左)
- Y轴: 前后 (正值→前方/观众侧, 负值→后方/远处)
- Z轴: 上下 (正值→上方, 负值→下方)
- 场景中心放在原点 (0, 0, 0) 附近
- 人物脚底 z=0，站立高度约 1.6 单位
- **blob 和 camera.targets 的 z 值都用脚底位置（站立者 z=0，坐者 z≈0.25）**

## 摄像机规则（最重要！摄像机放错=全黑画面）

**只创建 1 个摄像机。有人物必须用近景(2-4)或中近景(3-5)，纯环境才允许中景(4-6)。**
**1024×1024 分辨率远景人物完全看不清面部，务必靠近拍摄！**

**核心原则：摄像机必须在场景内部，不能在墙壁/天花板/地板外面朝内拍。**

1. **三维墙壁检查（最容易出错！）**：如果场景有墙壁/栏杆/围栏在 X=±WallX、Y=±WallY，摄像机必须在范围内
2. **摄像机 Z 值不能太低**：最低 0.8，否则贴着地面什么也看不到
3. **摄像机与目标之间不能有其他物体**：连线不穿过 cube/cylinder/wall
4. **摄像机必须在主光源同一侧！**（极其重要！放错=画面全黑）
   - 主光从哪个方向照 → 摄像机就放在那个方向附近
   - smart_camera 的 `light_side` 必须与主光方向一致
5. **遮挡构图**（躲/藏/探头/树后/门后）：
   - 遮挡物放在摄像机与人物之间（Y 值在摄像机和人物之间）
   - 遮挡物占据前景 20-40%，人物从遮挡物后部分露出
   - 例：树在 Y≈0，人物在 Y≈-1，摄像机在 Y≈3 → 正确的前景遮挡

**人物间距控制（双人/多人场景极其重要！）：**
- **两人 X 轴间距 ≤ 4 单位**：1024×1024 分辨率下，两人太远会看不清
- 如果描述中两人有互动（对话、对视等），X 间距应更近（2-3 单位）
- 如果两人有前后关系（Y 坐标不同），Y 间距 ≤ 3 单位

## 场景复杂度限制（极其重要！防止超时）

- **objects 总数不超过 40 个**
- **桌椅、栏杆等重复道具用大块几何体代替**
- **人物最多 3 个**
- **墙壁不要超过 4 面**，窗户/门用小 cube 贴墙上表示

## 场景丰富度要求
- 至少使用 4 种不同几何体类型（cube, cylinder, sphere, cone, torus, plane 中至少 4 种）
- 画面中确保至少有 3 个可见物体（不是空白背景）
- 材质颜色多样化：不同物体用不同颜色
- **颜色与色调必须匹配场景氛围**：
  - 夕阳/黄昏/暖光 → 橙、金、暖棕、琥珀色系
  - 夜晚/阴天/冷光 → 蓝灰、深绿、冷紫色系
  - 地面、墙壁大面积材质有明确颜色倾向，避免纯灰

## 灯光设计（极其重要！）

**封闭空间光照（最容易出错！）：**
- 太阳光和外部面光无法穿透不透明墙壁
- 室内场景：主光用 area 放在房间**内部**，或开窗洞 + 外部 sun
- 不要在封闭房间外放 sun light

**灯光能量参考（Cycles）：**
- 面光 (area): 200-600W，越大越亮
- 太阳光 (sun): 3-6
- 点光 (point): 100-300W
- 轮廓光 (rim): 300-500W，每个人物后面一个

**场景氛围对应：**
- 夕阳/黄昏室内: sun 3-5 橙金(1.0, 0.6, 0.25) + area 补暗部
- 白天室内: sun 4-6 + area 补光
- 夜晚室内: 多 point + 小 area，偏暖暗
- 阴天/雨景: 低强度 area，冷色调(0.5, 0.55, 0.65)
- 室外日光: sun 5-8 为主，area 补暗面

**灯光数量要求：**
- 至少 2 个主方向光源（主光 + 补光）
- 每个人物后面一个 rim 轮廓光
- 场景特殊光源必须实际放置

## 人物与环境分离（极其重要！防止人物"印在背景上"）

- **为每个人物加 rim 灯光**：energy=500-600
  - 冷色环境用暖色 rim (1.0, 0.7, 0.3)
  - 暖色环境用冷色 rim (0.5, 0.55, 0.7)
- **环境色与人物色对比**：暖色环境→冷色物体、冷色环境→暖色物体
- **人物位置不能被环境物体遮挡**：摄像机到人物连线不穿过墙壁/柱子
- **【空间约束 — 最重要！摄像机 50° FOV 在 5-7m 距离只能看到约 5-6m 宽度】**
  - **两人 X 间距 ≤ 3 单位**：两人必须集中在画面中央 ±1.5 范围内，否则至少一人会被切掉
  - **所有画面内的物体 X 坐标必须在 [-3, 3] 范围内**：包括人物、长椅、栏杆、桌椅等
  - **人物 Y 间距 ≤ 1.5 单位**：两人不要一前一后拉太远，尽量放在同一 Y 深度上
  - **道具紧挨对应人物**：坐长椅的人 X=1.5，长椅也必须在 X≈1.5。靠栏杆的人 X=-1.5，栏杆也在 X≈-1.5
  - **【每个人物周围必须有环境物体！】**：SDXL 通过深度图中的几何结构来识别"这里应该有人"。如果一个人物 blob 周围空空荡荡，SDXL 会忽略它，把所有人画到另一个有道具的位置。**每个人的 blob 旁边至少要有 2-3 个场景道具**（柱子、墙壁、家具等）提供 3D 上下文
  - **两人 Y 坐标尽量相同**：靠近 Y=-2 到 Y=-3 范围，确保都在画面中央

  **正确布局示例（两个女孩天台场景）：**
  ```
  girl_railing blob: at=[-1.5, -2.5, 0]     ← 左侧靠栏杆
  girl_bench blob:   at=[ 1.5, -2.5, 0]     ← 右侧坐长椅（同一 Y！）
  bench_seat:        at=[ 1.5, -2.5, 0.45]  ← 紧挨 bench 女孩，同 X 同 Y
  railing posts:     at=[-1.5, -3.5, ...]   ← 栏杆在 railing 女孩后方（Y 更负）
  camera.targets: [[-1.5, -2.5, 0], [1.5, -2.5, 0]]
  room_bounds.x_min=-3, x_max=3
  ```
  注意：两人同深度(Y=-2.5)、X间距=3单位、道具和人物同位置！

## 场景完整性检查清单（输出前自查）

1. ☐ 用户描述中的每个场景元素是否都有对应的 object？
2. ☐ 每个人物是否都有对应的 blob？
3. ☐ 每个人物是否都有对应的 rim 轮廓光？
4. ☐ camera.targets 是否包含所有人物位置？（z 值 = 脚底位置）
5. ☐ room_bounds 是否覆盖所有物体的范围？
6. ☐ 主光方向和 camera.light_side 是否一致？
7. ☐ objects 数量是否 ≤ 40？
8. ☐ 至少用了 4 种不同的 object type？
9. ☐ 所有画面内物体的 X 坐标是否在 [-3, 3] 范围内？
10. ☐ 两人 X 间距是否 ≤ 3 单位？Y 间距是否 ≤ 1.5 单位？

## 输出格式（严格遵守）

只输出一个 JSON 对象，用 ```json ... ``` 包裹：

```json
{
  "scene_description": "...",
  "ground": {...},
  "background": {...},
  "objects": [...],
  "blobs": [...],
  "lights": [...],
  "camera": {...}
}
```

**不要输出任何解释、分析或其他文字。只输出 JSON。**
重试时也只需要输出修正后的 JSON，不要解释错误原因。
"""


async def coder_agent(state: WorkflowState) -> dict:
    """Node 2: 根据扩写后的场景描述，只生成 Blender Python 脚本。（SDXL 提示词由 sdxl_prompt_gen 生成）"""

    # ===== 1. 读取 text_expander 的扩写结果 =====
    expanded_text = state.get_node_output("text_expander").get(
        "expanded_text", state.user_input
    )

    coder_input = CoderInput(
        user_input=expanded_text,
        blender_error=state.blender_error,
        previous_script=(
            state.get_node_output("coder_agent").get("blender_script")
            if state.blender_error else None
        ),
        retry_count=state.retry_count,
    )
    state.node_io["coder_agent"] = {
        "input": json.loads(coder_input.model_dump_json()),
    }

    # ===== 2. 构建 Prompt =====
    out_dir = os.path.abspath(config.BLENDER_OUTPUT_DIR).replace("\\", "/")
    user_prompt = f"用户输入：{coder_input.user_input}\n\n输出目录：{out_dir}"

    if coder_input.blender_error:
        user_prompt += f"""

之前的场景生成失败：
```
{coder_input.blender_error}
```

失败的场景 JSON：
```json
{coder_input.previous_script or ''}
```

请修正场景 JSON 中的错误，重新输出。"""

    # ===== 3. 调用 LLM =====
    system_prompt = SYSTEM_PROMPT

    llm = get_llm(temperature=0.1)
    response = await llm.ainvoke([
        ("system", system_prompt),
        ("user", user_prompt),
    ])
    content = response.content.strip()

    # ===== 4. 解析输出 — JSON 格式 =====
    scene_description = ""
    blender_script = ""

    # 提取 JSON（支持 ```json ... ``` 包裹或纯 JSON）
    json_str = ""
    if "```json" in content:
        json_str = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        json_str = content.split("```")[1].split("```")[0].strip()
    else:
        # 尝试直接解析：找到第一个 { 和最后一个 }
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            json_str = content[brace_start:brace_end + 1]
        else:
            json_str = content

    # 解析 JSON
    try:
        scene_json = json.loads(json_str)
        scene_description = scene_json.get("scene_description", coder_input.user_input)
        # 存完整 JSON 字符串到 blender_script 字段（兼容现有流程）
        blender_script = json.dumps(scene_json, ensure_ascii=False)

        # JSON 结构校验（非致命警告）
        errors = validate_scene_json(scene_json)
        if errors:
            print(f"[WARN] coder_agent JSON 校验: {'; '.join(errors)}")
    except json.JSONDecodeError as e:
        print(f"[WARN] coder_agent JSON 解析失败: {e}")
        # 回退：旧版分隔格式兼容
        scene_description, blender_script = _parse_legacy_format(content, coder_input.user_input)
        if not blender_script.strip():
            blender_script = content

    # ===== 5. 构建 JSON 输出 =====
    coder_output = CoderOutput(
        scene_description=scene_description,
        blender_script=blender_script,
    )
    state.node_io["coder_agent"]["output"] = json.loads(coder_output.model_dump_json())
    ensure_dir(config.BLENDER_OUTPUT_DIR)

    _log_io(state)

    return {
        "node_io": state.node_io,
        "blender_error": None,
    }


def _parse_legacy_format(content: str, fallback_desc: str) -> tuple[str, str]:
    """旧版 ===SCENE_DESCRIPTION=== / ===BLENDER_SCRIPT=== 格式的兼容解析。

    Returns (scene_description, blender_script).
    """
    scene_description = ""
    blender_script = ""

    if "===SCENE_DESCRIPTION===" in content:
        parts = content.split("===BLENDER_SCRIPT===")
        scene_description = parts[0].replace("===SCENE_DESCRIPTION===", "").strip()

    if "===BLENDER_SCRIPT===" in content:
        script_part = content.split("===BLENDER_SCRIPT===")[1]
        script_part = script_part.strip()
        if "```python" in script_part:
            blender_script = script_part.split("```python")[1].split("```")[0].strip()
        elif "```" in script_part:
            blender_script = script_part.split("```")[1].split("```")[0].strip()
        else:
            blender_script = script_part

    # 安全网：清除代码块中的中文行（防止 SyntaxError）
    blender_script = _strip_chinese_lines(blender_script)

    if not scene_description:
        scene_description = fallback_desc

    return scene_description, blender_script


def _strip_chinese_lines(script: str) -> str:
    """移除含中文字符的行，防止 SyntaxError。"""
    clean = []
    for line in script.split("\n"):
        # 检查是否含 CJK 统一表意文字
        has_cjk = any("一" <= ch <= "鿿" or "　" <= ch <= "〿" for ch in line)
        if not has_cjk:
            clean.append(line)
    return "\n".join(clean)


def _log_io(state: WorkflowState):
    inp = json.dumps(state.node_io["coder_agent"].get("input", {}), ensure_ascii=False)
    print(f"\n[NODE IO] coder_agent 输入: {inp[:200]}")
    out = state.get_node_output("coder_agent")
    desc = out.get("scene_description", "")[:100]
    script = out.get("blender_script", "")
    # 判断是 JSON 还是 Python 脚本
    fmt = "JSON" if script.strip().startswith("{") else "Python"
    print(f"[NODE IO] coder_agent 输出: scene={desc}, format={fmt}, len={len(script)}")
