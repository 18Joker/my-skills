from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble_page.py"


class AssemblePageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new("RGBA", (8, 5), (255, 0, 0, 255)).save(self.root / "a.png")
        Image.new("RGBA", (8, 3), (0, 0, 255, 128)).save(self.root / "b.png")
        self.data = {"expected_sections": ["a", "b"], "sections": [{"id": "a", "image": "a.png"}, {"id": "b", "image": "b.png"}]}
        self.output = self.root / "page.png"

    def run_cli(self, *extra):
        manifest = self.root / "page.json"
        manifest.write_text(json.dumps(self.data))
        return subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--output", str(self.output), *extra], capture_output=True, text=True, cwd=self.root.parent)

    def test_cli_preserves_order_dimensions_pixels_and_relative_paths(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(self.output) as im:
            self.assertEqual(im.size, (8, 8))
            self.assertEqual(im.getpixel((0, 4)), (255, 0, 0, 255))
            self.assertEqual(im.getpixel((0, 5)), (0, 0, 255, 128))

    def test_rejects_wrong_width_without_writing_output(self):
        Image.new("RGB", (7, 3)).save(self.root / "b.png")
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_rejects_missing_reordered_and_duplicate_sections(self):
        for sections in ([self.data["sections"][0]], list(reversed(self.data["sections"])), [self.data["sections"][0]] * 2):
            with self.subTest(sections=sections):
                original = self.data["sections"]
                self.data["sections"] = sections
                self.assertNotEqual(self.run_cli().returncode, 0)
                self.assertFalse(self.output.exists())
                self.data["sections"] = original

    def test_rejects_corrupt_source_and_preserves_existing_output(self):
        self.output.write_bytes(b"existing")
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.output.read_bytes(), b"existing")
        (self.root / "b.png").write_bytes(b"broken")
        self.assertNotEqual(self.run_cli("--force").returncode, 0)
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_force_replaces_output_after_validation(self):
        self.output.write_bytes(b"existing")
        self.assertEqual(self.run_cli("--force").returncode, 0)
        with Image.open(self.output) as im:
            self.assertEqual(im.size, (8, 8))

    def test_rejects_duplicate_image_and_overwriting_source(self):
        self.data["sections"][1]["image"] = "a.png"
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.data["sections"][1]["image"] = "b.png"
        self.output = self.root / "a.png"
        before = self.output.read_bytes()
        self.assertNotEqual(self.run_cli("--force").returncode, 0)
        self.assertEqual(self.output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
