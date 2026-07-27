"""Derived metadata must survive the repository being moved or copied.

The configuration has always been portable; the catalog, layouts, and
provenance sidecars generated beside the data must be too, or a repository
copied to another machine — or simply to another drive — describes files that
are no longer where it says they are.
"""

import json
import shutil
import unittest
from io import BytesIO
from zipfile import ZipFile

import pyarrow.parquet as pq
from openpyxl import Workbook

from pnadc_https.config import Settings
from pnadc_https.convert import convert_catalog
from pnadc_https.metadata import generate_metadata
from pnadc_https.utils import portable_path
from support import workspace


def _dictionary_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for _ in range(3):
        sheet.append(["header"])
    sheet.append(["Identificação", "", "", "", "", "", "", ""])
    sheet.append([1, 2, "UF", "1", "Unidade da Federação", 11, "Rondônia", "2012-atual"])
    sheet.append([3, 4, "V1008", "8", "Variável", "", "", "2012-atual"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _build(archive):
    docs = archive / "originals" / "trimestral" / "Documentacao"
    data = archive / "originals" / "trimestral" / "2012"
    docs.mkdir(parents=True)
    data.mkdir(parents=True)
    with ZipFile(docs / "Dicionario_e_input.zip", "w") as handle:
        handle.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())
    with ZipFile(data / "PNADC_012012_20250815.zip", "w") as handle:
        handle.writestr("PNADC_012012.txt", "110001\n120042\n")


class PortableMetadataTests(unittest.TestCase):
    def test_portable_path_helper(self):
        with workspace() as tmp_path:
            root = tmp_path / "repo"
            (root / "originals").mkdir(parents=True)
            inside = root / "originals" / "file.zip"
            inside.touch()
            # Relative, and with forward slashes even on Windows.
            self.assertEqual(portable_path(inside, root), "originals/file.zip")
            self.assertNotIn("\\", portable_path(inside, root))
            # Outside the root there is nothing to be relative to.
            outside = tmp_path / "elsewhere.parquet"
            outside.touch()
            self.assertEqual(portable_path(outside, root), str(outside))
            self.assertEqual(portable_path(inside, None), str(inside))

    def test_catalog_records_no_absolute_paths(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            _build(settings.archive)
            generate_metadata(settings)

            raw = (settings.metadata_dir / "catalog.json").read_text(encoding="utf-8")
            self.assertNotIn(str(tmp_path.resolve()), raw)
            self.assertNotIn("\\\\", raw)  # no escaped Windows separators

            catalog = json.loads(raw)
            self.assertEqual(catalog["schema_version"], 2)
            self.assertNotIn("archive", catalog)
            for record in catalog["microdata"] + catalog["layouts"]:
                self.assertFalse(record["source"].startswith(("/", "C:", "c:")))
                self.assertIn("/", record["source"])

            layout_file = next(
                settings.metadata_dir.joinpath("layouts").glob("*.json")
            )
            layout = json.loads(layout_file.read_text(encoding="utf-8"))
            self.assertNotIn("path", layout["source"])
            self.assertNotIn("\\", layout["source"]["archive_path"])

    def test_provenance_records_paths_relative_to_the_repository(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            _build(settings.archive)
            generate_metadata(settings)
            convert_catalog(settings)

            sidecar = (
                settings.parquet_dir
                / "trimestral"
                / "2012"
                / "PNADC_012012.parquet.provenance.json"
            )
            provenance = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(provenance["paths_relative_to"], "repository root")
            self.assertEqual(
                provenance["source"],
                "originals/trimestral/2012/PNADC_012012_20250815.zip",
            )
            self.assertNotIn("\\", provenance["layout"])
            self.assertNotIn(str(tmp_path.resolve()), sidecar.read_text(encoding="utf-8"))

    def test_repository_still_works_after_being_moved(self):
        with workspace() as tmp_path:
            original = tmp_path / "original"
            settings = Settings(archive=original)
            _build(original)
            generate_metadata(settings)
            convert_catalog(settings)
            before = (original / "metadata" / "catalog.json").read_bytes()

            # Move the whole repository, as if copied to another drive.
            moved = tmp_path / "moved"
            shutil.move(str(original), str(moved))
            relocated = Settings(archive=moved)

            # The catalog is byte-identical: it contained nothing about where
            # the repository happened to live.
            self.assertEqual((moved / "metadata" / "catalog.json").read_bytes(), before)

            # And it still describes real files, so nothing is reconverted.
            self.assertEqual(convert_catalog(relocated), (0, 1, 0))
            output = relocated.parquet_dir / "trimestral" / "2012" / "PNADC_012012.parquet"
            self.assertEqual(pq.read_table(output).to_pydict()["uf"], [11, 12])


if __name__ == "__main__":
    unittest.main()
