#!/usr/bin/env python3
"""按生成前的分段顺序拼接等宽长页，不裁切或缩放原图。"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from PIL import Image


def assemble(manifest: Path, output: Path, *, force: bool = False) -> tuple[int, int]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("清单必须是JSON对象")
    expected, sections = data.get("expected_sections"), data.get("sections")
    if not isinstance(expected, list) or not expected or any(not isinstance(x, str) or not x.strip() for x in expected):
        raise ValueError("expected_sections必须是非空ID列表")
    if len(set(expected)) != len(expected):
        raise ValueError("expected_sections存在重复ID")
    if not isinstance(sections, list) or any(not isinstance(x, dict) for x in sections):
        raise ValueError("sections必须是包含id和image的列表")
    if [x.get("id") for x in sections] != expected:
        raise ValueError("实际分段缺失、重复或顺序与expected_sections不符")
    if output.suffix.lower() != ".png":
        raise ValueError("完整长页输出必须使用.png扩展名")
    if output.exists() and not force:
        raise FileExistsError(f"输出已存在：{output}；确认替换后才使用--force")

    images = []
    seen_paths = set()
    try:
        for section in sections:
            raw = section.get("image")
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError(f"分段{section['id']}缺少image路径")
            path = (manifest.parent / raw).resolve()
            if path == output.resolve() or path in seen_paths:
                raise ValueError("不能重复使用同一图片或覆盖输入图片")
            seen_paths.add(path)
            with Image.open(path) as im:
                im.load()
                if images and im.width != images[0].width:
                    raise ValueError(f"分段{section['id']}宽度{im.width}与首段{images[0].width}不一致；不会自动缩放")
                images.append(im.convert("RGBA"))
        size = (images[0].width, sum(im.height for im in images))
        with Image.new("RGBA", size) as page:
            offset = 0
            for im in images:
                page.paste(im, (0, offset))
                offset += im.height
            output.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".full-page-", suffix=".png", dir=output.parent)
            os.close(fd)
            temporary = Path(temp_name)
            try:
                page.save(temporary, format="PNG")
                if force:
                    os.replace(temporary, output)
                else:
                    # 同目录硬链接原子拒绝覆盖，避免检查后输出被其他任务创建。
                    os.link(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)
        return size
    finally:
        for im in images:
            im.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        width, height = assemble(args.manifest.resolve(), args.output.resolve(), force=args.force)
    except (OSError, ValueError, KeyError, Image.DecompressionBombError) as exc:
        parser.exit(1, f"[错误] {exc}\n")
    print(f"output_path={args.output.resolve()}")
    print(f"size={width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
