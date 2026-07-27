import unittest
from pathlib import Path

from pnadc_https.config import load_settings
from support import workspace


class ConfigTests(unittest.TestCase):
    def test_config_archive_is_relative_to_config(self):
        with workspace() as tmp_path:
            config = tmp_path / "config.yml"
            config.write_text("archive: data\nnetwork:\n  workers: 2\n", encoding="utf-8")
            settings = load_settings(config)
            self.assertEqual(settings.archive, (tmp_path / "data").resolve())
            self.assertEqual(settings.originals, (tmp_path / "data" / "originals").resolve())
            self.assertEqual(settings.metadata_dir, (tmp_path / "data" / "metadata").resolve())
            self.assertEqual(settings.parquet_dir, (tmp_path / "data" / "parquet").resolve())
            self.assertEqual(settings.csv_dir, (tmp_path / "data" / "csv").resolve())
            self.assertEqual(settings.network.workers, 2)

    def test_config_csv_directory_is_overridable(self):
        with workspace() as tmp_path:
            config = tmp_path / "config.yml"
            config.write_text("archive: data\ncsv: exports\n", encoding="utf-8")
            settings = load_settings(config)
            self.assertEqual(settings.csv_dir, (tmp_path / "exports").resolve())
