"""Two lifecycle hazards: retained revisions, and re-extracting a changed ZIP.

Synchronization never deletes a superseded revision, so a repository can hold
`PNADC_012012_20250815.zip` and `PNADC_012012_20260701.zip` at once. Both map
to one output name. Separately, a ZIP whose contents changed must not keep the
previous revision's extracted members while recording the new fingerprint.
"""

import json
import unittest
from io import BytesIO
from zipfile import ZipFile

import pyarrow.parquet as pq
from openpyxl import Workbook

from pnadc_https.config import Settings
from pnadc_https.convert import _preferred_revisions, convert_catalog
from pnadc_https.extract import extract_archive
from pnadc_https.metadata import generate_metadata
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


class RevisionSelectionTests(unittest.TestCase):
    def test_newest_revision_wins(self):
        records = [
            {"scope": "trimestral", "source": "originals/trimestral/2012/PNADC_012012_20250815.zip"},
            {"scope": "trimestral", "source": "originals/trimestral/2012/PNADC_012012_20260701.zip"},
        ]
        for ordering in (records, list(reversed(records))):
            chosen = _preferred_revisions(ordering, "parquet")
            self.assertEqual(len(chosen), 1)
            self.assertIn("20260701", chosen[0]["source"])

    def test_distinct_outputs_are_all_kept(self):
        records = [
            {"scope": "trimestral", "source": "originals/trimestral/2012/PNADC_012012_20250815.zip"},
            {"scope": "trimestral", "source": "originals/trimestral/2012/PNADC_022012_20250815.zip"},
        ]
        self.assertEqual(len(_preferred_revisions(records, "parquet")), 2)

    def test_both_revisions_on_disk_convert_once_to_the_newer_data(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            docs = settings.originals / "trimestral" / "Documentacao"
            data = settings.originals / "trimestral" / "2012"
            docs.mkdir(parents=True)
            data.mkdir(parents=True)
            with ZipFile(docs / "Dicionario_e_input.zip", "w") as handle:
                handle.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())

            # The old revision is retained; sync only removes it under --prune.
            with ZipFile(data / "PNADC_012012_20250815.zip", "w") as handle:
                handle.writestr("PNADC_012012.txt", "110001\n120042\n")
            with ZipFile(data / "PNADC_012012_20260701.zip", "w") as handle:
                handle.writestr("PNADC_012012.txt", "990009\n880088\n")

            generate_metadata(settings)
            converted, skipped, unresolved = convert_catalog(settings)

            # One output, converted once, holding the newer revision's data.
            self.assertEqual((converted, skipped, unresolved), (1, 0, 0))
            output = settings.parquet_dir / "trimestral" / "2012" / "PNADC_012012.parquet"
            self.assertEqual(pq.read_table(output).to_pydict()["uf"], [99, 88])

            # And re-running is a no-op rather than a second write.
            self.assertEqual(convert_catalog(settings), (0, 1, 0))


class ExtractionRefreshTests(unittest.TestCase):
    def _archive(self, settings, members):
        path = settings.originals / "trimestral" / "2012" / "PNADC_012012.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(path, "w") as handle:
            for name, content in members.items():
                handle.writestr(name, content)
        return path

    def test_changed_archive_replaces_extracted_members(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            source = self._archive(settings, {"PNADC_012012.txt": "old contents"})
            self.assertEqual(extract_archive(settings), (1, 0))
            extracted = settings.archive / "extracted" / "trimestral" / "2012" / "PNADC_012012" / "PNADC_012012.txt"
            self.assertEqual(extracted.read_text(encoding="utf-8"), "old contents")

            # IBGE reissues the archive with different contents.
            source.unlink()
            self._archive(settings, {"PNADC_012012.txt": "new contents"})
            processed, skipped = extract_archive(settings)

            self.assertEqual((processed, skipped), (1, 0))
            self.assertEqual(extracted.read_text(encoding="utf-8"), "new contents")

    def test_members_dropped_from_a_new_revision_are_removed(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            source = self._archive(
                settings, {"keep.txt": "kept", "gone.txt": "obsolete"}
            )
            extract_archive(settings)
            base = settings.archive / "extracted" / "trimestral" / "2012" / "PNADC_012012"
            self.assertTrue((base / "gone.txt").is_file())

            source.unlink()
            self._archive(settings, {"keep.txt": "kept"})
            extract_archive(settings)

            self.assertTrue((base / "keep.txt").is_file())
            self.assertFalse(
                (base / "gone.txt").exists(),
                "a member removed upstream should not survive extraction",
            )

    def test_unchanged_archive_is_skipped(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            self._archive(settings, {"PNADC_012012.txt": "contents"})
            self.assertEqual(extract_archive(settings), (1, 0))
            self.assertEqual(extract_archive(settings), (0, 1))

    def test_excluded_archives_are_not_extracted(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            superseded = settings.originals / "trimestral" / "Projecoes_Anteriores"
            superseded.mkdir(parents=True)
            with ZipFile(superseded / "proj_tri_012012.zip", "w") as handle:
                handle.writestr("proj.txt", "superseded")
            self.assertEqual(extract_archive(settings), (0, 0))

            settings.exclude = ()
            self.assertEqual(extract_archive(settings), (1, 0))

    def test_pruned_source_removes_recorded_extracted_derivatives(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            source = self._archive(settings, {"PNADC_012012.txt": "contents"})
            extract_archive(settings)
            output = (
                settings.archive
                / "extracted"
                / "trimestral"
                / "2012"
                / "PNADC_012012"
                / "PNADC_012012.txt"
            )
            self.assertTrue(output.is_file())

            source.unlink()
            self.assertEqual(extract_archive(settings), (0, 0))
            self.assertFalse(output.exists())
            state = json.loads(
                (settings.state_dir / "extracted.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["files"], {})

    def test_uppercase_zip_extension_is_extracted(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            source = (
                settings.originals
                / "trimestral"
                / "2012"
                / "PNADC_012012.ZIP"
            )
            source.parent.mkdir(parents=True)
            with ZipFile(source, "w") as handle:
                handle.writestr("PNADC_012012.txt", "contents")

            self.assertEqual(extract_archive(settings), (1, 0))


if __name__ == "__main__":
    unittest.main()
