#!/usr/bin/env python3
"""Prepare a PNG reference with a coordinate grid and named region crops."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from compare_images import encode_png, read_png

MAX_SCALE = 4
MAX_REGIONS = 64
MAX_TOTAL_OUTPUT_PIXELS = 67_108_864
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}", re.ASCII)
DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def blend_pixel(buffer: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int], alpha: int) -> None:
    if not 0 <= x < width or not 0 <= y < height:
        return
    index = (y * width + x) * 4
    for channel in range(3):
        buffer[index + channel] = (buffer[index + channel] * (255 - alpha) + color[channel] * alpha) // 255
    buffer[index + 3] = 255


def fill_rect(buffer: bytearray, width: int, height: int, x: int, y: int, rect_width: int, rect_height: int, color: tuple[int, int, int], alpha: int) -> None:
    for row in range(y, y + rect_height):
        for column in range(x, x + rect_width):
            blend_pixel(buffer, width, height, column, row, color, alpha)


def draw_number(buffer: bytearray, width: int, height: int, value: int, x: int, y: int) -> None:
    text = str(value)
    pixel_size = 2
    label_width = len(text) * 8 + 2
    fill_rect(buffer, width, height, x - 1, y - 1, label_width, 14, (255, 255, 255), 220)
    for character_index, character in enumerate(text):
        glyph = DIGITS[character]
        origin_x = x + character_index * 8
        for row_index, row in enumerate(glyph):
            for column_index, cell in enumerate(row):
                if cell == "1":
                    fill_rect(
                        buffer,
                        width,
                        height,
                        origin_x + column_index * pixel_size,
                        y + row_index * pixel_size,
                        pixel_size,
                        pixel_size,
                        (20, 20, 20),
                        255,
                    )


def make_grid(width: int, height: int, rgba: bytes, step: int) -> bytes:
    grid = bytearray(rgba)
    for x in range(0, width, step):
        for y in range(height):
            blend_pixel(grid, width, height, x, y, (255, 40, 120), 105)
        draw_number(grid, width, height, x, min(x + 3, max(0, width - 48)), 3)
    for y in range(0, height, step):
        for x in range(width):
            blend_pixel(grid, width, height, x, y, (255, 40, 120), 105)
        draw_number(grid, width, height, y, 3, min(y + 3, max(0, height - 16)))
    return bytes(grid)


def crop(width: int, rgba: bytes, region: dict[str, int]) -> bytes:
    x, y, region_width, height = region["x"], region["y"], region["width"], region["height"]
    output = bytearray(region_width * height * 4)
    for row in range(height):
        source_start = ((y + row) * width + x) * 4
        source_end = source_start + region_width * 4
        output[row * region_width * 4:(row + 1) * region_width * 4] = rgba[source_start:source_end]
    return bytes(output)


def scale_nearest(width: int, height: int, rgba: bytes, scale: int) -> tuple[int, int, bytes]:
    if scale == 1:
        return width, height, rgba
    scaled_width, scaled_height = width * scale, height * scale
    output = bytearray(scaled_width * scaled_height * 4)
    for y in range(height):
        source_row = rgba[y * width * 4:(y + 1) * width * 4]
        scaled_row = bytearray(scaled_width * 4)
        for x in range(width):
            pixel = source_row[x * 4:x * 4 + 4]
            for offset in range(scale):
                start = (x * scale + offset) * 4
                scaled_row[start:start + 4] = pixel
        for repeat in range(scale):
            target_y = y * scale + repeat
            output[target_y * scaled_width * 4:(target_y + 1) * scaled_width * 4] = scaled_row
    return scaled_width, scaled_height, bytes(output)


def default_regions(width: int, height: int) -> list[dict[str, object]]:
    regions: list[dict[str, object]] = []
    for row in range(3):
        for column in range(3):
            x = width * column // 3
            y = height * row // 3
            end_x = width * (column + 1) // 3
            end_y = height * (row + 1) // 3
            regions.append({
                "id": f"region-r{row + 1}-c{column + 1}",
                "x": x,
                "y": y,
                "width": end_x - x,
                "height": end_y - y,
            })
    return regions


def load_regions(path: Path | None, width: int, height: int) -> list[dict[str, object]]:
    if path is None:
        regions = default_regions(width, height)
    else:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        regions = data.get("regions") if isinstance(data, dict) else data
        if not isinstance(regions, list):
            raise ValueError("区域文件必须是数组或包含 regions 数组")
    if not regions or len(regions) > MAX_REGIONS:
        raise ValueError(f"区域数量必须在 1 到 {MAX_REGIONS} 之间")
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in regions:
        if not isinstance(item, dict):
            raise ValueError("每个区域必须是对象")
        region_id = item.get("id")
        if not isinstance(region_id, str) or not ID_RE.fullmatch(region_id) or region_id in seen:
            raise ValueError("区域 ID 必须唯一，且只含小写字母、数字和连字符")
        seen.add(region_id)
        values: dict[str, int] = {}
        for field in ("x", "y", "width", "height"):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"区域 {region_id} 的 {field} 必须是整数")
            values[field] = value
        x, y, region_width, region_height = values["x"], values["y"], values["width"], values["height"]
        if x < 0 or y < 0 or region_width <= 0 or region_height <= 0 or x + region_width > width or y + region_height > height:
            raise ValueError(f"区域 {region_id} 超出原图边界或尺寸无效")
        validated.append({"id": region_id, **values})
    return validated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为 PNG 参考图生成坐标网格、命名区域裁剪和区域清单")
    parser.add_argument("--input", required=True, type=Path, help="原始 PNG；脚本不会修改它")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--regions", type=Path, help="可选的自定义区域 JSON")
    parser.add_argument("--grid-step", type=int, default=100, help="坐标网格间距，默认 100 像素")
    parser.add_argument("--scale", type=int, default=2, help="区域裁剪的整数放大倍数，默认 2")
    parser.add_argument("--overwrite", action="store_true", help="用户明确批准后覆盖已有输出")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        input_path = args.input.expanduser().resolve()
        output_dir = args.output_dir.expanduser()
        regions_path = args.regions.expanduser().resolve() if args.regions else None
        if not 20 <= args.grid_step <= 1000:
            raise ValueError("grid-step 必须在 20 到 1000 之间")
        if not 1 <= args.scale <= MAX_SCALE:
            raise ValueError(f"scale 必须在 1 到 {MAX_SCALE} 之间")
        width, height, rgba = read_png(input_path)
        regions = load_regions(regions_path, width, height)
        output_paths = {
            "grid.png": output_dir / "grid.png",
            "regions.json": output_dir / "regions.json",
        }
        for region in regions:
            output_paths[f"regions/{region['id']}.png"] = output_dir / "regions" / f"{region['id']}.png"
        for path in output_paths.values():
            resolved = path.resolve()
            if resolved == input_path or (regions_path is not None and resolved == regions_path):
                raise ValueError("输出不得覆盖原图或自定义区域文件")
            if path.exists() and not args.overwrite:
                raise ValueError(f"输出已存在；未明确批准覆盖时停止：{path}")
        payloads: dict[str, bytes] = {"grid.png": encode_png(width, height, make_grid(width, height, rgba, args.grid_step))}
        manifest_regions = []
        total_pixels = width * height
        for region in regions:
            cropped = crop(width, rgba, region)  # type: ignore[arg-type]
            scaled_width, scaled_height, scaled = scale_nearest(int(region["width"]), int(region["height"]), cropped, args.scale)
            total_pixels += scaled_width * scaled_height
            if total_pixels > MAX_TOTAL_OUTPUT_PIXELS:
                raise ValueError("网格与区域输出总像素超过安全上限；请减少区域或降低 scale")
            relative_name = f"regions/{region['id']}.png"
            payloads[relative_name] = encode_png(scaled_width, scaled_height, scaled)
            manifest_regions.append({
                **region,
                "file": relative_name,
                "scaledWidth": scaled_width,
                "scaledHeight": scaled_height,
                "scale": args.scale,
            })
        manifest = {
            "source": str(input_path),
            "sourceWidth": width,
            "sourceHeight": height,
            "gridStep": args.grid_step,
            "gridFile": "grid.png",
            "coordinateSpace": "source-pixels",
            "regions": manifest_regions,
        }
        payloads["regions.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = output_paths[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb" if args.overwrite else "xb") as stream:
                stream.write(payload)
        print(json.dumps({
            "status": "prepared",
            "source": str(input_path),
            "width": width,
            "height": height,
            "regionCount": len(regions),
            "outputs": [str(path.resolve()) for path in output_paths.values()],
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
