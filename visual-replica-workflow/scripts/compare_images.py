#!/usr/bin/env python3
"""Compare two same-sized PNG files using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PIXELS = 16_777_216


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
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(payload, expected + 1)
    if len(raw) > expected:
        raise ValueError("PNG 解压数据超过声明尺寸")
    raw += decompressor.flush(expected + 1 - len(raw))
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
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"输入不是 PNG：{path}")
    position = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int, int, int] | None = None
    compressed: list[bytes] = []
    palette = b""
    transparency = b""
    ended = False
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("PNG 块头不完整")
        length = struct.unpack(">I", data[position:position + 4])[0]
        if length > len(data) - position - 12:
            raise ValueError("PNG 块长度越界")
        chunk_type = data[position + 4:position + 8]
        chunk = data[position + 8:position + 8 + length]
        stored_crc = struct.unpack(">I", data[position + 8 + length:position + 12 + length])[0]
        actual_crc = zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise ValueError("PNG 块校验失败")
        if chunk_type == b"IHDR":
            if header is not None or position != len(PNG_SIGNATURE) or length != 13:
                raise ValueError("PNG IHDR 无效")
            header = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            if header is None:
                raise ValueError("PNG 在 IHDR 前出现 IDAT")
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("PNG IEND 无效")
            ended = True
            position += 12
            break
        elif chunk_type[0] & 0x20 == 0:
            raise ValueError(f"不支持的关键 PNG 块：{chunk_type!r}")
        position += length + 12
    if header is None or not ended or not compressed or position != len(data):
        raise ValueError("PNG 缺少有效头、数据或结束块")
    width, height, bit_depth, color_type, compression, filter_method, interlace = header
    if width == 0 or height == 0 or width * height > MAX_PIXELS:
        raise ValueError("PNG 尺寸为零或超过像素上限")
    if bit_depth != 8 or color_type not in CHANNELS:
        raise ValueError("只支持 8 位常见颜色类型 PNG")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("只支持标准压缩、标准过滤和非交错 PNG")
    if color_type == 3:
        if not palette or len(palette) % 3 or len(palette) > 768:
            raise ValueError("索引色 PNG 调色板无效")
        if len(transparency) > len(palette) // 3:
            raise ValueError("索引色 PNG 透明表无效")
    elif color_type in {4, 6} and transparency:
        raise ValueError("带 Alpha 的 PNG 不应包含 tRNS")
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
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA 数据长度与尺寸不一致")
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join((
        PNG_SIGNATURE,
        png_chunk(b"IHDR", header),
        png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
        png_chunk(b"IEND", b""),
    ))


def compare(reference: bytes, current: bytes) -> tuple[bytes, bytes, dict[str, object]]:
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
        "interpretation": "仅用于定位差异，不代表视觉质量或验收结论",
    }
    return bytes(overlay), bytes(diff), report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对比两张同尺寸 PNG，生成叠加图、差异图和定位信息")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="用户明确批准后覆盖已有输出文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        reference_path = args.reference.expanduser().resolve()
        current_path = args.current.expanduser().resolve()
        output_dir = args.output_dir.expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError("输出目录路径已存在但不是目录")
        output_paths = {
            "overlay.png": output_dir / "overlay.png",
            "diff.png": output_dir / "diff.png",
            "comparison.json": output_dir / "comparison.json",
        }
        resolved_outputs = [path.resolve() for path in output_paths.values()]
        if reference_path in resolved_outputs or current_path in resolved_outputs:
            raise ValueError("输出不得覆盖任一输入图片")
        for path in output_paths.values():
            if path.exists() and not args.overwrite:
                raise ValueError(f"输出已存在；未明确批准覆盖时停止：{path}")
        width, height, reference = read_png(reference_path)
        current_width, current_height, current = read_png(current_path)
        if (width, height) != (current_width, current_height):
            raise ValueError(f"图片尺寸不同：参考图 {width}x{height}，当前图 {current_width}x{current_height}")
        overlay, diff, metrics = compare(reference, current)
        report = {
            "reference": str(reference_path),
            "current": str(current_path),
            "width": width,
            "height": height,
            **metrics,
        }
        payloads = {
            "overlay.png": encode_png(width, height, overlay),
            "diff.png": encode_png(width, height, diff),
            "comparison.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            mode = "wb" if args.overwrite else "xb"
            with output_paths[name].open(mode) as stream:
                stream.write(payload)
        print(json.dumps({
            "status": "compared",
            "outputs": [str(path.resolve()) for path in output_paths.values()],
            "metrics": report,
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, zlib.error, struct.error) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
