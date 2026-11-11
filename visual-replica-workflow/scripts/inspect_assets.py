#!/usr/bin/env python3
"""Inspect PNG transparency and create light/dark visual review evidence."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from compare_images import check_pixel_budget, composite, encode_png, read_png, validate_output_path, validate_rgba

MAX_PREVIEW_EDGE = 1024
MAX_PREVIEW_PIXELS = 4_194_304


def resize_nearest(width: int, height: int, rgba: bytes, target_width: int, target_height: int) -> bytes:
    validate_rgba(width, height, rgba)
    target_pixels = check_pixel_budget(target_width, target_height, MAX_PREVIEW_PIXELS)
    output = bytearray(target_pixels * 4)
    for y in range(target_height):
        source_y = min(height - 1, y * height // target_height)
        for x in range(target_width):
            source_x = min(width - 1, x * width // target_width)
            source = (source_y * width + source_x) * 4
            target = (y * target_width + x) * 4
            output[target:target + 4] = rgba[source:source + 4]
    return bytes(output)


def make_preview(width: int, height: int, rgba: bytes) -> tuple[int, int, bytes]:
    validate_rgba(width, height, rgba)
    if MAX_PREVIEW_EDGE < 1:
        raise ValueError("预览边长上限必须为正数")
    scale = min(1.0, MAX_PREVIEW_EDGE / width, MAX_PREVIEW_EDGE / height)
    preview_width = max(1, math.floor(width * scale))
    preview_height = max(1, math.floor(height * scale))
    gap = 12
    check_pixel_budget(2 + gap * 3, 1 + gap * 2, MAX_PREVIEW_PIXELS)
    while (preview_width * 2 + gap * 3) * (preview_height + gap * 2) > MAX_PREVIEW_PIXELS:
        preview_width = max(1, preview_width * 9 // 10)
        preview_height = max(1, preview_height * 9 // 10)
    output_width = preview_width * 2 + gap * 3
    output_height = preview_height + gap * 2
    output_pixels = check_pixel_budget(output_width, output_height, MAX_PREVIEW_PIXELS)
    resized = rgba if (preview_width, preview_height) == (width, height) else resize_nearest(width, height, rgba, preview_width, preview_height)
    output = bytearray(output_pixels * 4)
    for y in range(output_height):
        for x in range(output_width):
            color = (245, 245, 245) if x < preview_width + gap * 2 else (32, 32, 32)
            index = (y * output_width + x) * 4
            output[index:index + 4] = bytes((*color, 255))
    light = composite(preview_width, preview_height, resized, (245, 245, 245))
    dark = composite(preview_width, preview_height, resized, (32, 32, 32))
    for y in range(preview_height):
        for image, start_x in ((light, gap), (dark, preview_width + gap * 2)):
            source_start = y * preview_width * 4
            target_start = ((y + gap) * output_width + start_x) * 4
            output[target_start:target_start + preview_width * 4] = image[source_start:source_start + preview_width * 4]
    return output_width, output_height, bytes(output)


def inspect(width: int, height: int, rgba: bytes) -> dict[str, object]:
    validate_rgba(width, height, rgba)
    transparent = 0
    translucent = 0
    opaque = 0
    min_x, min_y = width, height
    max_x = max_y = -1
    for pixel in range(width * height):
        index = pixel * 4
        alpha = rgba[index + 3]
        if alpha == 0:
            transparent += 1
        elif alpha < 255:
            translucent += 1
        else:
            opaque += 1
        if alpha > 0:
            x, y = pixel % width, pixel // width
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
    if max_x < 0:
        bounds = None
        margins = None
    else:
        bounds = {"x": min_x, "y": min_y, "width": max_x - min_x + 1, "height": max_y - min_y + 1}
        margins = {"left": min_x, "top": min_y, "right": width - max_x - 1, "bottom": height - max_y - 1}
    return {
        "width": width,
        "height": height,
        "pixels": width * height,
        "transparentPixels": transparent,
        "partiallyTransparentPixels": translucent,
        "opaquePixels": opaque,
        "hasRealTransparency": transparent + translucent > 0,
        "hasPartialTransparency": translucent > 0,
        "contentBounds": bounds,
        "transparentMargins": margins,
        "edgeChecked": False,
        "approved": False,
        "interpretation": "Alpha 统计和内容边界是机器事实；伪透明棋盘格、边缘质量和视觉可用性仍须结合深浅背景预览由用户检查",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 PNG 真实透明度并生成深浅背景预览")
    parser.add_argument("--asset", required=True, type=Path, help="待检查 PNG；脚本不会修改它")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="用户明确批准后覆盖已有输出")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        asset_path = args.asset.expanduser().resolve()
        output_dir = args.output_dir.expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError("输出目录路径已存在但不是目录")
        output_paths = {
            "inspection.json": output_dir / "inspection.json",
            "preview-light-dark.png": output_dir / "preview-light-dark.png",
        }
        protected_inputs = {asset_path}
        for path in output_paths.values():
            validate_output_path(path, protected_inputs, args.overwrite)
        width, height, rgba = read_png(asset_path)
        report = {"asset": asset_path.as_posix(), **inspect(width, height, rgba)}
        preview_width, preview_height, preview = make_preview(width, height, rgba)
        report["preview"] = {"file": "preview-light-dark.png", "width": preview_width, "height": preview_height}
        payloads = {
            "inspection.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            "preview-light-dark.png": encode_png(preview_width, preview_height, preview),
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            validate_output_path(output_paths[name], protected_inputs, args.overwrite)
            with output_paths[name].open("wb" if args.overwrite else "xb") as stream:
                stream.write(payload)
        print(json.dumps({
            "status": "inspected",
            "outputs": [path.resolve().as_posix() for path in output_paths.values()],
            "hasRealTransparency": report["hasRealTransparency"],
            "contentBounds": report["contentBounds"],
            "visualReviewRequired": True,
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
