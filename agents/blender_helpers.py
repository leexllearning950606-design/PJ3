"""Blender 5.1 辅助函数 — 注入到生成的脚本之前运行。

提供经过测试的：
- 场景清理
- 材质创建（只设置安全的 Principled BSDF 属性）
- 几何体创建（只用 primitive_* 运算符）
- 灯光设置（三点照明 + 世界环境光，确保渲染不黑）
- 摄像机创建 + Track To 自动瞄准（无需手工计算旋转）
- 渲染循环
"""

import bpy
import math
import os as _bl_os


# ===========================
# 场景清理
# ===========================

def clear_scene():
    """安全清除场景中所有网格、灯光、摄像机对象。"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


# ===========================
# 材质
# ===========================

def _find_bsdf_node(node_tree):
    """在节点树中查找 Principled BSDF 节点（兼容不同语言/版本的节点名称）。"""
    for node in node_tree.nodes:
        if node.bl_idname == 'ShaderNodeBsdfPrincipled':
            return node
    # 没找到就创建一个新的
    bsdf = node_tree.nodes.new('ShaderNodeBsdfPrincipled')
    out = _find_output_node(node_tree)
    node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return bsdf


def _find_output_node(node_tree):
    """查找 Material Output 节点。"""
    for node in node_tree.nodes:
        if node.bl_idname == 'ShaderNodeOutputMaterial':
            return node
    return node_tree.nodes.new('ShaderNodeOutputMaterial')


def make_material(name, color, roughness=0.7, metallic=0.0, emission=0.0, emission_color=None):
    """创建 Principled BSDF 材质。color 为 (R, G, B) 元组，范围 0-1。"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = _find_bsdf_node(mat.node_tree)
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    if emission > 0:
        bsdf.inputs['Emission Strength'].default_value = emission
        ec = emission_color or color
        bsdf.inputs['Emission Color'].default_value = (*ec, 1)
    return mat


def apply_material(obj, mat):
    """将材质应用到对象。"""
    if obj.data and hasattr(obj.data, 'materials'):
        obj.data.materials.append(mat)


# ===========================
# 几何体
# ===========================

def add_cube(name, location, scale=(1, 1, 1)):
    """创建立方体。scale 为 (sx, sy, sz)。"""
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return obj


def add_plane(name, location, size=10):
    """创建水平平面（地面）。size 可以是 float（正方形）或 (x, y) 元组（矩形）。"""
    if isinstance(size, (tuple, list)):
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.scale = (size[0], size[1], 1.0)
        bpy.ops.object.transform_apply(scale=True)
    else:
        bpy.ops.mesh.primitive_plane_add(size=size, location=location)
        obj = bpy.context.object
        obj.name = name
    return obj


def add_cylinder(name, location, radius=0.3, depth=1.0):
    """创建圆柱体。"""
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def add_sphere(name, location, radius=0.3):
    """创建球体。"""
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def add_cone(name, location, radius1=0.4, radius2=0.05, depth=0.3):
    """创建圆锥体。"""
    bpy.ops.mesh.primitive_cone_add(
        radius1=radius1, radius2=radius2, depth=depth, location=location
    )
    obj = bpy.context.object
    obj.name = name
    return obj


def add_depth_blob(name_prefix, location, height=1.6, width=0.5):
    """在角色位置放一个简单椭球/圆柱体，为深度图提供人物占位。

    Animagine XL 根据深度图的软 blob 知道"这里有个人"，结合提示词自动生成角色。
    """
    x, y, z = location
    # 主体躯干（拉长椭球）
    body = add_sphere(f"{name_prefix}_Blob_Body", (x, y, z + height * 0.5), radius=width * 0.6)
    body.scale = (1.0, 0.7, height / (width * 1.2))
    # 头部（小球）
    head = add_sphere(f"{name_prefix}_Blob_Head", (x, y, z + height * 0.9), radius=width * 0.35)
    mat = make_material(f"{name_prefix}BlobMat", (0.5, 0.5, 0.5), roughness=1.0)
    apply_material(body, mat)
    apply_material(head, mat)
    return {"body": body, "head": head}


# ===========================
# 灯光
# ===========================

def setup_lighting():
    """设置极简世界环境光（仅防纯黑）。

    所有主光/补光/轮廓光由 LLM 根据场景描述自行搭建，
    使用 add_area_light / add_sun_light / add_point_light / add_character_rim。
    """
    world = bpy.data.worlds.new(name="World")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    bg = nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = 0.15
    bg.inputs['Color'].default_value = (0.04, 0.04, 0.05, 1)
    out = nodes.new('ShaderNodeOutputWorld')
    links.new(bg.outputs['Background'], out.inputs['Surface'])
    bpy.context.scene.world = world


def add_area_light(name, location, energy=400, size=5, color=(1, 1, 1), target=None):
    """创建面光源 — 主光/补光的主力工具。

    energy: Cycles 瓦特，面光 200-800 为合理范围
    target: 可选 (x,y,z)，灯光自动瞄准该点
    """
    bpy.ops.object.light_add(type='AREA', location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.energy = energy
    obj.data.size = size
    obj.data.color = color
    if target:
        _track_to(obj, target)
    return obj


def add_sun_light(name, location, energy=3, color=(1, 0.95, 0.8), rotation=(0.6, 0, 1.2)):
    """创建太阳光 — 平行光，适合模拟日光/月光。

    energy: Cycles 太阳光强度，3-8 为合理范围（比面光单位不同）
    rotation: (rx, ry, rz) 弧度，控制光照方向
    """
    bpy.ops.object.light_add(type='SUN', location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.energy = energy
    obj.data.color = color
    obj.rotation_euler = rotation
    return obj


def add_point_light(name, location, energy=150, color=(1, 1, 1)):
    """创建点光源（用于局部补光，如灯笼、烛光）。"""
    bpy.ops.object.light_add(type='POINT', location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.energy = energy
    obj.data.color = color
    return obj


def add_character_rim(target_xyz, energy=500, color=(0.6, 0.55, 0.5)):
    """在目标后方放置轮廓光，分离人物与背景。

    光源自动放置在 target_xyz 后方（Y轴-方向）偏上。
    用于每个人物，确保主体从背景中凸显出来。
    """
    x, y, z = target_xyz
    rim_loc = (x, y - 2.5, z + 2.0)
    bpy.ops.object.light_add(type='AREA', location=rim_loc)
    light = bpy.context.object
    light.name = "CharRimLight"
    light.data.energy = energy
    light.data.size = 2
    light.data.color = color
    _track_to(light, target_xyz)
    return light


def _track_to(obj, target_xyz):
    """创建 Track To 约束，让灯光/摄像机自动瞄准目标。"""
    empty = bpy.data.objects.new(f"{obj.name}_target", None)
    bpy.context.collection.objects.link(empty)
    empty.location = target_xyz
    empty.empty_display_type = 'PLAIN_AXES'

    cons = obj.constraints.new(type='TRACK_TO')
    cons.target = empty
    cons.track_axis = 'TRACK_NEGATIVE_Z'
    cons.up_axis = 'UP_Y'


# ===========================
# 摄像机
# ===========================

def add_camera(name, location, look_at=(0, 0, 1.5)):
    """创建摄像机并用 Track To 约束自动瞄准目标点。

    location: 摄像机位置 (x, y, z)
    look_at: 看向的目标点 (x, y, z)，默认看向场景中央略高
    """
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.object
    cam.name = name
    _track_to(cam, look_at)
    return cam


def smart_camera(name, targets, room_bounds, light_side="front"):
    """自动计算摄像机位置，确保所有目标都在视野内。

    targets: [(x, y, z), ...] 所有人物的位置
    room_bounds: dict with keys 'x_min', 'x_max', 'y_min', 'y_max', 'z_ceiling'
    light_side: 'front' (Y+) or 'back' (Y-) — 摄像机放在主光同侧

    返回 cam 对象（已添加到 cameras 列表的场景中）。
    """
    import math

    # 1. 计算所有目标的中心点
    n = len(targets)
    cx = sum(t[0] for t in targets) / n
    cy = sum(t[1] for t in targets) / n
    cz = sum(t[2] for t in targets) / n

    # 2. 计算目标散布范围，确定拍摄距离
    max_spread = 0
    for t in targets:
        d = ((t[0] - cx)**2 + (t[1] - cy)**2)**0.5
        max_spread = max(max_spread, d)
    max_spread = max(max_spread, 1.5)  # 最少也要覆盖一些范围

    # 3. 摄像机距离 — 偏近景，确保面部和手部细节清晰
    cam_dist = max_spread * 1.2 + 2.5  # 单人≈4.3
    cam_dist = min(cam_dist, 5.0)  # 最远不超过5单位

    # 4. 摄像机位置 — 根据主光方向选择从 Y+ 还是 Y- 拍摄
    if light_side == "front":
        cam_y = room_bounds['y_max'] - 0.5
    else:
        cam_y = room_bounds['y_min'] + 0.5

    cam_x = cx
    cam_z = cz + 1.4

    # 确保摄像机在房间内
    margin = 0.5
    cam_x = max(room_bounds['x_min'] + margin, min(room_bounds['x_max'] - margin, cam_x))
    cam_y = max(room_bounds['y_min'] + margin, min(room_bounds['y_max'] - margin, cam_y))
    cam_z = max(1.2, min(room_bounds['z_ceiling'] - 0.3, cam_z))

    look_at_z = cz + 0.9
    cam_loc = (cam_x, cam_y, cam_z)
    look_at = (cx, cy, look_at_z)

    cam = add_camera(name, location=cam_loc, look_at=look_at)

    print(f"[smart_camera] \"{name}\": 机位({cam_x:.1f}, {cam_y:.1f}, {cam_z:.1f}) → 目标({cx:.1f}, {cy:.1f}, {look_at_z:.1f}), 散布={max_spread:.1f}, 距离={cam_dist:.1f}")
    return cam


# ===========================
# 渲染
# ===========================

def setup_render(output_dir, res_x=1024, res_y=1024, engine='CYCLES'):
    """配置渲染设置（Blender 5.1）。

    默认使用 Cycles 获得高质量无模糊输出。
    深度图由 render_all() 在 EEVEE 模式下生成：
    - frame_0001.png (颜色 — Cycles 路径追踪 + 降噪)
    - depth_0001.png (深度图，白色=近，黑色=远)
    """
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.compression = 0

    # 色彩管理 — Filmic 防止高光过曝
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'

    if engine == 'CYCLES':
        scene.cycles.samples = 128
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.01

        # 启用 GPU 渲染（OptiX → CUDA → 回退 CPU）
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for device_type in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
            try:
                prefs.compute_device_type = device_type
                prefs.get_devices()
                has_gpu = any(d.type != 'CPU' for d in prefs.devices)
                if has_gpu:
                    break
            except Exception:
                continue

        for device in prefs.devices:
            device.use = True

        try:
            scene.cycles.device = 'GPU'
        except Exception:
            pass

    _bl_os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _create_depth_material():
    """创建深度可视化材质（Camera-Z → MapRange → Emission）。

    返回 (material, map_range_node) 以便逐帧根据场景实际深度范围设置参数。

    Blender TexCoord→Camera 的 Z 轴指向观察方向（正值）。
    近处物体 Z 小（≈2），远处物体 Z 大（≈10）。
    """
    mat = bpy.data.materials.new('__DepthHelper')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    tex = nodes.new('ShaderNodeTexCoord')
    sep = nodes.new('ShaderNodeSeparateXYZ')
    links.new(tex.outputs['Camera'], sep.inputs['Vector'])

    # Camera Z 是正值（Z 指向观察方向），near=small pos, far=large pos
    map_range = nodes.new('ShaderNodeMapRange')
    links.new(sep.outputs['Z'], map_range.inputs['Value'])
    # From Min/Max 由 render_all 逐帧动态设置
    # To Min=1.0 (white=近), To Max=0.0 (black=远)
    map_range.inputs['To Min'].default_value = 1.0
    map_range.inputs['To Max'].default_value = 0.0
    map_range.clamp = True  # clamp 防止越界值

    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Strength'].default_value = 1.0
    links.new(map_range.outputs['Result'], emit.inputs['Color'])

    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs['Emission'], out.inputs['Surface'])

    return mat, map_range


def _compute_scene_depth_bounds(camera_obj):
    """计算场景中所有 mesh 物体到摄像机的最近和最远距离。

    用于设置深度 shader 的 MapRange 范围，确保深度图利用完整 0-1 灰度。
    使用 matrix_world.translation 获取世界空间位置（正确处理父子层级）。
    返回 (near, far) 元组。
    """
    cam_pos = camera_obj.location
    min_dist = float('inf')
    max_dist = float('-inf')
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue
        # 用世界空间位置（正确处理父子层级后的实际位置）
        world_pos = obj.matrix_world.translation
        dist = (world_pos - cam_pos).length
        min_dist = min(min_dist, dist)
        max_dist = max(max_dist, dist)

    if min_dist == float('inf'):
        return (0.1, 10.0)

    # 加 padding 确保所有物体都在范围内
    near = max(0.01, min_dist * 0.6)
    far = max_dist * 1.4 + 0.5
    return (near, far)


def _normalize_depth_image(filepath):
    """加载已渲染的深度 PNG，将像素值重新归一化到 0-1 全范围。"""
    import numpy as _np
    img = bpy.data.images.load(filepath)
    w, h = img.size
    # pixels is flat RGBA float array
    pixels = _np.array(img.pixels[:]).reshape((h, w, 4))
    depth = pixels[:, :, 0]
    dmin, dmax = depth.min(), depth.max()
    if dmax > dmin:
        depth_norm = (depth - dmin) / (dmax - dmin)
    else:
        depth_norm = depth
    # Write back to RGBA
    flat = pixels.flatten()
    flat[0::4] = depth_norm.flatten()
    flat[1::4] = depth_norm.flatten()
    flat[2::4] = depth_norm.flatten()
    flat[3::4] = 1.0
    img.pixels = flat.tolist()
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def check_camera_visibility(cam, targets: list):
    """验证所有目标点都在摄像机视野内。

    targets: [(name, (x, y, z)), ...] 每个人物/关键物体的名称和位置。
    如果有人在摄像机后面或视野边缘外，抛出 RuntimeError 中断渲染。
    """
    cam_loc = cam.location
    look_at = _get_camera_look_at(cam)
    forward = look_at - cam_loc
    forward_len = forward.length

    if forward_len < 0.001:
        raise RuntimeError("[摄像机自检失败] 摄像机位置和 look_at 相同！")

    import mathutils
    for name, pos in targets:
        to_target = mathutils.Vector(pos) - cam_loc
        dist = to_target.length
        if dist < 0.001:
            continue  # 目标在摄像机位置，跳过

        # 归一化点积 = cos(夹角)，1.0=正前方，0.0=90度侧面，<0=后方
        dot_norm = forward.dot(to_target) / (forward_len * dist)

        if dot_norm <= 0:
            raise RuntimeError(
                f"[摄像机自检失败] \"{name}\" 在摄像机后面！\n"
                f"  摄像机位置: ({cam_loc.x:.1f}, {cam_loc.y:.1f}, {cam_loc.z:.1f})\n"
                f"  摄像机看向: ({look_at.x:.1f}, {look_at.y:.1f}, {look_at.z:.1f})\n"
                f"  {name}位置:  ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})\n"
                f"  cos(夹角)={dot_norm:.2f} (必须>0)\n"
                f"  请把{name}移到摄像机前方，或把摄像机移到{name}的后方。"
            )
        elif dot_norm < 0.25:
            raise RuntimeError(
                f"[摄像机自检失败] \"{name}\" 在摄像机视野边缘外！\n"
                f"  摄像机位置: ({cam_loc.x:.1f}, {cam_loc.y:.1f}, {cam_loc.z:.1f})\n"
                f"  摄像机看向: ({look_at.x:.1f}, {look_at.y:.1f}, {look_at.z:.1f})\n"
                f"  {name}位置:  ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})\n"
                f"  cos(夹角)={dot_norm:.2f} (必须>0.25，约75度视野内)\n"
                f"  请把{name}移靠近画面中心，或调整摄像机 look_at 包含{name}。"
            )

        print(f"[摄像机自检] ✓ \"{name}\" 在视野内 (cos={dot_norm:.2f}, dist={dist:.1f})")


def _get_camera_look_at(cam):
    """从摄像机约束中提取 look_at 目标点。"""
    for c in cam.constraints:
        if c.type == 'TRACK_TO' and c.target:
            return c.target.location.copy()
    # 无约束时用摄像机朝向估算（前方2单位）
    import mathutils
    dir_vec = mathutils.Vector((0, 0, -1))
    dir_vec.rotate(cam.rotation_euler)
    return cam.location + dir_vec * 2.0


def render_all(cameras, output_dir):
    """逐摄像机渲染，颜色图用 Cycles 高质量，深度图用 EEVEE 秒级生成。

    深度 pass 没有复杂光照（纯 Emission shader），EEVEE 与 Cycles 结果一致。

    输出：
    - frame_0001.png, frame_0002.png, ... (颜色图 — Cycles 128采样 + 降噪)
    - depth_0001.png, depth_0002.png, ... (深度图，白色=近，黑色=远)
    """
    scene = bpy.context.scene
    vl = bpy.context.view_layer
    original_engine = scene.render.engine

    depth_mat, map_range = _create_depth_material()

    for i, cam in enumerate(cameras):
        scene.frame_set(i + 1)
        scene.camera = cam

        # 根据场景实际物体深度设置 shader 范围（而非摄像机裁剪面）
        # TexCoord→Camera Z 是正值（Z 指向观察方向），近处=小正值，远处=大正值
        near, far = _compute_scene_depth_bounds(cam)
        map_range.inputs['From Min'].default_value = near  # 最近 → white
        map_range.inputs['From Max'].default_value = far   # 最远 → black

        # 渲染颜色图（Cycles 或当前引擎）— 人物正常包含
        filepath = f"{output_dir}/frame_{i+1:04d}.png"
        scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)

        # 切换 EEVEE 渲染深度图 — 排除人物部件，只保留环境
        # 关键：临时切到 Standard view transform，否则 Filmic 把深度值压缩到接近 0
        scene.render.engine = 'BLENDER_EEVEE'
        scene.render.image_settings.color_depth = '16'
        saved_view_transform = scene.view_settings.view_transform
        saved_look = scene.view_settings.look
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        vl.material_override = depth_mat

        depth_path = f"{output_dir}/depth_{i+1:04d}.png"
        scene.render.filepath = depth_path
        bpy.ops.render.render(write_still=True)

        scene.render.image_settings.color_depth = '8'
        vl.material_override = None
        scene.view_settings.view_transform = saved_view_transform
        scene.view_settings.look = saved_look
        scene.render.engine = original_engine

        # 归一化深度图到 0-1 全范围
        _normalize_depth_image(depth_path)

        print(f"Rendered frame {i+1}/{len(cameras)}: {filepath} + depth")

    bpy.data.materials.remove(depth_mat)
    print("All frames rendered successfully!")


# ===========================
# (char mask removed — not used in anime pipeline)
# (skeleton removed — no OpenPose CN in anime pipeline)
# ===========================


print("[blender_helpers] 所有辅助函数已就绪。")