#!/usr/bin/env python3
"""Compare two same-sized PNG files using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PIXELS = 16_777_216
MAX_REGIONS = 64
MAX_REGION_FILE_BYTES = 1024 * 1024
MAX_TOTAL_OUTPUT_PIXELS = 67_108_864
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}", re.ASCII)


def check_pixel_budget(width: int, height: int, limit: int = MAX_PIXELS) -> int:
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
        raise ValueError("图片尺寸必须是正整数")
    pixels = width * height
    if pixels > limit:
        raise ValueError("图片尺寸超过像素上限")
    return pixels


def validate_rgba(width: int, height: int, rgba: bytes, limit: int = MAX_TOTAL_OUTPUT_PIXELS) -> None:
    pixels = check_pixel_budget(width, height, limit)
    if len(rgba) != pixels * 4:
        raise ValueError("RGBA 数据长度与尺寸不一致")


def validate_output_path(path: Path, protected_inputs: set[Path], overwrite: bool) -> None:
    if path.is_symlink():
        raise ValueError("输出不得指向符号链接")
    for source in protected_inputs:
        if path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
            raise ValueError("输出不得覆盖输入文件，包括符号链接或硬链接别名")
    if path.exists() and not path.is_file():
        raise ValueError(f"输出不是普通文件：{path}")
    if path.exists() and not overwrite:
        raise ValueError(f"输出已存在；未明确批准覆盖时停止：{path}")


def parse_background(background: str) -> tuple[int, int, int]:
    if not isinstance(background, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise ValueError("background 必须是 #RRGGBB 格式的明确不透明背景色")
    return tuple(int(background[index:index + 2], 16) for index in (1, 3, 5))


def composite(width: int, height: int, rgba: bytes, background: tuple[int, int, int]) -> bytes:
    validate_rgba(width, height, rgba)
    if len(background) != 3 or any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255 for value in background):
        raise ValueError("背景必须包含三个 0 到 255 的整数通道")
    output = bytearray(len(rgba))
    for index in range(0, len(rgba), 4):
        alpha = rgba[index + 3]
        for channel in range(3):
            output[index + channel] = (rgba[index + channel] * alpha + background[channel] * (255 - alpha)) // 255
        output[index + 3] = 255
    return bytes(output)


def paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def decompress_rows(payload: bytes, expected: int) -> bytes:
    if not 0 < expected <= MAX_PIXELS * 5:
        raise ValueError("PNG 解压尺寸超过安全上限")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(payload, expected + 1)
        if len(raw) > expected:
            raise ValueError("PNG 解压数据超过声明尺寸")
        raw += decompressor.flush(expected + 1 - len(raw))
    except zlib.error as exc:
        raise ValueError("PNG 压缩数据无效") from exc
    if len(raw) != expected or not decompressor.eof:
        raise ValueError("PNG 解压数据长度或流状态无效")
    if decompressor.unconsumed_tail or decompressor.unused_data:
        raise ValueError("PNG 包含未消费或额外的压缩数据")
    return raw


def row_to_rgba(
    row: bytearray,
    width: int,
    color_type: int,
    palette: bytes,
    transparency: bytes,
) -> bytearray:
    check_pixel_budget(width, 1)
    if color_type not in CHANNELS or len(row) != width * CHANNELS[color_type]:
        raise ValueError("PNG 行长度或颜色类型无效")
    rgba = bytearray(width * 4)
    for x in range(width):
        target = x * 4
        if color_type == 6:
            source = x * 4
            rgba[target:target + 4] = row[source:source + 4]
        elif color_type == 2:
            source = x * 3
            red, green, blue = row[source:source + 3]
            alpha = 255
            if len(transparency) == 6:
                transparent = struct.unpack(">HHH", transparency)
                alpha = 0 if (red, green, blue) == transparent else 255
            rgba[target:target + 4] = bytes((red, green, blue, alpha))
        elif color_type == 0:
            gray = row[x]
            alpha = 255
            if len(transparency) == 2 and gray == struct.unpack(">H", transparency)[0]:
                alpha = 0
            rgba[target:target + 4] = bytes((gray, gray, gray, alpha))
        elif color_type == 4:
            source = x * 2
            gray, alpha = row[source:source + 2]
            rgba[target:target + 4] = bytes((gray, gray, gray, alpha))
        elif color_type == 3:
            index = row[x]
            source = index * 3
            if source + 3 > len(palette):
                raise ValueError("PNG 像素引用了无效调色板索引")
            red, green, blue = palette[source:source + 3]
            alpha = transparency[index] if index < len(transparency) else 255
            rgba[target:target + 4] = bytes((red, green, blue, alpha))
        else:
            raise ValueError("不支持的 PNG 颜色类型")
    return rgba


def read_png(path: Path) -> tuple[int, int, bytes]:
    if not path.is_file():
        raise ValueError(f"输入不是普通文件：{path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"PNG 文件超过大小上限：{path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"PNG 文件超过大小上限：{path}")
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"输入不是 PNG：{path}")
    try:
        return _decode_png(data)
    except (zlib.error, struct.error) as exc:
        raise ValueError("PNG 二进制或压缩数据无效") from exc


def _decode_png(data: bytes) -> tuple[int, int, bytes]:
    position = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int, int, int] | None = None
    compressed: list[bytes] = []
    palette = b""
    transparency = b""
    ended = False
    seen_palette = False
    seen_transparency = False
    seen_data = False
    data_closed = False
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("PNG 块头不完整")
        length = struct.unpack(">I", data[position:position + 4])[0]
        if length > len(data) - position - 12:
            raise ValueError("PNG 块长度越界")
        chunk_type = data[position + 4:position + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type) or chunk_type[2] & 0x20:
            raise ValueError("PNG 块类型无效")
        if header is None and chunk_type != b"IHDR":
            raise ValueError("PNG 必须以 IHDR 块开始")
        if seen_data and chunk_type != b"IDAT":
            data_closed = True
        chunk = data[position + 8:position + 8 + length]
        stored_crc = struct.unpack(">I", data[position + 8 + length:position + 12 + length])[0]
        actual_crc = zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise ValueError("PNG 块校验失败")
        if chunk_type == b"IHDR":
            if header is not None or position != len(PNG_SIGNATURE) or length != 13:
                raise ValueError("PNG IHDR 无效")
            header = struct.unpack(">IIBBBBB", chunk)
            width, height, bit_depth, color_type, compression, filter_method, interlace = header
            check_pixel_budget(width, height)
            if bit_depth != 8 or color_type not in CHANNELS:
                raise ValueError("只支持 8 位常见颜色类型 PNG")
            if compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("只支持标准压缩、标准过滤和非交错 PNG")
        elif chunk_type == b"PLTE":
            if seen_palette or seen_transparency or seen_data:
                raise ValueError("PNG PLTE 重复或顺序无效")
            if color_type in {0, 4} or not length or length % 3 or length > 768:
                raise ValueError("PNG 调色板长度或颜色类型无效")
            palette = chunk
            seen_palette = True
        elif chunk_type == b"tRNS":
            if seen_transparency or seen_data:
                raise ValueError("PNG tRNS 重复或顺序无效")
            if color_type == 0:
                if length != 2 or struct.unpack(">H", chunk)[0] > 255:
                    raise ValueError("灰度 PNG tRNS 无效")
            elif color_type == 2:
                if length != 6 or any(value > 255 for value in struct.unpack(">HHH", chunk)):
                    raise ValueError("真彩色 PNG tRNS 无效")
            elif color_type == 3:
                if not seen_palette or not 1 <= length <= len(palette) // 3:
                    raise ValueError("索引色 PNG tRNS 长度或顺序无效")
            else:
                raise ValueError("带 Alpha 的 PNG 不应包含 tRNS")
            transparency = chunk
            seen_transparency = True
        elif chunk_type == b"IDAT":
            if data_closed:
                raise ValueError("PNG IDAT 块必须连续")
            if color_type == 3 and not seen_palette:
                raise ValueError("索引色 PNG 必须在 IDAT 前包含 PLTE")
            compressed.append(chunk)
            seen_data = True
        elif chunk_type == b"IEND":
            if length != 0 or not seen_data:
                raise ValueError("PNG IEND 长度或顺序无效")
            ended = True
            position += 12
            break
        elif chunk_type[0] & 0x20 == 0:
            raise ValueError(f"不支持的关键 PNG 块：{chunk_type!r}")
        position += length + 12
    if header is None or not ended or not compressed or position != len(data):
        raise ValueError("PNG 缺少有效头、数据或结束块")
    width, height, _, color_type, _, _, _ = header
    channels = CHANNELS[color_type]
    stride = width * channels
    raw = decompress_rows(b"".join(compressed), height * (stride + 1))
    rgba = bytearray(width * height * 4)
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        filter_type = raw[offset]
        source = raw[offset + 1:offset + 1 + stride]
        offset += stride + 1
        if filter_type > 4:
            raise ValueError("PNG 行过滤类型无效")
        row = bytearray(stride)
        for index, value in enumerate(source):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            else:
                predictor = paeth(left, up, upper_left)
            row[index] = (value + predictor) & 0xFF
        converted = row_to_rgba(row, width, color_type, palette, transparency)
        rgba[y * width * 4:(y + 1) * width * 4] = converted
        previous = row
    return width, height, bytes(rgba)


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    validate_rgba(width, height, rgba)
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    try:
        header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        return b"".join((
            PNG_SIGNATURE,
            png_chunk(b"IHDR", header),
            png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            png_chunk(b"IEND", b""),
        ))
    except (zlib.error, struct.error) as exc:
        raise ValueError("PNG 编码数据无效") from exc


def compare(reference: bytes, current: bytes, background: str = "#ffffff") -> tuple[bytes, bytes, dict[str, object]]:
    if not reference or len(reference) != len(current) or len(reference) % 4:
        raise ValueError("比较输入必须是等长、非空的 RGBA 数据")
    pixels = check_pixel_budget(len(reference) // 4, 1)
    background_rgb = parse_background(background)
    reference = composite(pixels, 1, reference, background_rgb)
    current = composite(pixels, 1, current, background_rgb)
    overlay = bytearray(len(reference))
    diff = bytearray(len(reference))
    changed = 0
    channel_difference = 0
    for index in range(0, len(reference), 4):
        deltas = [abs(reference[index + channel] - current[index + channel]) for channel in range(4)]
        channel_difference += sum(deltas)
        maximum = max(deltas)
        if maximum:
            changed += 1
        for channel in range(4):
            overlay[index + channel] = (reference[index + channel] + current[index + channel]) // 2
        if maximum:
            diff[index:index + 4] = bytes((255, max(0, 96 - maximum), max(0, 96 - maximum), 255))
        else:
            luminance = (reference[index] * 299 + reference[index + 1] * 587 + reference[index + 2] * 114) // 1000
            gray = max(16, luminance // 4)
            diff[index:index + 4] = bytes((gray, gray, gray, 255))
    pixels = len(reference) // 4
    report: dict[str, object] = {
        "changed_pixel_count": changed,
        "changed_pixel_ratio": round(changed / pixels, 8),
        "mean_absolute_rgba_difference": round(channel_difference / (pixels * 4), 6),
        "comparison_mode": "visible-rgba-on-background",
        "background": background.lower(),
        "overlay_mode": "50-percent-composited-rgb",
        "metric_channels": "composited-rgba-alpha-255",
        "interpretation": "仅用于定位差异，不代表视觉质量或验收结论",
    }
    return bytes(overlay), bytes(diff), report


def crop_rgba(width: int, rgba: bytes, region: dict[str, int]) -> bytes:
    x, y, region_width, height = region["x"], region["y"], region["width"], region["height"]
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0 or len(rgba) % (width * 4):
        raise ValueError("裁剪输入宽度或 RGBA 长度无效")
    source_height = len(rgba) // (width * 4)
    validate_rgba(width, source_height, rgba)
    check_pixel_budget(region_width, height, MAX_TOTAL_OUTPUT_PIXELS)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)) or x < 0 or y < 0 or x + region_width > width or y + height > source_height:
        raise ValueError("裁剪区域超出图片边界")
    output = bytearray(region_width * height * 4)
    for row in range(height):
        source_start = ((y + row) * width + x) * 4
        source_end = source_start + region_width * 4
        output[row * region_width * 4:(row + 1) * region_width * 4] = rgba[source_start:source_end]
    return bytes(output)


def make_triptych(width: int, height: int, images: tuple[bytes, bytes, bytes]) -> tuple[int, int, bytes]:
    gap = 4
    check_pixel_budget(width, height)
    if len(images) != 3:
        raise ValueError("局部三联图必须包含三张图片")
    for image in images:
        validate_rgba(width, height, image)
    output_width = width * 3 + gap * 2
    output_pixels = check_pixel_budget(output_width, height, MAX_TOTAL_OUTPUT_PIXELS)
    output = bytearray((48, 48, 48, 255)) * output_pixels
    for image_index, image in enumerate(images):
        start_x = image_index * (width + gap)
        for y in range(height):
            source_start = y * width * 4
            target_start = (y * output_width + start_x) * 4
            output[target_start:target_start + width * 4] = image[source_start:source_start + width * 4]
    return output_width, height, bytes(output)


def load_region_json(path: Path) -> object:
    if path.stat().st_size > MAX_REGION_FILE_BYTES:
        raise ValueError("区域 JSON 文件超过大小上限")
    with path.open("rb") as stream:
        data = stream.read(MAX_REGION_FILE_BYTES + 1)
    if len(data) > MAX_REGION_FILE_BYTES:
        raise ValueError("区域 JSON 文件超过大小上限")
    return json.loads(data.decode("utf-8-sig"))


def load_region_definitions(path: Path, width: int, height: int) -> list[dict[str, object]]:
    data = load_region_json(path)
    regions = data.get("regions") if isinstance(data, dict) else data
    if not isinstance(regions, list) or not regions or len(regions) > MAX_REGIONS:
        raise ValueError(f"区域文件必须包含 1 到 {MAX_REGIONS} 个区域")
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
            raise ValueError(f"区域 {region_id} 超出图片边界或尺寸无效")
        validated.append({"id": region_id, **values})
    return validated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对比两张同尺寸 PNG，生成叠加图、差异图和定位信息")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--regions", type=Path, help="可选区域清单，生成局部图片和定位信息")
    parser.add_argument("--background", default="#ffffff", help="统一合成背景色，格式 #RRGGBB，默认 #ffffff")
    parser.add_argument("--overwrite", action="store_true", help="用户明确批准后覆盖已有输出文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        reference_path = args.reference.expanduser().resolve()
        current_path = args.current.expanduser().resolve()
        regions_path = args.regions.expanduser().resolve() if args.regions else None
        output_dir = args.output_dir.expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError("输出目录路径已存在但不是目录")
        width, height, reference = read_png(reference_path)
        current_width, current_height, current = read_png(current_path)
        if (width, height) != (current_width, current_height):
            raise ValueError(f"图片尺寸不同：参考图 {width}x{height}，当前图 {current_width}x{current_height}")
        regions = load_region_definitions(regions_path, width, height) if regions_path else []
        background_rgb = parse_background(args.background)
        total_pixels = width * height * 2
        for region in regions:
            region_width, region_height = int(region["width"]), int(region["height"])
            total_pixels += (region_width * 6 + 8) * region_height
        if total_pixels > MAX_TOTAL_OUTPUT_PIXELS:
            raise ValueError("比较与区域输出总像素超过安全上限；请减少区域或区域尺寸")
        output_paths = {
            "overlay.png": output_dir / "overlay.png",
            "diff.png": output_dir / "diff.png",
            "comparison.json": output_dir / "comparison.json",
        }
        if regions:
            output_paths["regions.json"] = output_dir / "regions.json"
            for region in regions:
                for filename in ("reference.png", "current.png", "diff.png", "triptych.png"):
                    name = f"regions/{region['id']}/{filename}"
                    output_paths[name] = output_dir / "regions" / str(region["id"]) / filename
        protected_inputs = {reference_path, current_path}
        if regions_path:
            protected_inputs.add(regions_path)
        for path in output_paths.values():
            validate_output_path(path, protected_inputs, args.overwrite)
        overlay, diff, metrics = compare(reference, current, args.background)
        report = {
            "reference": reference_path.as_posix(),
            "current": current_path.as_posix(),
            "width": width,
            "height": height,
            **metrics,
        }
        payloads = {
            "overlay.png": encode_png(width, height, overlay),
            "diff.png": encode_png(width, height, diff),
            "comparison.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        }
        region_reports = []
        for region in regions:
            typed_region = {key: value for key, value in region.items() if key != "id"}
            reference_crop = crop_rgba(width, reference, typed_region)  # type: ignore[arg-type]
            current_crop = crop_rgba(width, current, typed_region)  # type: ignore[arg-type]
            _, region_diff, region_metrics = compare(reference_crop, current_crop, args.background)
            region_width, region_height = int(region["width"]), int(region["height"])
            reference_crop = composite(region_width, region_height, reference_crop, background_rgb)
            current_crop = composite(region_width, region_height, current_crop, background_rgb)
            triptych_width, triptych_height, triptych = make_triptych(
                region_width,
                region_height,
                (reference_crop, current_crop, region_diff),
            )
            base_name = f"regions/{region['id']}"
            payloads[f"{base_name}/reference.png"] = encode_png(region_width, region_height, reference_crop)
            payloads[f"{base_name}/current.png"] = encode_png(region_width, region_height, current_crop)
            payloads[f"{base_name}/diff.png"] = encode_png(region_width, region_height, region_diff)
            payloads[f"{base_name}/triptych.png"] = encode_png(triptych_width, triptych_height, triptych)
            region_reports.append({**region, **region_metrics, "triptych": f"{base_name}/triptych.png"})
        if regions:
            region_report = {
                "reference": reference_path.as_posix(),
                "current": current_path.as_posix(),
                "coordinateSpace": "source-pixels",
                "comparison_mode": metrics["comparison_mode"],
                "background": metrics["background"],
                "interpretation": "区域指标只用于定位与安排检查顺序，不代表视觉质量或验收结论",
                "regions": region_reports,
            }
            payloads["regions.json"] = (json.dumps(region_report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = output_paths[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            validate_output_path(path, protected_inputs, args.overwrite)
            mode = "wb" if args.overwrite else "xb"
            with path.open(mode) as stream:
                stream.write(payload)
        print(json.dumps({
            "status": "compared",
            "outputs": [path.resolve().as_posix() for path in output_paths.values()],
            "metrics": report,
            "regionCount": len(regions),
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
