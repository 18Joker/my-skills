#!/usr/bin/env python3
"""Offline tests using generated PNGs and temporary directories only."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import struct
import subprocess
import sys
import zlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import capture_page
import check_environment
import compare_images
import inspect_assets
import prepare_reference
import validate_project


def rgba_from_colors(width: int, height: int, colors: dict[tuple[int, int], tuple[int, int, int, int]], default: tuple[int, int, int, int]) -> bytes:
    output = bytearray()
    for y in range(height):
        for x in range(width):
            output.extend(colors.get((x, y), default))
    return bytes(output)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    path.write_bytes(compare_images.encode_png(width, height, rgba))


def run_main(module: object, arguments: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", [module.__name__, *arguments]):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main()
    return code, stdout.getvalue(), stderr.getvalue()


class WorkflowScriptTests(unittest.TestCase):
    def test_prepare_reference_generates_traceable_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="visual-replica-test-") as temporary:
            root = Path(temporary)
            source = root / "source.png"
            regions = root / "custom-regions.json"
            output = root / "out"
            rgba = rgba_from_colors(12, 12, {}, (80, 120, 160, 255))
            write_png(source, 12, 12, rgba)
            original = source.read_bytes()
            regions.write_text(json.dumps({"regions": [{"id": "hero", "x": 2, "y": 2, "width": 4, "height": 4}]}), encoding="utf-8")
            code, _, errors = run_main(prepare_reference, [
                "--input", str(source),
                "--output-dir", str(output),
                "--regions", str(regions),
                "--grid-step", "20",
                "--scale", "2",
            ])
            self.assertEqual(code, 0, errors)
            self.assertEqual(source.read_bytes(), original)
            self.assertTrue((output / "grid.png").is_file())
            self.assertTrue((output / "regions" / "hero.png").is_file())
            width, height, _ = compare_images.read_png(output / "regions" / "hero.png")
            self.assertEqual((width, height), (8, 8))
            manifest = json.loads((output / "regions.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["coordinateSpace"], "source-pixels")
            self.assertEqual(manifest["regions"][0]["x"], 2)
            self.assertEqual(manifest["regions"][0]["scaledWidth"], 8)

    def test_prepare_reference_rejects_invalid_region(self) -> None:
        with tempfile.TemporaryDirectory(prefix="visual-replica-test-") as temporary:
            root = Path(temporary)
            source = root / "source.png"
            regions = root / "custom-regions.json"
            write_png(source, 12, 12, rgba_from_colors(12, 12, {}, (0, 0, 0, 255)))
            regions.write_text(json.dumps({"regions": [{"id": "bad", "x": 10, "y": 2, "width": 4, "height": 4}]}), encoding="utf-8")
            code, _, errors = run_main(prepare_reference, [
                "--input", str(source),
                "--output-dir", str(root / "out"),
                "--regions", str(regions),
            ])
            self.assertEqual(code, 2)
            self.assertIn("超出原图边界", errors)

    def test_asset_inspection_reports_alpha_without_auto_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="visual-replica-test-") as temporary:
            root = Path(temporary)
            asset = root / "asset.png"
            output = root / "inspection"
            rgba = rgba_from_colors(4, 4, {(1, 1): (255, 255, 255, 255), (2, 2): (255, 255, 255, 128)}, (0, 0, 0, 0))
            write_png(asset, 4, 4, rgba)
            original = asset.read_bytes()
            code, _, errors = run_main(inspect_assets, ["--asset", str(asset), "--output-dir", str(output)])
            self.assertEqual(code, 0, errors)
            self.assertEqual(asset.read_bytes(), original)
            report = json.loads((output / "inspection.json").read_text(encoding="utf-8"))
            self.assertTrue(report["hasRealTransparency"])
            self.assertTrue(report["hasPartialTransparency"])
            self.assertEqual(report["contentBounds"], {"x": 1, "y": 1, "width": 2, "height": 2})
            self.assertEqual(report["transparentMargins"], {"left": 1, "top": 1, "right": 1, "bottom": 1})
            self.assertFalse(report["approved"])
            self.assertTrue((output / "preview-light-dark.png").is_file())
            second_code, _, _ = run_main(inspect_assets, ["--asset", str(asset), "--output-dir", str(output)])
            self.assertEqual(second_code, 2)

    def test_region_comparison_generates_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="visual-replica-test-") as temporary:
            root = Path(temporary)
            reference = root / "reference.png"
            current = root / "current.png"
            regions = root / "regions.json"
            output = root / "comparison"
            black = rgba_from_colors(6, 6, {}, (0, 0, 0, 255))
            changed = rgba_from_colors(6, 6, {(2, 2): (255, 255, 255, 255)}, (0, 0, 0, 255))
            write_png(reference, 6, 6, black)
            write_png(current, 6, 6, changed)
            regions.write_text(json.dumps({"regions": [{"id": "hero", "x": 1, "y": 1, "width": 3, "height": 3}]}), encoding="utf-8")
            code, _, errors = run_main(compare_images, [
                "--reference", str(reference),
                "--current", str(current),
                "--output-dir", str(output),
                "--regions", str(regions),
            ])
            self.assertEqual(code, 0, errors)
            report = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(report["changed_pixel_count"], 1)
            region_report = json.loads((output / "regions.json").read_text(encoding="utf-8"))
            self.assertEqual(region_report["regions"][0]["changed_pixel_count"], 1)
            for name in ("reference.png", "current.png", "diff.png", "triptych.png"):
                self.assertTrue((output / "regions" / "hero" / name).is_file())
            width, height, _ = compare_images.read_png(output / "regions" / "hero" / "triptych.png")
            self.assertEqual((width, height), (17, 3))

    def test_legacy_comparison_and_manifest_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="visual-replica-test-") as temporary:
            root = Path(temporary)
            reference = root / "reference.png"
            current = root / "current.png"
            output = root / "comparison"
            rgba = rgba_from_colors(2, 2, {}, (10, 20, 30, 255))
            write_png(reference, 2, 2, rgba)
            write_png(current, 2, 2, rgba)
            code, _, errors = run_main(compare_images, [
                "--reference", str(reference),
                "--current", str(current),
                "--output-dir", str(output),
            ])
            self.assertEqual(code, 0, errors)
            self.assertFalse((output / "regions.json").exists())
            report = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(report["changed_pixel_count"], 0)
            manifest = check_environment.load_json(Path(__file__).resolve().parents[1] / "skill-dependencies.json")
            check_environment.validate_manifest(manifest)
            selected = check_environment.select_dependencies(manifest, {"reference-preprocessing", "asset-inspection"})
            self.assertEqual([item["id"] for item in selected], ["python-runtime"])


def raw_png(width, height, color_type, rows, filters=None, palette=None, transparency=None):
    channels = compare_images.CHANNELS[color_type]
    raw, previous = bytearray(), bytes(width * channels)
    for row, mode in zip(rows, filters or [0] * height):
        raw.append(mode)
        for i, value in enumerate(row):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            predictor = (0, left, up, (left + up) // 2, compare_images.paeth(left, up, corner))[mode]
            raw.append((value - predictor) & 255)
        previous = row
    chunks = [(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))]
    if palette is not None:
        chunks.append((b"PLTE", palette))
    if transparency is not None:
        chunks.append((b"tRNS", transparency))
    return png_chunks([*chunks, (b"IDAT", zlib.compress(raw)), (b"IEND", b"")])


def png_chunks(chunks):
    return compare_images.PNG_SIGNATURE + b"".join(compare_images.png_chunk(kind, value) for kind, value in chunks)


class PngSafetyTests(unittest.TestCase):
    def decode(self, content):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.png"
            path.write_bytes(content)
            return compare_images.read_png(path)

    def test_filters_0_through_4_all_supported_types(self):
        cases = {
            0: (bytes([10, 70]), bytes([10, 10, 10, 255, 70, 70, 70, 255])),
            2: (bytes([10, 20, 30, 70, 80, 90]), bytes([10, 20, 30, 255, 70, 80, 90, 255])),
            3: (bytes([0, 1]), bytes([10, 20, 30, 255, 70, 80, 90, 255])),
            4: (bytes([10, 128, 70, 255]), bytes([10, 10, 10, 128, 70, 70, 70, 255])),
            6: (bytes([10, 20, 30, 128, 70, 80, 90, 255]), bytes([10, 20, 30, 128, 70, 80, 90, 255])),
        }
        for color_type, (row, expected) in cases.items():
            for mode in range(5):
                with self.subTest(color_type=color_type, filter=mode):
                    data = raw_png(2, 2, color_type, [row, row], [mode, mode],
                                   palette=bytes([10, 20, 30, 70, 80, 90]) if color_type == 3 else None)
                    self.assertEqual(self.decode(data), (2, 2, expected * 2))

    def test_valid_trns_gray_rgb_palette(self):
        for color_type, row, palette, transparency, expected in (
            (0, b"\x0a\x14", None, struct.pack(">H", 10), bytes([10, 10, 10, 0, 20, 20, 20, 255])),
            (2, bytes([1, 2, 3, 4, 5, 6]), None, struct.pack(">HHH", 1, 2, 3), bytes([1, 2, 3, 0, 4, 5, 6, 255])),
            (3, b"\x00\x01", bytes([1, 2, 3, 4, 5, 6]), b"\x80", bytes([1, 2, 3, 128, 4, 5, 6, 255])),
        ):
            with self.subTest(color_type=color_type):
                self.assertEqual(self.decode(raw_png(2, 1, color_type, [row], palette=palette, transparency=transparency))[2], expected)

    def test_invalid_trns_lengths_values_and_alpha_types(self):
        cases = [(0, b"", None), (0, struct.pack(">H", 256), None), (2, b"12", None),
                 (2, struct.pack(">HHH", 256, 0, 0), None), (3, b"", b"123"),
                 (3, b"12", b"123"), (3, b"1", None), (4, b"1", None), (6, b"1", None)]
        for color_type, transparency, palette in cases:
            with self.subTest(color_type=color_type, transparency=transparency):
                row = bytes(compare_images.CHANNELS[color_type])
                with self.assertRaises(ValueError):
                    self.decode(raw_png(1, 1, color_type, [row], palette=palette, transparency=transparency))

    def test_crc_rejected(self):
        data = bytearray(compare_images.encode_png(1, 1, bytes([1, 2, 3, 255])))
        data[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "校验"):
            self.decode(bytes(data))

    def test_invalid_zlib_and_declared_length_rejected(self):
        header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        for payload in (b"not-zlib", zlib.compress(b"\x00abcd")[:-2], zlib.compress(b"\x00abc"),
                        zlib.compress(b"\x00abcde"), zlib.compress(b"\x00abcd") + zlib.compress(b"extra")):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.decode(png_chunks([(b"IHDR", header), (b"IDAT", payload), (b"IEND", b"")]))

    def test_noncontiguous_idat_rejected(self):
        header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        data = zlib.compress(b"\x00abcd")
        with self.assertRaisesRegex(ValueError, "连续"):
            self.decode(png_chunks([(b"IHDR", header), (b"IDAT", data[:4]), (b"tEXt", b"a\x00b"),
                                    (b"IDAT", data[4:]), (b"IEND", b"")]))

    def test_contiguous_multiple_idat_valid(self):
        header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        data = zlib.compress(b"\x00abcd")
        self.assertEqual(self.decode(png_chunks([(b"IHDR", header), (b"IDAT", data[:4]),
                                                (b"IDAT", data[4:]), (b"IEND", b"")]))[2], b"abcd")

    def test_invalid_palette_and_index_rejected(self):
        for palette, row in ((None, b"\x00"), (b"", b"\x00"), (b"12", b"\x00"),
                             (b"123", b"\x01"), (bytes(771), b"\x00")):
            with self.subTest(palette=palette), self.assertRaises(ValueError):
                self.decode(raw_png(1, 1, 3, [row], palette=palette))
        with self.assertRaises(ValueError):
            self.decode(raw_png(1, 1, 0, [b"\x00"], palette=b"123"))

    def test_chunk_order_duplicate_palette_and_transparency(self):
        header = struct.pack(">IIBBBBB", 1, 1, 8, 3, 0, 0, 0)
        data = zlib.compress(b"\x00\x00")
        base = [(b"IHDR", header), (b"PLTE", b"123")]
        for extra in ([(b"PLTE", b"456")], [(b"tRNS", b"\x00"), (b"tRNS", b"\x00")],
                      [(b"IDAT", data), (b"tRNS", b"\x00")]):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.decode(png_chunks([*base, *extra, (b"IDAT", data), (b"IEND", b"")]))
        with self.assertRaises(ValueError):
            self.decode(png_chunks([(b"IDAT", data), *base, (b"IEND", b"")]))

    def test_invalid_header_filter_trailing_and_missing_end(self):
        valid = compare_images.encode_png(1, 1, b"abcd")
        for data in (valid + b"x", valid[:-12], png_chunks([(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)),
                                                           (b"IDAT", zlib.compress(b"\x05abcd")), (b"IEND", b"")])):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.decode(data)

    def test_transparent_hidden_rgb_ignored(self):
        _, _, metrics = compare_images.compare(bytes([255, 0, 0, 0]), bytes([0, 255, 0, 0]))
        self.assertEqual(metrics["changed_pixel_count"], 0)

    def test_partial_alpha_composited(self):
        _, _, metrics = compare_images.compare(bytes([255, 0, 0, 128]), bytes([255, 0, 0, 255]))
        self.assertEqual(metrics["changed_pixel_count"], 1)
        self.assertEqual(compare_images.composite(1, 1, bytes([255, 0, 0, 128]), (255, 255, 255)), bytes([255, 127, 127, 255]))

    def test_specified_background_changes_visible_comparison(self):
        a, b = bytes([255, 255, 255, 0]), bytes([255, 255, 255, 255])
        self.assertEqual(compare_images.compare(a, b, "#ffffff")[2]["changed_pixel_count"], 0)
        self.assertEqual(compare_images.compare(a, b, "#000000")[2]["changed_pixel_count"], 1)
        with self.assertRaises(ValueError):
            compare_images.compare(a, b, "transparent")

    def test_png_budget_before_decompression_allocation(self):
        header = struct.pack(">IIBBBBB", compare_images.MAX_PIXELS + 1, 1, 8, 6, 0, 0, 0)
        with patch.object(compare_images, "decompress_rows", side_effect=AssertionError("不得解压")), \
             patch.object(compare_images, "bytearray", side_effect=AssertionError("不得分配"), create=True):
            with self.assertRaisesRegex(ValueError, "像素上限"):
                self.decode(png_chunks([(b"IHDR", header), (b"IDAT", b"x"), (b"IEND", b"")]))

    def test_scale_and_preview_budget_before_allocation(self):
        with patch.object(prepare_reference, "MAX_TOTAL_OUTPUT_PIXELS", 15), \
             patch.object(prepare_reference, "bytearray", side_effect=AssertionError("不得分配"), create=True):
            with self.assertRaises(ValueError):
                prepare_reference.scale_nearest(2, 2, bytes(16), 2)
        with patch.object(inspect_assets, "MAX_PREVIEW_PIXELS", 1), \
             patch.object(inspect_assets, "bytearray", side_effect=AssertionError("不得分配"), create=True):
            with self.assertRaises(ValueError):
                inspect_assets.make_preview(1, 1, bytes(4))

    def test_local_to_source_exact_inverse_two_times(self):
        region = {"x": 10, "y": 20, "width": 8, "height": 6}
        self.assertEqual(prepare_reference.local_to_source(region, 3, 5, 4, 6, 2),
                         {"x": 11.5, "y": 22.5, "width": 2.0, "height": 3.0})
        for scale in (1, 2, 4):
            self.assertEqual(prepare_reference.local_to_source(region, 0, 0, 8 * scale, 6 * scale, scale),
                             {"x": 10, "y": 20, "width": 8, "height": 6})

    def test_local_to_source_nan_zero_and_invalid_scale(self):
        region = {"x": 0, "y": 0, "width": 8, "height": 6}
        for scale in (0, -1, 5, 2.0, True, float("nan")):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                prepare_reference.local_to_source(region, 0, 0, 1, 1, scale)
        for value in (float("nan"), float("inf"), -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_reference.local_to_source(region, value, 0, 1, 1, 2)
        with self.assertRaises(ValueError):
            prepare_reference.local_to_source({**region, "width": 0}, 0, 0, 0, 0, 2)

    def test_compare_total_output_budget_before_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("source.png", "current.png"):
                write_png(root / name, 2, 2, bytes(16))
            with patch.object(compare_images, "MAX_TOTAL_OUTPUT_PIXELS", 7), \
                 patch.object(compare_images, "compare", side_effect=AssertionError("不得比较分配")):
                code, _, error = run_main(compare_images, ["--reference", str(root / "source.png"),
                                                          "--current", str(root / "current.png"), "--output-dir", str(root / "out")])
            self.assertEqual(code, 2)
            self.assertIn("总像素", error)
            self.assertFalse((root / "out").exists())

    def test_unsupported_png_header_modes(self):
        for bit_depth, color_type, compression, filtering, interlace in ((16, 6, 0, 0, 0), (8, 1, 0, 0, 0),
                                                                       (8, 6, 1, 0, 0), (8, 6, 0, 1, 0), (8, 6, 0, 0, 1)):
            with self.subTest(mode=(bit_depth, color_type, compression, filtering, interlace)), self.assertRaises(ValueError):
                self.decode(png_chunks([(b"IHDR", struct.pack(">IIBBBBB", 1, 1, bit_depth, color_type, compression, filtering, interlace)),
                                        (b"IDAT", zlib.compress(b"\x00abcd")), (b"IEND", b"")]))

    def test_all_transparent_inspection_not_auto_approved(self):
        report = inspect_assets.inspect(1, 1, bytes([255, 0, 255, 0]))
        self.assertTrue(report["hasRealTransparency"])
        self.assertIsNone(report["contentBounds"])
        self.assertFalse(report["approved"])
        self.assertFalse(report["edgeChecked"])


class CaptureSafetyTests(unittest.TestCase):
    def config(self, root, backend="cli"):
        return {"url": "http://localhost/", "output": str(root / "out.png"), "report": str(root / "out.json"),
                "capture": str(root / "fresh.png"), "width": 16, "height": 16, "device_scale_factor": 2.0,
                "browser": "mock-browser", "backend": backend, "backend_selection": "mock", "wait_ms": 0,
                "ready_selector": "#ready"}

    def test_checked_png_rejects_bad_file_and_wrong_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.png"
            path.write_bytes(b"not-png")
            with self.assertRaises(ValueError):
                capture_page.checked_png(path, (32, 32))
            write_png(path, 16, 16, bytes([0, 0, 0, 255]) * 256)
            with self.assertRaises(ValueError):
                capture_page.checked_png(path, (32, 32))

    def test_dimensions_dpr_nonfinite_fractional_and_budget(self):
        self.assertEqual(capture_page.validate_dimensions(16, 16, 2), (32, 32))
        for dpr in (0, -1, float("nan"), float("inf"), 1.01, 10000):
            with self.subTest(dpr=dpr), self.assertRaises(ValueError):
                capture_page.validate_dimensions(16, 16, dpr)

    def test_old_png_never_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.config(root)
            write_png(Path(config["capture"]), 32, 32, bytes(4096))
            with patch.object(capture_page, "capture_cli") as cli, patch.object(capture_page, "capture_playwright") as strict:
                result = capture_page.capture_worker(config)
            cli.assert_not_called()
            strict.assert_not_called()
            self.assertEqual(result["status"], "unavailable")
            self.assertFalse(result["readiness_verified"])

    def test_worker_bad_png_and_wrong_dpr_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for content in (b"bad", compare_images.encode_png(16, 16, bytes(1024))):
                config = self.config(root)
                def fake_cli(config, capture, profile, result):
                    capture.write_bytes(content)
                with patch.object(capture_page, "capture_cli", side_effect=fake_cli):
                    result = capture_page.capture_worker(config)
                self.assertEqual(result["status"], "unavailable")
                self.assertFalse(result["readiness_verified"])
                Path(config["capture"]).unlink()

    def test_cli_report_never_claims_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.config(root)
            def fake_run(command, **kwargs):
                destination = next(value.split("=", 1)[1] for value in command if value.startswith("--screenshot="))
                write_png(Path(destination), 32, 32, bytes([0, 0, 0, 255]) * 1024)
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch.object(capture_page.subprocess, "run", side_effect=fake_run):
                result = capture_page.capture_worker(config)
            self.assertEqual(result["status"], "captured_not_readiness_verified")
            self.assertFalse(result["readiness_verified"])
            self.assertIsNone(result["browser_version"])
            self.assertEqual(result["png_sha256"], hashlib.sha256(Path(config["capture"]).read_bytes()).hexdigest())
            self.assertTrue(any("ready-selector" in text for text in result["limitations"]))

    def test_auto_fallback_and_strict_no_downgrade(self):
        with patch.object(capture_page.importlib, "import_module", side_effect=ImportError):
            self.assertEqual(capture_page.select_backend("auto", Path("mock")), ("cli", "python_playwright_unavailable"))
            with self.assertRaises(RuntimeError):
                capture_page.select_backend("playwright", Path("mock"))
        with self.assertRaises(RuntimeError):
            capture_page.select_backend("auto", None)

    def test_environment_reuses_browser_finder_discovery_only(self):
        with patch.object(capture_page, "find_browser", return_value=Path("mock-browser")) as finder:
            report = check_environment.check_item("chromium-browser", {"type": "cli", "command": "chrome"},
                                                   allow_network=False, timeout=1, retries=0, probe_results={})
        finder.assert_called_once()
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["discovery_only"])
        self.assertFalse(report["runtime_verified"])


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="replica-validator-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.black = bytes([0, 0, 0, 255]) * 64
        write_png(self.root / "source.png", 8, 8, self.black)
        self.spec = {"schemaVersion": "1", "revision": 1, "sourceFile": "source.png",
                     "sourceSha256": self.hash("source.png"), "coordinateSpace": "source-pixels",
                     "canvas": {"sourceWidth": 8, "sourceHeight": 8, "viewportWidth": 4, "viewportHeight": 4,
                                "deviceScaleFactor": 2},
                     "elements": [self.element("target", 0, 0), self.element("title", 4, 4, "text")]}
        self.spec["elements"][1]["text"] = "标题"
        self.approve()
        self.texts = {"title": {"text": "标题", "source": "user-provided", "verified": True,
                                "verificationEvidence": "用户消息：标题", "renderMode": "text", "requiredEditable": True,
                                "fontVerified": False, "lineBreaksVerified": True}}
        self.assets = {}
        self.save("text.json", self.texts)
        self.save("assets.json", self.assets)
        write_png(self.root / "current.png", 8, 8, self.black)
        write_png(self.root / "baseline.png", 8, 8, self.black)
        (self.root / "page.css").write_text(".target{color:black}", encoding="utf-8")

    def element(self, eid, x, y, type_="box"):
        return {"id": eid, "type": type_, "parentId": None, "x": x, "y": y, "width": 2, "height": 2,
                "rotation": 0, "source": "measured", "confidence": "high", "verified": False,
                "status": "pending-review", "freeze": False, "implementation": "html-css"}

    def hash(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return Path(name)

    def approve(self, selected=None, generated=None, raster=None):
        self.spec["review"] = {"status": "approved", "revision": self.spec["revision"],
                               "analysisDigest": validate_project.plan_digest(self.spec), "confirmedBy": "user",
                               "evidence": "用户消息引用：确认 target 方案", "approvedElementIds": selected or ["target"],
                               "allowGeneratedAssetIds": generated or [], "allowRasterizedTextIds": raster or []}

    def capture(self):
        report = {"status": "captured", "png_sha256": self.hash("current.png"), "actual_width": 8,
                  "actual_height": 8, "viewport_width": 4, "viewport_height": 4, "device_scale_factor": 2,
                  "readiness_verified": True, "backend": "playwright", "resource_errors": [],
                  "browser_version": "mock-1", "os": "mock-os", "timestamp": "2026-11-05T00:00:00Z",
                  "elements": [{"id": e["id"], "x": e["x"] / 2, "y": e["y"] / 2,
                                "width": e["width"] / 2, "height": e["height"] / 2,
                                "coordinate_space": "viewport-css-pixels"} for e in self.spec["elements"]]}
        self.save("capture.json", report)
        return report

    def regression(self):
        digest = validate_project.plan_digest(self.spec)
        self.issue = {"revision": 1, "analysisDigest": digest, "allowedElementIds": ["target"],
                      "allowedFiles": ["page.css"], "allowedProperties": ["color"],
                      "regressionElementIds": ["title"], "evidence": "用户消息引用：target 颜色问题"}
        self.checkpoint = {"revision": 1, "analysisDigest": digest, "baseline": "baseline.png",
                           "baselineSha256": self.hash("baseline.png"),
                           "files": {"page.css": self.hash("page.css"), "source.png": self.hash("source.png")}}
        self.save("issues.json", self.issue)
        self.save("checkpoint.json", self.checkpoint)
        self.capture()

    def execute(self, stage="implementation", **overrides):
        self.save("analysis.json", self.spec)
        paths = {"text_manifest": Path("text.json"), "asset_manifest": Path("assets.json")}
        if stage in {"capture", "regression"}:
            paths.update(current=Path("current.png"), capture_report=Path("capture.json"))
        if stage == "regression":
            paths.update(baseline=Path("baseline.png"), issues=Path("issues.json"), checkpoint=Path("checkpoint.json"))
        paths.update(overrides)
        return validate_project.validate_project(self.root, Path("analysis.json"), stage, **paths)

    def blocked(self, report, contains=None):
        self.assertEqual(report["status"], "blocked", report)
        self.assertFalse(report["visual_approved"])
        self.assertTrue(report["errors"])
        if contains:
            self.assertIn(contains, " ".join(report["errors"]))

    def image(self, generated=False, transparent=False, pixels=None):
        e = self.spec["elements"][0]
        e.update(implementation="generate-image" if generated else "reuse-image", assetId="asset")
        write_png(self.root / "asset.png", 2, 2, pixels or bytes([20, 30, 40, 255]) * 4)
        self.assets = {"asset": {"file": "asset.png", "source": "generated" if generated else "provided",
                                 "approved": True, "approvalEvidence": "用户消息引用：确认素材",
                                 "approximate": False, "transparentBackground": transparent,
                                 "alphaVerified": transparent, "edgeChecked": transparent}}
        self.save("assets.json", self.assets)
        self.approve()

    def test_candidate_without_approval_and_missing_source_hash_warning(self):
        self.spec.pop("review")
        self.spec.pop("sourceSha256")
        self.spec["elements"][0].update(type="unknown", implementation="undetermined", source="estimated")
        report = self.execute("analysis")
        self.assertEqual(report["status"], "awaiting_user_review", report)
        self.assertFalse(report["visual_approved"])
        self.assertEqual(report["source_sha256"], self.hash("source.png"))
        self.assertTrue(any("sourceSha256" in text for text in report["warnings"]))

    def test_candidate_cli_success_exit_zero(self):
        self.spec.pop("review")
        self.save("analysis.json", self.spec)
        code, output, errors = run_main(validate_project, ["--project-root", str(self.root), "--analysis", "analysis.json", "--stage", "analysis"])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["status"], "awaiting_user_review")

    def test_missing_confirmation_blocks_implementation(self):
        self.spec.pop("review")
        self.blocked(self.execute(), "review")

    def test_pending_confirmation_blocks_implementation(self):
        self.spec["review"]["status"] = "pending"
        self.blocked(self.execute(), "用户确认")

    def test_stale_digest_and_revision_block(self):
        self.spec["elements"][0]["x"] = 1
        self.blocked(self.execute(), "analysisDigest")
        self.approve()
        self.spec["revision"] = 2
        self.blocked(self.execute(), "revision")

    def test_digest_includes_planning_excludes_runtime_and_review(self):
        before = validate_project.plan_digest(self.spec)
        self.spec["elements"][0].update(status="approved", freeze=True, verified=True, verificationEvidence="证据")
        self.spec["review"]["evidence"] = "不同原话"
        self.assertEqual(before, validate_project.plan_digest(self.spec))
        for mutate in (lambda s: s["elements"][0].update(style={"color": "red"}),
                       lambda s: s.update(revision=2), lambda s: s.update(sourceSha256="0" * 64),
                       lambda s: s["elements"][0].update(x=1), lambda s: s.update(sourceFile="other.png")):
            changed = copy.deepcopy(self.spec)
            mutate(changed)
            self.assertNotEqual(before, validate_project.plan_digest(changed))
        reordered = dict(reversed(list(self.spec.items())))
        self.assertEqual(before, validate_project.plan_digest(reordered))

    def test_partial_scope_does_not_select_all_text(self):
        self.save("text.json", {})
        report = self.execute()
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertEqual(report["selected_element_ids"], ["target"])
        self.assertEqual(report["pending_element_ids"], ["title"])
        self.assertFalse(report["visual_approved"])
        self.assertIn("实际聊天", report["limitations"][0])

    def test_empty_or_nonexistent_selected_scope(self):
        for ids in ([], ["missing"], ["target", "target"]):
            self.spec["review"]["approvedElementIds"] = ids
            self.blocked(self.execute())

    def test_unknown_selected_blocks(self):
        self.spec["elements"][0]["type"] = "unknown"
        self.approve()
        self.blocked(self.execute(), "不可实施")

    def test_duplicate_ids_parent_cycle_and_missing_parent(self):
        original = copy.deepcopy(self.spec)
        for change in (lambda: self.spec["elements"][1].update(id="target"),
                       lambda: (self.spec["elements"][0].update(parentId="title"), self.spec["elements"][1].update(parentId="target")),
                       lambda: self.spec["elements"][0].update(parentId="missing")):
            self.spec = copy.deepcopy(original)
            change()
            self.blocked(self.execute("analysis"))

    def test_relative_tolerance_and_mismatch(self):
        self.spec.pop("review")
        self.spec["elements"][0]["relative"] = {"x": 0.00009, "y": 0, "width": 0.25, "height": 0.25}
        self.assertEqual(self.execute("analysis")["status"], "awaiting_user_review")
        self.spec["elements"][0]["relative"]["x"] = 0.001
        self.blocked(self.execute("analysis"), "relative")

    def test_nonfinite_and_bool_geometry_block(self):
        for value in (float("nan"), float("inf"), True):
            self.spec["elements"][0]["x"] = value
            self.blocked(self.execute("analysis"))

    def test_canvas_exact_physical_and_positive_dimensions(self):
        for value in (1.9, 0, float("nan")):
            self.spec["canvas"]["deviceScaleFactor"] = value
            self.blocked(self.execute("analysis"))
        self.spec["canvas"]["deviceScaleFactor"] = 2
        self.spec["canvas"]["sourceWidth"] = True
        self.blocked(self.execute("analysis"))

    def test_revision_schema_and_element_limit(self):
        for field, value in (("revision", True), ("revision", 0), ("schemaVersion", 1), ("coordinateSpace", "css-pixels")):
            original = self.spec[field]
            self.spec[field] = value
            self.blocked(self.execute("analysis"))
            self.spec[field] = original
        self.spec["elements"] = [self.element(f"e-{i}", 0, 0) for i in range(513)]
        self.blocked(self.execute("analysis"), "512")

    def test_overflow_requires_evidence_and_freeze_requires_approval(self):
        self.spec.pop("review")
        e = self.spec["elements"][0]
        e["x"] = -1
        self.blocked(self.execute("analysis"), "越界")
        e.update(allowOverflow=True, evidence="源图边缘裁切")
        self.assertEqual(self.execute("analysis")["status"], "awaiting_user_review")
        e.update(freeze=True, verificationEvidence="核验")
        self.blocked(self.execute("analysis"), "approved")
        e.update(status="approved")
        self.assertEqual(self.execute("analysis")["status"], "awaiting_user_review")

    def test_verified_requires_verification_evidence(self):
        self.spec["elements"][0]["verified"] = True
        self.blocked(self.execute("analysis"), "verificationEvidence")

    def test_source_hash_always_validated_and_missing_blocks_impl(self):
        self.spec["sourceSha256"] = "0" * 64
        self.blocked(self.execute("analysis"), "不匹配")
        self.spec.pop("sourceSha256")
        self.blocked(self.execute(), "sourceSha256")

    def test_explicit_and_reference_path_escape_blocked(self):
        self.blocked(self.execute(issues=Path("../outside.json")), "..")
        self.spec["sourceFile"] = "../outside.png"
        self.blocked(self.execute("analysis"), "..")
        self.spec["sourceFile"] = (self.root / "source.png").as_posix()
        self.blocked(self.execute("analysis"), "根相对")

    def test_symlink_escape_blocked_without_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary) / "outside.png"
            outside.write_bytes("不得读取".encode("utf-8"))
            link = self.root / "link.png"
            with contextlib.ExitStack() as stack:
                try:
                    link.symlink_to(outside)
                except OSError:
                    # Windows 无创建权限时模拟 resolve 结果，仍检查越界文件绝不读取。
                    link.write_bytes(b"mock-link")
                    original = Path.resolve
                    def resolve(path, *args, **kwargs):
                        return outside if path == link else original(path, *args, **kwargs)
                    stack.enter_context(patch.object(Path, "resolve", resolve))
                self.spec["sourceFile"] = "link.png"
                stack.enter_context(patch.object(validate_project, "read_png", side_effect=AssertionError("不得读越界 PNG")))
                self.blocked(self.execute("analysis"), "符号链接")

    def test_missing_bad_oversize_duplicate_json_structured(self):
        self.blocked(self.execute(text_manifest=Path("missing.json")))
        for content in (b"bad", b'{"a":1,"a":2}', b" " * (validate_project.MAX_JSON_BYTES + 1)):
            (self.root / "text.json").write_bytes(content)
            self.blocked(self.execute())

    def test_invalid_cli_structured_exit_one(self):
        for args in ([], ["--project-root", str(self.root), "--analysis", "missing.json", "--stage", "capture"],
                     ["--project-root", str(self.root), "--analysis", "missing.json", "--stage", "wrong"]):
            code, output, _ = run_main(validate_project, args)
            self.assertEqual(code, 1)
            self.blocked(json.loads(output))

    def test_selected_text_missing_unverified_and_mismatched(self):
        self.approve(["title"])
        for texts in ({}, {"title": {**self.texts["title"], "verified": False}},
                      {"title": {**self.texts["title"], "text": "错字"}},
                      {"title": {**self.texts["title"], "verificationEvidence": ""}}):
            self.save("text.json", texts)
            self.blocked(self.execute())

    def test_unverified_font_warns_not_visual_failure(self):
        self.approve(["title"])
        report = self.execute()
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertTrue(any("字体未核验" in text for text in report["warnings"]))

    def test_editable_text_cannot_rasterize_even_with_receipt(self):
        self.image()
        self.spec["elements"][1]["assetId"] = "asset"
        self.texts["title"]["renderMode"] = "image"
        self.save("text.json", self.texts)
        self.approve(["title"], raster=["title"])
        self.blocked(self.execute(), "可编辑")

    def test_raster_text_requires_receipt_and_approved_asset(self):
        self.image()
        self.spec["elements"][1]["assetId"] = "asset"
        self.texts["title"].update(renderMode="image", requiredEditable=False)
        self.save("text.json", self.texts)
        self.approve(["title"])
        self.blocked(self.execute(), "栅格化授权")
        self.approve(["title"], raster=["title"])
        self.assertEqual(self.execute()["status"], "checks_passed")
        self.assets["asset"]["approved"] = False
        self.save("assets.json", self.assets)
        self.blocked(self.execute(), "素材未获批准")

    def test_approved_asset_missing_file_or_evidence_blocked(self):
        self.image()
        (self.root / "asset.png").unlink()
        self.blocked(self.execute())
        write_png(self.root / "asset.png", 1, 1, bytes(4))
        self.assets["asset"]["approvalEvidence"] = ""
        self.save("assets.json", self.assets)
        self.blocked(self.execute(), "审批缺证据")

    def test_image_asset_same_element_id_fallback(self):
        self.image()
        self.spec["elements"][0].pop("assetId")
        self.assets = {"target": self.assets["asset"]}
        self.save("assets.json", self.assets)
        self.approve()
        self.assertEqual(self.execute()["status"], "checks_passed")

    def test_explicit_asset_reference_cannot_bypass_approval_via_css(self):
        self.image()
        self.spec["elements"][0]["implementation"] = "html-css"
        self.assets["asset"]["approved"] = False
        self.save("assets.json", self.assets)
        self.approve()
        self.blocked(self.execute(), "素材未获批准")

    def test_text_image_method_cannot_claim_editable_text_render_mode(self):
        self.image()
        self.spec["elements"][1].update(implementation="reuse-image", assetId="asset")
        self.approve(["title"])
        self.blocked(self.execute(), "renderMode:text")

    def test_generated_and_approximate_asset_need_element_authorization(self):
        self.image(generated=True)
        self.blocked(self.execute(), "未授权")
        self.approve(generated=["target"])
        self.assertEqual(self.execute()["status"], "checks_passed")
        self.assets["asset"].update(source="provided", approximate=True)
        self.spec["elements"][0]["implementation"] = "reuse-image"
        self.save("assets.json", self.assets)
        self.approve()
        self.blocked(self.execute(), "未授权")
        self.approve(generated=["asset"])
        self.blocked(self.execute(), "不存在")

    def test_real_alpha_and_nonempty_content_required(self):
        for pixels, passed in ((bytes([0, 0, 0, 255]) * 4, False), (bytes([255, 0, 0, 0]) * 4, False),
                               (bytes([0, 0, 0, 0, 20, 30, 40, 128]) * 2, True)):
            self.image(transparent=True, pixels=pixels)
            report = self.execute()
            if passed:
                self.assertEqual(report["status"], "checks_passed", report)
                self.assertFalse(report["alpha_checks"]["target"]["approved"])
            else:
                self.blocked(report, "Alpha")

    def test_edge_and_alpha_declarations_required(self):
        self.image(transparent=True, pixels=bytes([0, 0, 0, 0, 20, 30, 40, 255]) * 2)
        for field in ("alphaVerified", "edgeChecked"):
            self.assets["asset"][field] = False
            self.save("assets.json", self.assets)
            self.blocked(self.execute(), "透明或边缘")
            self.assets["asset"][field] = True

    def test_manifest_file_and_inspection_escape_blocked(self):
        self.image()
        self.assets["asset"]["inspectionFile"] = "../inspection.json"
        self.save("assets.json", self.assets)
        self.blocked(self.execute(), "..")
        self.assets["asset"].pop("inspectionFile")
        self.assets["asset"]["file"] = "../asset.png"
        self.save("assets.json", self.assets)
        self.blocked(self.execute(), "..")

    def test_capture_hash_mismatch_blocked(self):
        report = self.capture()
        report["png_sha256"] = "0" * 64
        self.save("capture.json", report)
        self.blocked(self.execute("capture"), "png_sha256")

    def test_cli_cannot_be_promoted_to_strict(self):
        report = self.capture()
        report["backend"] = "cli"
        self.save("capture.json", report)
        self.blocked(self.execute("capture"), "CLI")

    def test_capture_required_fields_dimensions_readiness_resources(self):
        original = self.capture()
        for field, value in (("actual_width", 7), ("viewport_width", 8), ("device_scale_factor", 1),
                             ("observed_viewport_width", 8), ("readiness_verified", False), ("resource_errors", ["error"]),
                             ("resource_errors", {}), ("status", "unstable"), ("browser_version", ""), ("timestamp", "")):
            with self.subTest(field=field):
                self.save("capture.json", {**original, field: value})
                self.blocked(self.execute("capture"))

    def test_capture_current_png_wrong_dimensions_or_bad(self):
        self.capture()
        for content in (b"bad", compare_images.encode_png(4, 4, bytes(64))):
            (self.root / "current.png").write_bytes(content)
            self.blocked(self.execute("capture"))

    def test_capture_source_hash_still_required(self):
        self.capture()
        write_png(self.root / "source.png", 8, 8, bytes([255, 0, 0, 255]) * 64)
        self.blocked(self.execute("capture"), "sourceSha256")

    def test_capture_dom_missing_duplicate_ids(self):
        original = self.capture()
        for items in ([], original["elements"] + [original["elements"][0]]):
            self.save("capture.json", {**original, "elements": items})
            self.blocked(self.execute("capture"), "DOM")

    def test_capture_geometry_is_report_only_including_rotation(self):
        self.spec["elements"][0]["rotation"] = 45
        self.approve()
        capture = self.capture()
        capture["elements"][0].update(x=100, width=3)
        self.save("capture.json", capture)
        report = self.execute("capture")
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertEqual(report["geometry_deltas"]["target"]["delta"]["x"], 200)
        self.assertEqual(report["geometry_deltas"]["target"]["delta"]["width"], 4)
        self.assertFalse(report["visual_approved"])

    def test_host_capture_and_observed_viewport_match(self):
        capture = self.capture()
        capture.update(backend="host", observed_viewport_width=4, observed_viewport_height=4, observed_device_scale_factor=2)
        self.save("capture.json", capture)
        self.assertEqual(self.execute("capture")["status"], "checks_passed")

    def test_regression_allowed_file_and_target_metrics_not_reject(self):
        self.regression()
        (self.root / "page.css").write_text(".target{color:red}", encoding="utf-8")
        write_png(self.root / "current.png", 8, 8, rgba_from_colors(8, 8, {(0, 0): (255, 0, 0, 255)}, (0, 0, 0, 255)))
        self.capture()
        report = self.execute("regression")
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertEqual(report["region_metrics"]["target"]["changed_pixel_count"], 1)
        self.assertTrue(report["file_checks"]["page.css"]["allowed"])

    def test_regression_nonallowed_tracked_file_change_or_missing(self):
        self.regression()
        (self.root / "other.css").write_text("old", encoding="utf-8")
        self.checkpoint["files"]["other.css"] = self.hash("other.css")
        self.save("checkpoint.json", self.checkpoint)
        (self.root / "other.css").write_text("new", encoding="utf-8")
        self.blocked(self.execute("regression"), "非 allowedFiles")
        (self.root / "other.css").unlink()
        self.blocked(self.execute("regression"))

    def test_regression_checkpoint_paths_escape(self):
        self.regression()
        self.checkpoint["files"]["../outside.css"] = "0" * 64
        self.save("checkpoint.json", self.checkpoint)
        self.blocked(self.execute("regression"), "..")
        self.checkpoint["files"].pop("../outside.css")
        self.save("checkpoint.json", self.checkpoint)
        self.issue["allowedFiles"] = ["../outside.css"]
        self.save("issues.json", self.issue)
        self.blocked(self.execute("regression"), "..")

    def test_regression_cannot_authorize_source_spec_approved_asset(self):
        self.image()
        self.regression()
        for name in ("source.png", "analysis.json", "assets.json", "asset.png"):
            self.issue["allowedFiles"] = [name]
            self.save("issues.json", self.issue)
            self.blocked(self.execute("regression"), "不得授权覆盖")

    def test_regression_approved_asset_hash_cannot_change_when_tracked(self):
        self.image()
        self.regression()
        self.checkpoint["files"]["asset.png"] = self.hash("asset.png")
        self.save("checkpoint.json", self.checkpoint)
        write_png(self.root / "asset.png", 2, 2, bytes([255, 0, 0, 255]) * 4)
        self.blocked(self.execute("regression"), "非 allowedFiles")

    def test_regression_frozen_region_change_needs_review_exit_one(self):
        self.spec["elements"][1].update(freeze=True, status="approved", verificationEvidence="用户原话：冻结 title")
        self.regression()
        write_png(self.root / "current.png", 8, 8, rgba_from_colors(8, 8, {(4, 4): (255, 255, 255, 255)}, (0, 0, 0, 255)))
        self.capture()
        report = self.execute("regression")
        self.assertEqual(report["status"], "needs_review", report)
        self.assertEqual(report["frozen_changes"], ["title"])
        self.assertEqual(report["errors"], [])
        code, output, _ = run_main(validate_project, ["--project-root", str(self.root), "--analysis", "analysis.json", "--stage", "regression",
                                                    "--text-manifest", "text.json", "--asset-manifest", "assets.json", "--current", "current.png",
                                                    "--capture-report", "capture.json", "--baseline", "baseline.png", "--issues", "issues.json",
                                                    "--checkpoint", "checkpoint.json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["status"], "needs_review")

    def test_regression_frozen_hidden_rgb_changes_ignored_white_background(self):
        self.spec["elements"][1].update(freeze=True, status="approved", verificationEvidence="用户原话：冻结 title")
        before = rgba_from_colors(8, 8, {(4, 4): (255, 0, 0, 0)}, (0, 0, 0, 255))
        after = rgba_from_colors(8, 8, {(4, 4): (0, 255, 0, 0)}, (0, 0, 0, 255))
        write_png(self.root / "baseline.png", 8, 8, before)
        write_png(self.root / "current.png", 8, 8, after)
        self.regression()
        report = self.execute("regression")
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertEqual(report["region_metrics"]["title"]["changed_pixel_count"], 0)

    def test_regression_freeze_target_requires_explicit_unfreeze(self):
        self.spec["elements"][0].update(freeze=True, status="approved", verificationEvidence="用户原话：冻结 target")
        self.regression()
        self.blocked(self.execute("regression"), "unfreezeEvidence")
        self.issue["unfreezeEvidence"] = "用户消息引用：允许解冻 target"
        self.save("issues.json", self.issue)
        self.assertEqual(self.execute("regression")["status"], "checks_passed")

    def test_regression_floor_ceil_source_aabb_crop(self):
        self.spec["elements"][0].update(x=0.25, y=0.25, width=1.5, height=1.5, rotation=45)
        self.approve()
        self.regression()
        report = self.execute("regression")
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertEqual(report["region_metrics"]["target"]["source_aabb_crop"], {"x": 0, "y": 0, "width": 2, "height": 2})

    def test_regression_baseline_hash_and_same_path_block(self):
        self.regression()
        self.checkpoint["baselineSha256"] = "0" * 64
        self.save("checkpoint.json", self.checkpoint)
        self.blocked(self.execute("regression"), "baselineSha256")
        self.blocked(self.execute("regression", baseline=Path("current.png")), "不得同一路径")

    def test_regression_stale_issue_and_checkpoint_digest(self):
        self.regression()
        self.issue["analysisDigest"] = "0" * 64
        self.save("issues.json", self.issue)
        self.blocked(self.execute("regression"), "issues analysisDigest")
        self.issue["analysisDigest"] = validate_project.plan_digest(self.spec)
        self.save("issues.json", self.issue)
        self.checkpoint["revision"] = 2
        self.save("checkpoint.json", self.checkpoint)
        self.blocked(self.execute("regression"), "checkpoint revision")

    def test_regression_issue_limit_expansion_and_selected_scope(self):
        self.spec["elements"] += [self.element("third", 2, 2), self.element("fourth", 6, 6)]
        self.approve([e["id"] for e in self.spec["elements"]])
        self.regression()
        self.issue["allowedElementIds"] = [e["id"] for e in self.spec["elements"]]
        self.save("issues.json", self.issue)
        self.blocked(self.execute("regression"), "maxIssues")
        self.issue["maxIssues"] = 4
        self.save("issues.json", self.issue)
        self.blocked(self.execute("regression"), "expansionEvidence")
        self.issue["expansionEvidence"] = "用户消息引用：允许扩大到四个元素"
        self.save("issues.json", self.issue)
        self.assertEqual(self.execute("regression")["status"], "checks_passed")
        self.approve(["target"])
        self.blocked(self.execute("regression"), "不存在")

    def test_candidate_partial_or_stale_review_is_not_approval_gate(self):
        for review in ({"status": "pending"}, {**self.spec["review"], "analysisDigest": "0" * 64}):
            self.spec["review"] = review
            report = self.execute("analysis")
            self.assertEqual(report["status"], "awaiting_user_review", report)
            self.assertEqual(report["selected_element_ids"], [])
            self.assertTrue(any("完整或已过期" in item for item in report["warnings"]))
            self.blocked(self.execute())

    def test_windows_path_objects_and_absolute_cli_inputs(self):
        self.save("analysis.json", self.spec)
        code, output, error = run_main(validate_project, ["--project-root", self.root.as_posix(),
                                                        "--analysis", (self.root / "analysis.json").as_posix(), "--stage", "implementation"])
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["status"], "checks_passed")

    def test_cli_no_abbreviation_or_strict_upgrade_argument(self):
        for extra in (["--strict"], ["--asset", "assets.json"]):
            code, output, _ = run_main(validate_project, ["--project-root", self.root.as_posix(),
                                                        "--analysis", "analysis.json", "--stage", "capture", *extra])
            self.assertEqual(code, 1)
            self.blocked(json.loads(output))

    def test_simulated_symlink_escape_resolved_before_read(self):
        self.spec["sourceFile"] = "link.png"
        (self.root / "link.png").write_bytes(b"mock-link")
        original = Path.resolve
        outside = self.root.parent / "outside.png"
        def resolve(path, *args, **kwargs):
            return outside if path.name == "link.png" else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve), \
             patch.object(validate_project, "read_png", side_effect=AssertionError("不得读逃逸文件")):
            self.blocked(self.execute("analysis"), "符号链接")

    def test_explicit_absolute_outside_root_not_opened(self):
        with patch.object(validate_project, "load_json", side_effect=AssertionError("不得读逃逸输入")):
            self.blocked(self.execute(issues=self.root.parent / "outside.json"), "逃逸")

    def test_nested_manifest_reference_and_inspection_preview_escape(self):
        self.spec["elements"][0]["style"] = {"file": "../outside.png"}
        self.blocked(self.execute("analysis"), "..")
        self.spec["elements"][0].pop("style")
        self.image()
        self.save("inspection.json", {"preview": {"file": "../outside.png"}})
        self.assets["asset"]["inspectionFile"] = "inspection.json"
        self.save("assets.json", self.assets)
        self.blocked(self.execute(), "..")

    def test_inspection_relative_preview_resolves_within_its_directory(self):
        self.image()
        directory = self.root / "inspection"
        directory.mkdir()
        write_png(directory / "preview.png", 1, 1, bytes(4))
        self.save("inspection/report.json", {"asset": "asset.png", "preview": {"file": "preview.png"}})
        self.assets["asset"]["inspectionFile"] = "inspection/report.json"
        self.save("assets.json", self.assets)
        self.assertEqual(self.execute()["status"], "checks_passed")

    def test_capture_geometry_overflow_structured_not_traceback(self):
        capture = self.capture()
        capture["elements"][0]["x"] = 1e308
        self.save("capture.json", capture)
        self.blocked(self.execute("capture"), "有限")
        code, output, _ = run_main(validate_project, ["--project-root", self.root.as_posix(), "--analysis", "analysis.json",
                                                    "--stage", "capture", "--current", "current.png", "--capture-report", "capture.json"])
        self.assertEqual(code, 1)
        self.blocked(json.loads(output))

    def test_capture_image_and_raster_text_both_require_dom_ids(self):
        self.image()
        self.spec["elements"][1]["assetId"] = "asset"
        self.texts["title"].update(renderMode="image", requiredEditable=False)
        self.save("text.json", self.texts)
        self.approve(["target", "title"], raster=["title"])
        original = self.capture()
        for missing in ("target", "title"):
            self.save("capture.json", {**original, "elements": [e for e in original["elements"] if e["id"] != missing]})
            self.blocked(self.execute("capture"), "DOM 缺少")

    def test_receipt_complete_and_user_evidence_required(self):
        original = copy.deepcopy(self.spec["review"])
        for missing in ("revision", "analysisDigest", "confirmedBy", "evidence", "approvedElementIds",
                        "allowGeneratedAssetIds", "allowRasterizedTextIds"):
            self.spec["review"] = {k: v for k, v in original.items() if k != missing}
            self.blocked(self.execute())
        self.spec["review"] = {**original, "confirmedBy": "agent"}
        self.blocked(self.execute(), "user")

    def test_json_nesting_nonfinite_extension_and_bad_root(self):
        nested = {}
        for _ in range(34):
            nested = {"nested": nested}
        for document in (nested, {"extension": float("nan")}, []):
            self.save("extra.json", document)
            self.blocked(self.execute(issues=Path("extra.json")))

    def test_regression_hardlink_cannot_authorize_protected_source(self):
        self.regression()
        alias = self.root / "source-alias.css"
        alias.hardlink_to(self.root / "source.png")
        self.issue["allowedFiles"] = ["source-alias.css"]
        self.save("issues.json", self.issue)
        self.blocked(self.execute("regression"), "硬链接")

    def test_regression_frozen_target_change_still_review_until_flag_cleared(self):
        self.spec["elements"][0].update(freeze=True, status="approved", verificationEvidence="用户消息引用：冻结 target")
        self.regression()
        self.issue["unfreezeEvidence"] = "用户消息引用：允许解冻 target"
        self.save("issues.json", self.issue)
        write_png(self.root / "current.png", 8, 8, rgba_from_colors(8, 8, {(0, 0): (255, 0, 0, 255)}, (0, 0, 0, 255)))
        self.capture()
        self.assertEqual(self.execute("regression")["status"], "needs_review")
        self.spec["elements"][0]["freeze"] = False
        self.assertEqual(self.execute("regression")["status"], "checks_passed")

    def test_regression_wrong_baseline_size_and_untracked_allowed_file(self):
        self.regression()
        write_png(self.root / "small.png", 4, 4, bytes(64))
        self.blocked(self.execute("regression", baseline=Path("small.png")), "物理尺寸")
        (self.root / "new.css").write_text("new", encoding="utf-8")
        self.issue["allowedFiles"] = ["new.css"]
        self.save("issues.json", self.issue)
        self.blocked(self.execute("regression"), "明列追踪")

    def test_regression_does_not_read_unlisted_new_file(self):
        self.regression()
        unlisted = self.root / "untracked.css"
        unlisted.write_text("必须由宿主 diff 核对", encoding="utf-8")
        original = Path.open
        def open_path(path, *args, **kwargs):
            if path == unlisted:
                raise AssertionError("不得读未列文件")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", open_path):
            report = self.execute("regression")
        self.assertEqual(report["status"], "checks_passed", report)
        self.assertTrue(any("未追踪" in item for item in report["limitations"]))

    def test_validator_read_only_no_directory_scan(self):
        self.capture()
        self.save("analysis.json", self.spec)
        with patch.object(Path, "write_text", side_effect=AssertionError("不得写入")), \
             patch.object(Path, "write_bytes", side_effect=AssertionError("不得写入")), \
             patch.object(Path, "iterdir", side_effect=AssertionError("不得扫描")), \
             patch.object(Path, "rglob", side_effect=AssertionError("不得扫描")):
            report = validate_project.validate_project(self.root, Path("analysis.json"), "capture",
                                                       current=Path("current.png"), capture_report=Path("capture.json"))
        self.assertEqual(report["status"], "checks_passed", report)


if __name__ == "__main__":
    unittest.main()
