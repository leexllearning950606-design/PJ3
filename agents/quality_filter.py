"""图片质量筛选 + 网格图生成 + CLI 交互选择。

提供:
  - _check_frame_quality(): 规则式检测过曝/过暗/低方差
  - _create_grid_image(): 将多张图片拼成网格图
  - _interactive_select(): CLI 交互让用户选择最佳变体
"""

import os
import sys
from PIL import Image
from PIL import ImageDraw
import numpy as np
from config import config


# ===========================
# 质量筛选
# ===========================

def _check_frame_quality(image_path: str) -> dict:
    """规则式质量检测：过曝/过暗/低方差。

    返回 {"pass": bool, "overexposed": bool, "underexposed": bool, "low_variance": bool, "reason": str}
    """
    img = Image.open(image_path).convert('L')
    arr = np.array(img, dtype=np.float64)
    total = arr.size

    # 过曝: 像素值 > 250 占比超过阈值
    overexposed_pct = (arr > 250).sum() / total
    overexposed = overexposed_pct > config.ANIME_QUALITY_OVEREXPOSE_THRESHOLD

    # 过暗: 像素值 < 15 占比超过阈值
    underexposed_pct = (arr < 15).sum() / total
    underexposed = underexposed_pct > config.ANIME_QUALITY_UNDEREXPOSE_THRESHOLD

    # 低方差: 标准差 < 阈值（纯色或噪点图）
    std = arr.std()
    low_variance = std < config.ANIME_QUALITY_LOW_STD_THRESHOLD

    reasons = []
    if overexposed:
        reasons.append(f"过曝({overexposed_pct:.1%})")
    if underexposed:
        reasons.append(f"过暗({underexposed_pct:.1%})")
    if low_variance:
        reasons.append(f"低方差(std={std:.1f})")

    return {
        "pass": not (overexposed or underexposed or low_variance),
        "overexposed": overexposed,
        "underexposed": underexposed,
        "low_variance": low_variance,
        "reason": ", ".join(reasons) if reasons else "通过",
    }


# ===========================
# 网格图生成
# ===========================

def _create_grid_image(image_paths: list, output_dir: str, idx: int = 1) -> str:
    """将多张图片拼成 2×2 或 1×N 网格图，每格标注编号。

    返回网格图路径。
    """
    if not image_paths:
        return ""

    images = [Image.open(p).convert('RGB') for p in image_paths]
    n = len(images)

    # 确定网格布局
    if n == 1:
        cols, rows = 1, 1
    elif n == 2:
        cols, rows = 2, 1
    elif n <= 4:
        cols, rows = 2, 2
    else:
        cols = 3
        rows = (n + 2) // 3

    # 每格尺寸（取第一张图的尺寸）
    cell_w, cell_h = images[0].size
    grid_w = cell_w * cols
    grid_h = cell_h * rows

    grid = Image.new('RGB', (grid_w, grid_h), (30, 30, 30))

    for i, img in enumerate(images):
        r, c = divmod(i, cols)
        x, y = c * cell_w, r * cell_h
        # 如果图片尺寸不一致，缩放
        if img.size != (cell_w, cell_h):
            img = img.resize((cell_w, cell_h), Image.LANCZOS)
        grid.paste(img, (x, y))

        # 标注编号
        draw = ImageDraw.Draw(grid)
        label = str(i + 1)
        bbox = draw.textbbox((0, 0), label)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # 半透明背景
        overlay = Image.new('RGBA', (tw + 20, th + 14), (0, 0, 0, 160))
        grid_rgba = grid.convert('RGBA')
        grid_rgba.paste(overlay, (x + 6, y + 6), overlay)
        grid = grid_rgba.convert('RGB')
        draw = ImageDraw.Draw(grid)
        draw.text((x + 16, y + 12), label, fill=(255, 255, 255))

    grid_path = os.path.join(output_dir, f"grid_{idx:04d}.png")
    grid.save(grid_path)
    print(f"  网格图: {grid_path} ({n} 张, {cols}×{rows})")
    return grid_path


# ===========================
# CLI 交互选择
# ===========================

def _interactive_select(valid_count: int, seeds: list) -> int:
    """CLI 交互：让用户选择最佳变体。非交互模式自动选第1张。

    返回选中索引 (0-based)。
    """
    # 非交互模式（管道/后台）→ 自动选第1张
    if not sys.stdin.isatty():
        print(f"\n  [AUTO] 非交互模式，自动选择第1张 (seed={seeds[0] if seeds else '?'})")
        return 0

    print(f"\n{'─'*50}")
    print(f"  打开网格图查看 {valid_count} 张变体")
    print(f"  输入编号选择最佳图做 Hires Fix：")
    print()
    for i in range(valid_count):
        seed_str = f"seed={seeds[i]}" if i < len(seeds) else ""
        print(f"    [{i+1}]  {seed_str}")
    print(f"    [0]  全部跳过 Hires Fix（保留网格图中的最佳输出）")
    print()

    retries = 0
    while retries < 10:
        try:
            choice = input("  选择 (0-{}): ".format(valid_count)).strip()
            if choice == "0":
                print(f"  跳过 Hires Fix，输出第一张合格图")
                return 0
            idx = int(choice) - 1
            if 0 <= idx < valid_count:
                return idx
        except (ValueError, EOFError):
            pass
        retries += 1
        print(f"  无效输入，请输入 0-{valid_count} (剩余 {10 - retries} 次)")

    # 重试耗尽 → 自动选第1张
    print(f"  重试耗尽，自动选择第1张 (seed={seeds[0] if seeds else '?'})")
    return 0
