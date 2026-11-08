#!/usr/bin/env python3
"""使用隔离 Chromium 截图；严格就绪检查需要可选的本地 Playwright。"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import platform
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import url2pathname

from compare_images import read_png

MAX_PIXELS = 16_777_216
PROCESS_TIMEOUT_SECONDS = 45
OPERATION_TIMEOUT_MS = 10_000
STABILITY_INTERVAL_MS = 250
STABILITY_ATTEMPTS = 6
BROWSER_COMMANDS = ("chrome", "google-chrome", "chromium", "msedge", "chromium-browser", "google-chrome-stable")
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
FREEZE_CSS = """
*, *::before, *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
    scroll-behavior: auto !important;
}
"""
RESOURCE_READY_JS = """async (timeout) => {
    let timer;
    const work = async () => {
        await document.fonts.ready;
        const errors = [];
        await Promise.all(Array.from(document.images, async (image) => {
            try {
                await image.decode();
                if (!image.naturalWidth || !image.naturalHeight) throw new Error('empty');
            } catch (_) {
                errors.push({kind: 'image_decode', url: image.currentSrc || image.src,
                             detail: '图片无法解码或没有有效像素'});
            }
        }));
        await document.fonts.ready;
        return errors;
    };
    try {
        return await Promise.race([work(), new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error('资源就绪等待超时')), timeout);
        })]);
    } finally { clearTimeout(timer); }
}"""
PAGE_STATE_JS = """() => ({
    dom_ready_state: document.readyState,
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    device_scale_factor: window.devicePixelRatio,
    fonts: {status: document.fonts.status, faces: Array.from(document.fonts, font => ({
        family: font.family, style: font.style, weight: font.weight, status: font.status
    }))},
    elements: Array.from(document.querySelectorAll('[data-replica-id]'), element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return {id: element.getAttribute('data-replica-id'),
                x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                transform: style.transform, rotation: style.rotate,
                coordinate_space: 'viewport-css-pixels',
                bounds_note: 'getBoundingClientRect 为变换后的 AABB；rotation 不是旋转局部边界'};
    })
})"""


def find_browser() -> Path | None:
    def usable(path: Path) -> bool:
        return path.is_file() and os.access(path, os.X_OK)

    for command in BROWSER_COMMANDS:
        executable = shutil.which(command)
        if executable and usable(Path(executable)):
            return Path(executable).resolve()
    if os.name == "nt":
        roots = {
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        }
        for root in sorted(item for item in roots if item):
            for relative in WINDOWS_BROWSER_RELATIVE_PATHS:
                candidate = Path(root) / relative
                if usable(candidate):
                    return candidate.resolve()
    if sys.platform == "darwin":
        for candidate in MAC_BROWSER_PATHS:
            if usable(candidate):
                return candidate.resolve()
    return None


def validate_url(value: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("URL 不得包含控制字符")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "file"}:
        raise ValueError("URL 只支持 http、https 或 file")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise ValueError("HTTP/HTTPS URL 缺少主机")
    if parsed.scheme == "file" and not parsed.path:
        raise ValueError("file URL 缺少路径")
    if parsed.username or parsed.password:
        raise ValueError("URL 不得包含用户名或密码")
    for name, _ in parse_qsl(parsed.query.replace(";", "&"), keep_blank_values=True):
        compact = re.sub(r"[^a-z0-9]", "", name.lower())
        if (any(word in compact for word in ("token", "password", "passwd", "secret", "credential"))
                or compact.endswith("key")
                or compact in {"pwd", "auth", "authorization", "signature", "sig", "code"}
                or compact.endswith("signature")):
            raise ValueError("URL 含常见敏感 query 参数；请移除 token/key/password 等凭据")
    return value


def redacted_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        query = urlencode([(name, "[redacted]") for name, _ in parse_qsl(parsed.query, keep_blank_values=True)])
        return parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1], query=query, fragment="").geturl()
    except ValueError:
        return "[无效 URL 已隐藏]"


def safe_detail(value: object) -> str:
    text = re.sub(r"(?:https?|file)://[^\s<>\"']+", lambda match: redacted_url(match.group()), str(value))
    # 错误消息也可能包含相对资源 URL；所有 query 值脱敏，而非只过滤已知键名。
    return re.sub(r"\?[^\s<>\"']+", lambda match: "?" + urlencode([
        (name, "[redacted]") for name, _ in parse_qsl(match.group()[1:].split("#", 1)[0], keep_blank_values=True)
    ]), text)[-2000:]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_dimensions(width: int, height: int, dpr: float) -> tuple[int, int]:
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError("宽高必须在 16 到 16384 之间")
    if not math.isfinite(dpr) or dpr <= 0:
        raise ValueError("device-scale-factor 必须是有限正数")
    physical_width, physical_height = width * float(dpr), height * float(dpr)
    if not physical_width.is_integer() or not physical_height.is_integer():
        raise ValueError("width/height 乘 DPR 必须是整数像素；不进行隐式取整")
    if width * height > MAX_PIXELS or physical_width * physical_height > MAX_PIXELS:
        raise ValueError("视口或实际截图像素总量超过安全上限")
    if physical_width < 1 or physical_height < 1:
        raise ValueError("实际截图宽高不得为零")
    return int(physical_width), int(physical_height)


def same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (left.exists() and right.exists() and os.path.samefile(left, right))


def validate_destinations(url: str, output: Path, report: Path, overwrite: bool) -> None:
    if output.suffix.lower() != ".png" or report.suffix.lower() != ".json":
        raise ValueError("截图使用 .png，报告使用 .json 扩展名")
    if same_path(output, report):
        raise ValueError("截图与报告路径不得相同或指向同一文件")
    parsed = urlsplit(url)
    if parsed.scheme == "file":
        host = parsed.netloc if parsed.netloc.lower() != "localhost" else ""
        source = Path(url2pathname(("//" + host if host else "") + parsed.path))
        if any(same_path(path, source) for path in (output, report)):
            raise ValueError("截图与报告不得覆盖 file URL 输入，包括符号链接或硬链接")
    for path in (output, report):
        if path.is_symlink():
            raise ValueError("输出路径不得是符号链接")
        if path.exists() and not path.is_file():
            raise ValueError("输出路径不是普通文件")
        if path.exists() and not overwrite:
            raise ValueError("截图或报告已存在；未明确批准覆盖时停止")


def select_backend(requested: str, browser: Path | None) -> tuple[str, str]:
    if browser is None:
        raise RuntimeError("未找到本地可执行 Chrome、Chromium 或 Edge；不会下载或安装浏览器")
    if requested == "cli":
        return "cli", "explicit_cli"
    try:
        importlib.import_module("playwright.sync_api")
    except ImportError:
        if requested == "playwright":
            raise RuntimeError("Python Playwright 不可用；严格后端不会自动安装或降级") from None
        return "cli", "python_playwright_unavailable"
    return "playwright", "local_browser_and_python_playwright"


def checked_png(path: Path, expected: tuple[int, int]) -> tuple[int, int, bytes]:
    width, height, pixels = read_png(path)
    if not pixels or (width, height) != expected:
        raise ValueError(f"PNG 实测尺寸 {width}x{height} 与期望 {expected[0]}x{expected[1]} 不符或没有像素")
    return width, height, pixels


def capture_cli(config: dict, capture: Path, profile: Path, result: dict) -> None:
    command = [
        config["browser"], "--headless=new", "--disable-extensions", "--disable-background-networking",
        "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
        f"--force-device-scale-factor={config['device_scale_factor']}",
        "--run-all-compositor-stages-before-draw",
        f"--window-size={config['width']},{config['height']}",
        f"--virtual-time-budget={config['wait_ms']}",
        f"--user-data-dir={profile}", f"--screenshot={capture}", config["url"],
    ]
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, errors="replace",
                               timeout=PROCESS_TIMEOUT_SECONDS, check=False, shell=False)
    if completed.returncode != 0:
        raise RuntimeError(f"浏览器退出码 {completed.returncode}：{safe_detail(completed.stderr or completed.stdout)}")
    result.update(status="captured_not_readiness_verified", readiness="unverified", readiness_verified=False,
                  limitations=["CLI 仅核验新 PNG 的解码和实际尺寸；DOM、字体、图片、元素、错误、稳定性及浏览器版本未验证",
                               "CLI window-size/DPR 参数不证明实际 CSS viewport；报告中的 viewport 是请求值"],
                  stability={"stable": None, "attempts": 1})
    if config["ready_selector"]:
        result["limitations"].append("CLI 不执行 ready-selector 检查")


def capture_playwright(config: dict, capture: Path, profile: Path, result: dict) -> None:
    # 仅在严格后端运行时导入；始终使用发现的本地可执行文件和临时 profile。
    sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    expected = validate_dimensions(config["width"], config["height"], config["device_scale_factor"])

    def resource(kind: str, url: str = "", detail: str = "", **fields) -> None:
        error = {"kind": kind, "url": redacted_url(url), "detail": safe_detail(detail), **fields}
        if error not in result["resource_errors"]:
            result["resource_errors"].append(error)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), executable_path=config["browser"], headless=True,
            viewport={"width": config["width"], "height": config["height"]},
            device_scale_factor=config["device_scale_factor"], reduced_motion="reduce", chromium_sandbox=True,
            args=["--disable-extensions", "--disable-background-networking", "--no-first-run", "--no-default-browser-check"],
            timeout=OPERATION_TIMEOUT_MS,
        )
        try:
            context.set_default_timeout(OPERATION_TIMEOUT_MS)
            context.set_default_navigation_timeout(OPERATION_TIMEOUT_MS)
            page = context.pages[0] if context.pages else context.new_page()
            browser_handle = context.browser
            if browser_handle is not None:
                result["browser_version"] = browser_handle.version
            else:
                session = context.new_cdp_session(page)
                try:
                    result["browser_version"] = session.send("Browser.getVersion").get("product")
                finally:
                    session.detach()
            if not result["browser_version"]:
                raise RuntimeError("无法取得实际浏览器版本；不把未知版本记为已验证")
            page.on("pageerror", lambda error: resource("pageerror", detail=str(error)))
            page.on("console", lambda message: resource("console_error", detail=message.text) if message.type == "error" else None)
            page.on("requestfailed", lambda request: resource("requestfailed", request.url, request.failure or "请求失败"))
            page.on("response", lambda response: resource("http_error", response.url, status=response.status) if response.status >= 400 else None)
            page.goto(config["url"], wait_until="load", timeout=OPERATION_TIMEOUT_MS)
            page.add_style_tag(content=FREEZE_CSS)
            page.evaluate("() => document.getAnimations().forEach(animation => { animation.pause(); animation.currentTime = 0; })")
            if config["ready_selector"]:
                page.locator(config["ready_selector"]).first.wait_for(state="visible", timeout=OPERATION_TIMEOUT_MS)
            result["selector_ready"] = True if config["ready_selector"] else None
            for error in page.evaluate(RESOURCE_READY_JS, OPERATION_TIMEOUT_MS):
                resource(error["kind"], error["url"], error["detail"])
            previous = None
            stable = False
            for attempt in range(1, STABILITY_ATTEMPTS + 1):
                for error in page.evaluate(RESOURCE_READY_JS, OPERATION_TIMEOUT_MS):
                    resource(error["kind"], error["url"], error["detail"])
                sample = capture.with_name(f"sample-{attempt}.png")
                page.screenshot(path=str(sample), type="png", full_page=False, scale="device",
                                animations="disabled", caret="hide", style=FREEZE_CSS, timeout=OPERATION_TIMEOUT_MS)
                _, _, pixels = checked_png(sample, expected)
                os.replace(sample, capture)
                if pixels == previous:
                    stable = True
                    break
                previous = pixels
                if attempt < STABILITY_ATTEMPTS:
                    page.wait_for_timeout(STABILITY_INTERVAL_MS)
            result["stability"] = {"stable": stable, "attempts": attempt, "interval_ms": STABILITY_INTERVAL_MS,
                                   "comparison": "consecutive_decoded_rgba_exact_match"}
            state = page.evaluate(PAGE_STATE_JS)
            if len(state["elements"]) > 512:
                raise RuntimeError("data-replica-id 超过 512 项；请将重复细节聚合为稳定分组后重新截图，不截断证据")
            result.update(dom_ready_state=state["dom_ready_state"], fonts=state["fonts"], elements=state["elements"],
                          observed_viewport_width=state["viewport_width"], observed_viewport_height=state["viewport_height"],
                          observed_device_scale_factor=state["device_scale_factor"], final_url=redacted_url(page.url))
            if (state["viewport_width"], state["viewport_height"]) != (config["width"], config["height"]) or not math.isclose(
                    state["device_scale_factor"], config["device_scale_factor"], rel_tol=0, abs_tol=1e-6):
                raise RuntimeError("浏览器实际 CSS viewport 或 DPR 与请求不符")
            for font in state["fonts"]["faces"]:
                if font["status"] == "error":
                    resource("font_error", detail=font["family"])
            dom_ready = state["dom_ready_state"] == "complete" and state["fonts"]["status"] == "loaded"
            verified = stable and dom_ready and not result["resource_errors"]
            result.update(status=("unstable" if not stable else "captured_with_resource_errors" if result["resource_errors"]
                                  else "captured" if dom_ready else "captured_not_readiness_verified"),
                          readiness="verified" if verified else "unstable" if not stable else "unverified",
                          readiness_verified=verified,
                          limitations=["就绪与连续像素稳定不等于完整视觉验收；动态脚本、视频或 canvas 不保证永久稳定"])
        finally:
            context.close()


def capture_worker(config: dict) -> dict:
    result = {
        "status": "unavailable", "output": config["output"], "report": config["report"],
        "actual_width": None, "actual_height": None,
        "viewport_width": config["width"], "viewport_height": config["height"],
        "device_scale_factor": config["device_scale_factor"], "backend": config["backend"],
        "backend_selection": config["backend_selection"], "readiness": "unverified", "readiness_verified": False,
        "resource_errors": [], "elements": [], "fonts": None, "dom_ready_state": "unknown",
        "browser": config["browser"], "browser_version": None, "os": platform.platform(),
        "url": redacted_url(config["url"]), "timestamp": timestamp(), "profile": "temporary-isolated",
        "publication_atomicity": "截图与报告只能逐文件原子发布，不能保证共同原子；用 png_sha256 核对配对",
    }
    try:
        validate_url(config["url"])
        expected = validate_dimensions(config["width"], config["height"], config["device_scale_factor"])
        capture = Path(config["capture"])
        if capture.exists():
            raise ValueError("隔离截图临时文件必须从不存在的路径开始，禁止复用旧 PNG")
        profile = capture.parent / "profile"
        if config["backend"] == "playwright":
            capture_playwright(config, capture, profile, result)
            # close 期间也可能收到错误事件；报告有错误时绝不保留 verified。
            if result["resource_errors"]:
                result.update(status="unstable" if result["status"] == "unstable" else "captured_with_resource_errors",
                              readiness="unstable" if result["status"] == "unstable" else "unverified", readiness_verified=False)
        elif config["backend"] == "cli":
            capture_cli(config, capture, profile, result)
        else:
            raise ValueError("无效截图后端")
        width, height, _ = checked_png(capture, expected)
        result.update(actual_width=width, actual_height=height, png_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
                      timestamp=timestamp())
    except Exception as exc:
        result.update(status="unavailable", readiness="unverified", readiness_verified=False, error=safe_detail(exc), timestamp=timestamp())
    return result


def run_worker(config: dict) -> dict:
    # 子进程总超时覆盖 launch、evaluate、截图与 close；严格失败绝不改走 CLI。
    process = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--_capture-worker"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", shell=False,
                               start_new_session=(os.name != "nt"))
    try:
        stdout, _ = process.communicate(json.dumps(config, ensure_ascii=False), timeout=PROCESS_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        cleanup_errors = []
        try:
            if os.name == "nt":
                # 同时终止 worker 的隔离浏览器后代，避免 Windows 留下挂起进程。
                terminated = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False, shell=False)
                if terminated.returncode != 0:
                    cleanup_errors.append("未确认浏览器进程树已终止")
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (OSError, subprocess.TimeoutExpired):
            cleanup_errors.append("未确认浏览器进程树已终止")
        try:
            process.kill()
            process.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            cleanup_errors.append("未确认 worker 已终止")
        detail = "；".join(cleanup_errors)
        raise RuntimeError("浏览器截图进程超时；没有确认或发布成功结果" + ("；" + detail if detail else "")) from None
    if process.returncode != 0:
        raise RuntimeError("截图 worker 失败；没有确认或发布成功结果")
    result = json.loads(stdout)
    if not isinstance(result, dict) or "status" not in result:
        raise ValueError("截图 worker 未返回有效报告")
    return result


def publish(capture: Path, output: Path, report: Path, result: dict, overwrite: bool) -> None:
    # 两个 staging 文件先准备完毕；每次只发布一份，失败时在 stderr 明示已发布路径。
    with tempfile.TemporaryDirectory(prefix="visual-replica-publish-", dir=output.parent) as image_stage:
        image = Path(image_stage) / "capture.png"
        shutil.copyfile(capture, image)
        with tempfile.TemporaryDirectory(prefix="visual-replica-publish-", dir=report.parent) as report_stage:
            metadata = Path(report_stage) / "capture.json"
            metadata.write_text(json.dumps({**result, "published": [output.as_posix(), report.as_posix()]},
                                           ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for source, destination in ((image, output), (metadata, report)):
                if overwrite:
                    os.replace(source, destination)
                else:
                    # link 保证不覆盖竞争中新出现的目标；不支持时直接失败，不改用非原子覆盖。
                    os.link(source, destination)
                result.setdefault("published", []).append(destination.as_posix())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用本地隔离浏览器生成固定视口 PNG 和 JSON；不启动 devserver、不安装依赖")
    parser.add_argument("--url", required=True, help="用户批准且不含敏感 query 凭据的 http、https 或 file URL")
    parser.add_argument("--output", required=True, type=Path, help="输出 PNG 路径")
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--backend", choices=("auto", "playwright", "cli"), default="auto")
    parser.add_argument("--device-scale-factor", type=float, default=1.0)
    parser.add_argument("--report", type=Path, help="默认 <output>.capture.json，例如 page.png.capture.json")
    parser.add_argument("--ready-selector", help="严格后端等待可见元素；CLI 不验证此条件")
    parser.add_argument("--wait-ms", type=int, default=3000, help="仅 CLI 虚拟等待预算，默认 3000；不代表就绪")
    parser.add_argument("--timeout", type=int, choices=(PROCESS_TIMEOUT_SECONDS,), default=PROCESS_TIMEOUT_SECONDS,
                        help="兼容旧参数，但进程总超时固定为 45 秒，单个严格操作最多 10 秒")
    parser.add_argument("--overwrite", action="store_true", help="用户明确批准后覆盖截图及报告；仍须重新截图")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = {"status": "unavailable", "readiness": "unverified", "readiness_verified": False, "timestamp": timestamp()}
    try:
        url = validate_url(args.url)
        expected = validate_dimensions(args.width, args.height, args.device_scale_factor)
        if not 0 <= args.wait_ms <= 60000:
            raise ValueError("wait-ms 必须在 0 到 60000 之间")
        output = args.output.expanduser().absolute()
        report = (args.report.expanduser().absolute() if args.report else output.with_name(output.name + ".capture.json"))
        validate_destinations(url, output, report, args.overwrite)
        browser = find_browser()
        backend, selection = select_backend(args.backend, browser)
        config = {"url": url, "output": output.as_posix(), "report": report.as_posix(), "width": args.width, "height": args.height,
                  "device_scale_factor": args.device_scale_factor, "backend": backend, "backend_selection": selection,
                  "browser": browser.as_posix(), "wait_ms": args.wait_ms, "ready_selector": args.ready_selector}
        with tempfile.TemporaryDirectory(prefix="visual-replica-browser-") as temporary:
            capture = Path(temporary) / "capture.png"
            config["capture"] = capture.as_posix()
            result = run_worker(config)
            if result["status"] == "unavailable":
                raise RuntimeError(result.get("error", "截图失败"))
            width, height, _ = checked_png(capture, expected)
            if result.get("png_sha256") != hashlib.sha256(capture.read_bytes()).hexdigest():
                raise ValueError("隔离 PNG 与 worker 报告的校验摘要不一致")
            result.update(actual_width=width, actual_height=height)
            validate_destinations(url, output, report, args.overwrite)
            output.parent.mkdir(parents=True, exist_ok=True)
            report.parent.mkdir(parents=True, exist_ok=True)
            publish(capture, output, report, result, args.overwrite)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if (result["status"] == "captured" or
                     result.get("backend") == "cli" and result["status"] == "captured_not_readiness_verified") else 1
    except (OSError, RuntimeError, ValueError, zlib.error, struct.error) as exc:
        result.update(capture_status=result.get("status"), status="unavailable", readiness="unverified",
                      readiness_verified=False, error=safe_detail(exc), timestamp=timestamp())
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if sys.argv[1:] == ["--_capture-worker"]:
        print(json.dumps(capture_worker(json.load(sys.stdin)), ensure_ascii=False))
    else:
        raise SystemExit(main())
