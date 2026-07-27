import unittest
from pathlib import Path
from zipfile import ZipFile

from pnadc_https.extract import extract_zip
from support import workspace


class ExtractTests(unittest.TestCase):
    def test_extract_zip_and_reject_traversal(self):
        with workspace() as tmp_path:
            good = tmp_path / "good.zip"
            with ZipFile(good, "w") as archive:
                archive.writestr("folder/data.txt", "123\n")
            outputs = extract_zip(good, tmp_path / "out")
            self.assertEqual(outputs[0].read_text(encoding="utf-8"), "123\n")

            bad = tmp_path / "bad.zip"
            with ZipFile(bad, "w") as archive:
                archive.writestr("../escape.txt", "no")
            with self.assertRaisesRegex(ValueError, "Unsafe ZIP member"):
                extract_zip(bad, tmp_path / "unsafe")
