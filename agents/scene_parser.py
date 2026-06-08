"""JSON 场景清单 → Blender Python 脚本的确定性翻译器。

LLM 只负责空间推理（"什么东西在什么位置"），输出结构化 JSON。
本模块将 JSON 机械翻译为正确的 Blender helper 调用，零 AI 参与。

所有 Blender 坐标系细节（圆柱默认轴向、cube 对齐、Track To 约束等）
在本模块中一次性正确处理，LLM 完全不感知。
"""

import json
import os


# ===========================
# 校验
# ===========================

def validate_scene_json(scene_json: dict) -> list[str]:
    """校验场景 JSON 结构，返回问题列表（空 = 通过）。"""
    issues = []

    # blobs 至少 1 个
    blobs = scene_json.get("blobs", [])
    if not blobs:
        issues.append("缺少 blobs：至少需要 1 个人物占位 blob")

    # objects 数量限制
    objects = scene_json.get("objects", [])
    if len(objects) > 40:
        issues.append(f"objects 数量 {len(objects)} > 40，场景太复杂")

    # 每个 object 的 at 是 3 元素
    for i, obj in enumerate(objects):
        name = obj.get("name", f"obj[{i}]")
        at = obj.get("at", [])
        if len(at) != 3:
            issues.append(f"物体 '{name}' 的 at 字段必须是 [x, y, z] 三元组，当前: {at}")
        obj_type = obj.get("type", "")
        if obj_type not in ("cube", "cylinder", "sphere", "cone", "torus", "plane"):
            issues.append(f"物体 '{name}' 的 type '{obj_type}' 不支持，支持: cube/cylinder/sphere/cone/torus/plane")

    # 每个 blob 的 at 是 3 元素
    for i, blob in enumerate(blobs):
        name = blob.get("name", f"blob[{i}]")
        at = blob.get("at", [])
        if len(at) != 3:
            issues.append(f"人物 '{name}' 的 at 字段必须是 [x, y, z] 三元组")

    # camera 必填
    camera = scene_json.get("camera")
    if not camera:
        issues.append("缺少 camera 字段")
    else:
        mode = camera.get("mode", "")
        if mode not in ("smart", "manual"):
            issues.append(f"camera.mode 必须是 'smart' 或 'manual'，当前: '{mode}'")
        if mode == "smart":
            targets = camera.get("targets", [])
            if not targets:
                issues.append("camera.mode='smart' 时 targets 不能为空")
            bounds = camera.get("room_bounds")
            if not bounds:
                issues.append("camera.mode='smart' 时 room_bounds 不能为空")
            else:
                for key in ("x_min", "x_max", "y_min", "y_max", "z_ceiling"):
                    if key not in bounds:
                        issues.append(f"camera.room_bounds 缺少 '{key}'")
        if mode == "manual":
            pos = camera.get("position")
            look = camera.get("look_at")
            if not pos or len(pos) != 3:
                issues.append("camera.mode='manual' 时 position 必须是 [x, y, z]")
            if not look or len(look) != 3:
                issues.append("camera.mode='manual' 时 look_at 必须是 [x, y, z]")

    # lights 校验
    for i, light in enumerate(scene_json.get("lights", [])):
        lt = light.get("type", "")
        if lt not in ("area", "sun", "point", "rim"):
            issues.append(f"灯光[{i}] type '{lt}' 不支持，支持: area/sun/point/rim")

    # 空间约束校验（防止人物出画）
    _check_spatial_constraints(scene_json, issues)

    return issues


def _check_spatial_constraints(scene_json: dict, issues: list[str]):
    """校验人物和关键物体的空间布局在摄像机 FOV 内。"""
    blobs = scene_json.get("blobs", [])
    camera = scene_json.get("camera", {})
    targets = camera.get("targets", [])

    if len(blobs) < 2 or len(targets) < 2:
        return

    # 计算 targets 的中心和散布
    tx_coords = [(t[0], t[1]) for t in targets if len(t) >= 2]
    if len(tx_coords) < 2:
        return

    xs = [t[0] for t in tx_coords]
    ys = [t[1] for t in tx_coords]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)

    if x_span > 4.5:
        issues.append(
            f"camera.targets 的 X 间距为 {x_span:.1f} 单位（超过 4.5）。"
            f"摄像机 50° FOV 无法同时拍到两人。将两人 X 坐标靠近到 ≤3 单位"
        )
    if y_span > 2.5:
        issues.append(
            f"camera.targets 的 Y 间距为 {y_span:.1f} 单位（超过 2.5）。"
            f"两人前后距离太大，至少一人会失焦或出画。将两人放到同一 Y 深度"
        )

    # 检查 blob 是否和对应 target 位置一致
    for blob in blobs:
        bx, by = blob["at"][0], blob["at"][1]
        name = blob.get("name", "?")
        # 检查 X 是否在画面中心 ±4 范围内（保守）
        center_x = sum(xs) / len(xs)
        if abs(bx - center_x) > 4.5:
            issues.append(
                f"人物 '{name}' X={bx:.1f} 距画面中心 {center_x:.1f} 太远（>{4.5}），会被切掉。"
                f"将 X 移到 [{center_x-3:.0f}, {center_x+3:.0f}] 范围内"
            )

    # 检查 camera.targets 的 z 是否合理（应为脚底高度，0~0.5）
    for i, t in enumerate(targets):
        if len(t) >= 3 and t[2] > 1.0:
            issues.append(
                f"camera.targets[{i}] 的 z={t[2]} 太高，应该用脚底位置（通常 z=0 或坐姿 z≈0.25），"
                f"不要用胸高。z 值过高会导致摄像机朝上、人物被压到画面底部"
            )


# ===========================
# 脚本生成
# ===========================

def parse_scene_json(scene_json: dict, output_dir: str) -> str:
    """JSON 场景描述 → Blender Python 脚本字符串。

    Args:
        scene_json: LLM 输出的场景 JSON
        output_dir: Blender 渲染输出目录

    Returns:
        完整的 Blender Python 脚本（已包含 helper import 不重复的纯代码）
    """
    lines: list[str] = []

    # 1. 清理
    lines.append("clear_scene()")
    lines.append("")

    # 2. 地面
    ground = scene_json.get("ground")
    if ground:
        size = ground.get("size", 12)
        color = ground.get("color", [0.5, 0.5, 0.5])
        lines.append(f"# Ground")
        lines.append(f"ground = add_plane(\"Ground\", (0, 0, 0), size={_size_val(size)})")
        lines.append(f"apply_material(ground, make_material(\"GroundMat\", {_rgb(color)}, roughness=0.85))")
        lines.append("")

    # 3. 背景
    bg = scene_json.get("background")
    if bg:
        _emit_background(lines, bg)

    # 4. 场景物体
    objects = scene_json.get("objects", [])
    if objects:
        lines.append(f"# Scene objects ({len(objects)} total)")
        for obj in objects:
            _emit_object(lines, obj)
        lines.append("")

    # 5. 人物 blobs
    blobs = scene_json.get("blobs", [])
    if blobs:
        lines.append(f"# Character blobs ({len(blobs)} total)")
        for blob in blobs:
            _emit_blob(lines, blob)
        lines.append("")

    # 6. 灯光
    lights = scene_json.get("lights", [])
    if lights:
        lines.append(f"# Lighting ({len(lights)} total)")
        lines.append("setup_lighting()")
        for light in lights:
            _emit_light(lines, light)
        lines.append("")

    # 7. 摄像机
    camera = scene_json.get("camera", {})
    _emit_camera(lines, camera)

    # 8. 渲染
    out = output_dir.replace("\\", "/")
    lines.append(f"# Render")
    lines.append(f'output_dir = "{out}"')
    lines.append(f'setup_render(output_dir, res_x=1024, res_y=1024, engine="CYCLES")')
    lines.append(f'render_all(cameras, output_dir)')

    return "\n".join(lines)


# ===========================
# 内部发射器
# ===========================

def _emit_background(lines: list[str], bg: dict):
    """发射背景（sky_dome 等）。"""
    bg_type = bg.get("type", "sky_dome")
    lines.append(f"# Background: {bg_type}")
    if bg_type == "sky_dome":
        center = bg.get("center", [0, 0, 8])
        radius = bg.get("radius", 12)
        color = bg.get("color", [0.6, 0.75, 0.85])
        lines.append(
            f"sky = add_sphere(\"SkyDome\", ({center[0]},{center[1]},{center[2]}), radius={radius})"
        )
        lines.append(
            f"apply_material(sky, make_material(\"SkyMat\", {_rgb(color)}, "
            f"roughness=1.0, emission=0.3, emission_color={_rgb(color)}))"
        )
    lines.append("")


def _emit_object(lines: list[str], obj: dict):
    """发射单个场景物体。"""
    name = obj["name"]
    obj_type = obj["type"]
    at = obj.get("at", [0, 0, 0])
    color = obj.get("color", [0.5, 0.5, 0.5])

    if obj_type == "cube":
        size = obj.get("size", [1, 1, 1])
        lines.append(
            f'{name} = add_cube("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'scale=({size[0]},{size[1]},{size[2]}))'
        )
    elif obj_type == "cylinder":
        radius = obj.get("radius", 0.3)
        depth = obj.get("depth", 1.0)
        lines.append(
            f'{name} = add_cylinder("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'radius={radius}, depth={depth})'
        )
    elif obj_type == "sphere":
        radius = obj.get("radius", 0.3)
        lines.append(
            f'{name} = add_sphere("{name}", ({at[0]},{at[1]},{at[2]}), radius={radius})'
        )
    elif obj_type == "cone":
        r1 = obj.get("radius1", 0.4)
        r2 = obj.get("radius2", 0.05)
        depth = obj.get("depth", 0.3)
        lines.append(
            f'{name} = add_cone("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'radius1={r1}, radius2={r2}, depth={depth})'
        )
    elif obj_type == "torus":
        major_r = obj.get("major_radius", 0.5)
        minor_r = obj.get("minor_radius", 0.15)
        lines.append(
            f'{name} = add_torus("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'major_radius={major_r}, minor_radius={minor_r})'
        )
    elif obj_type == "plane":
        size = obj.get("size", 2)
        lines.append(
            f'{name} = add_plane("{name}", ({at[0]},{at[1]},{at[2]}), size={_size_val(size)})'
        )

    # 旋转（LLM 只需填弧度，解析器负责正确的 rotation_euler 调用）
    rot = obj.get("rotation", [0, 0, 0])
    if rot[0] != 0 or rot[1] != 0 or rot[2] != 0:
        lines.append(f'{name}.rotation_euler = ({rot[0]}, {rot[1]}, {rot[2]})')

    # 材质
    lines.append(
        f'apply_material({name}, make_material("Mat_{name}", {_rgb(color)}))'
    )


def _emit_blob(lines: list[str], blob: dict):
    """发射人物占位 blob。"""
    name = blob["name"]
    at = blob.get("at", [0, 0, 0])
    height = blob.get("height", 1.6)
    width = blob.get("width", 0.5)
    lines.append(
        f'add_depth_blob("{name}", ({at[0]},{at[1]},{at[2]}), '
        f'height={height}, width={width})'
    )


def _emit_light(lines: list[str], light: dict):
    """发射灯光。"""
    lt = light.get("type", "area")

    if lt == "area":
        name = light.get("name", "AreaLight")
        at = light.get("at", [0, 0, 3])
        energy = light.get("energy", 400)
        size = light.get("size", 5)
        color = light.get("color", [1, 1, 1])
        target = light.get("target")
        size_str = _size_val(size)
        target_str = f', target=({target[0]},{target[1]},{target[2]})' if target else ''
        lines.append(
            f'add_area_light("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'energy={energy}, size={size_str}, color={_rgb(color)}{target_str})'
        )
    elif lt == "sun":
        name = light.get("name", "SunLight")
        at = light.get("at", [0, 0, 10])
        energy = light.get("energy", 3)
        color = light.get("color", [1, 0.95, 0.8])
        rot = light.get("rotation", [0.6, 0, 1.2])
        lines.append(
            f'add_sun_light("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'energy={energy}, color={_rgb(color)}, rotation=({rot[0]},{rot[1]},{rot[2]}))'
        )
    elif lt == "point":
        name = light.get("name", "PointLight")
        at = light.get("at", [0, 0, 2])
        energy = light.get("energy", 150)
        color = light.get("color", [1, 1, 1])
        lines.append(
            f'add_point_light("{name}", ({at[0]},{at[1]},{at[2]}), '
            f'energy={energy}, color={_rgb(color)})'
        )
    elif lt == "rim":
        target = light.get("target", [0, 0, 0])
        energy = light.get("energy", 500)
        color = light.get("color", [0.6, 0.55, 0.5])
        lines.append(
            f'add_character_rim(({target[0]},{target[1]},{target[2]}), '
            f'energy={energy}, color={_rgb(color)})'
        )


def _emit_camera(lines: list[str], camera: dict):
    """发射摄像机设置。"""
    lines.append("# Camera")
    mode = camera.get("mode", "smart")

    if mode == "manual":
        pos = camera.get("position", [0, 3, 1.5])
        look = camera.get("look_at", [0, 0, 1])
        lines.append(
            f'cam = add_camera("MainCam", ({pos[0]},{pos[1]},{pos[2]}), '
            f'look_at=({look[0]},{look[1]},{look[2]}))'
        )
        lines.append('cameras = [cam]')
    else:
        # smart 模式（默认）
        targets = camera.get("targets", [[0, 0, 0]])
        bounds = camera.get("room_bounds", {
            "x_min": -2, "x_max": 2, "y_min": -2, "y_max": 2, "z_ceiling": 3
        })
        light_side = camera.get("light_side", "front")

        targets_str = json.dumps(targets)
        bounds_str = json.dumps(bounds)

        lines.append(f'room_bounds = {bounds_str}')
        lines.append(f'person_positions = {targets_str}')
        lines.append(
            f'cam = smart_camera("MainCam", person_positions, room_bounds, '
            f'light_side="{light_side}")'
        )
        lines.append('cameras = [cam]')

        # 如果 camera 指定了 override position / look_at
        override_pos = camera.get("override_position")
        override_look = camera.get("override_look_at")
        if override_pos and override_look:
            lines.append("# Override camera position (with proper constraint update)")
            lines.append(
                f'_set_camera_look_at(cam, ({override_look[0]},{override_look[1]},{override_look[2]}))'
            )
            lines.append(
                f'cam.location = ({override_pos[0]},{override_pos[1]},{override_pos[2]})'
            )

    lines.append("")


# ===========================
# 工具函数
# ===========================

def _rgb(color: list) -> str:
    """颜色数组 [r, g, b] → Python tuple 字符串 '(r, g, b)'。"""
    return f'({color[0]}, {color[1]}, {color[2]})'


def _size_val(size):
    """处理 size 字段：float/int（正方形面光/平面）或 list（矩形）。"""
    if isinstance(size, (int, float)):
        return str(size)
    elif isinstance(size, list):
        return f'({size[0]}, {size[1]})'
    return str(size)
