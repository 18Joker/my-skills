#!/usr/bin/env python3
"""Offline tests using generated PNGs and temporary directories only."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import check_environment
import compare_images
import inspect_assets
import prepare_reference


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


if __name__ == "__main__":
    unittest.main()
