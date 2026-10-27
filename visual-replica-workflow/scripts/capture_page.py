#!/usr/bin/env python3
"""Capture a fixed-viewport PNG with an isolated Chromium-based browser."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

MAX_PIXELS = 16_777_216
BROWSER_COMMANDS = ("chrome", "google-chrome", "chromium", "msedge")
WINDOWS_BROWSER_RELATIVE_PATHS = (
    Path("Google/Chrome/Application/chrome.exe"),
    Path("Microsoft/Edge/Application/msedge.exe"),
    Path("Chromium/Application/chrome.exe"),
)
MAC_BROWSER_PATHS = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
)


def find_browser() -> Path | None:
    for command in BROWSER_COMMANDS:
        executable = shutil.which(command)
        if executable:
            return Path(executable)
    if os.name == "nt":
        roots = {
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        }
        for root in sorted(item for item in roots if item):
            for relative in WINDOWS_BROWSER_RELATIVE_PATHS:
                candidate = Path(root) / relative
                if candidate.is_file():
                    return candidate
    if sys.platform == "darwin":
        for candidate in MAC_BROWSER_PATHS:
            if candidate.is_file():
                return candidate
    return None


def validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "file"}:
        raise ValueError("URL 只支持 http、https 或 file")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise ValueError("HTTP/HTTPS URL 缺少主机")
    if parsed.scheme == "file" and not parsed.path:
        raise ValueError("file URL 缺少路径")
    if parsed.username or parsed.password:
        raise ValueError("URL 不得包含用户名或密码")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用临时隔离浏览器资料生成固定视口 PNG")
    parser.add_argument("--url", required=True, help="用户批准的 http、https 或 file URL")
    parser.add_argument("--output", required=True, type=Path, help="输出 PNG 路径")
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--wait-ms", type=int, default=3000, help="页面虚拟等待预算，默认 3000")
    parser.add_argument("--timeout", type=int, default=45, help="浏览器进程超时秒数，默认 45")
    parser.add_argument("--overwrite", action="store_true", help="用户明确批准后覆盖已有输出 PNG")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        url = validate_url(args.url)
        if not 16 <= args.width <= 16384 or not 16 <= args.height <= 16384:
            raise ValueError("宽高必须在 16 到 16384 之间")
        if args.width * args.height > MAX_PIXELS:
            raise ValueError("视口像素总量超过安全上限")
        if not 0 <= args.wait_ms <= 60000:
            raise ValueError("wait-ms 必须在 0 到 60000 之间")
        if not 5 <= args.timeout <= 120:
            raise ValueError("timeout 必须在 5 到 120 秒之间")
        output = args.output.expanduser()
        if output.suffix.lower() != ".png":
            raise ValueError("输出文件必须使用 .png 扩展名")
        if output.exists() and not args.overwrite:
            raise ValueError("输出已存在；未明确批准覆盖时停止")
        if output.exists() and not output.is_file():
            raise ValueError("输出路径不是普通文件")
        browser = find_browser()
        if browser is None:
            raise RuntimeError("未找到受支持的 Chrome、Chromium 或 Edge；请改用手动截图或宿主浏览器工具")
        output.parent.mkdir(parents=True, exist_ok=True)
        output = output.resolve()
        with tempfile.TemporaryDirectory(prefix="visual-replica-browser-") as profile:
            command = [
                str(browser),
                "--headless=new",
                "--disable-extensions",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--run-all-compositor-stages-before-draw",
                f"--window-size={args.width},{args.height}",
                f"--virtual-time-budget={args.wait_ms}",
                f"--user-data-dir={profile}",
                f"--screenshot={output}",
                url,
            ]
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                timeout=args.timeout,
                check=False,
                shell=False,
            )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "未知浏览器错误")[-2000:]
            raise RuntimeError(f"浏览器退出码 {completed.returncode}：{detail}")
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("浏览器未生成有效 PNG；请检查页面和视口后重试")
        print(json.dumps({
            "status": "captured",
            "output": str(output),
            "width": args.width,
            "height": args.height,
            "device_scale_factor": 1,
            "browser": browser.name,
            "profile": "temporary-isolated",
        }, ensure_ascii=False, indent=2))
        return 0
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "unavailable", "error": "浏览器截图超时；未确认生成有效 PNG"}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
