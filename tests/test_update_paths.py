"""Maintenance scenarios: keeping standardized output in step with IBGE.

These cover the update paths where a stale output would be silently wrong
rather than obviously broken, which is the failure mode that matters most
for a repository meant to be re-synchronized over years.
"""

import time
import unittest
from io import BytesIO
from zipfile import ZipFile

import pyarrow.parquet as pq
from openpyxl import Workbook

from pnadc_https.config import Settings
from pnadc_https.convert import convert_catalog
from pnadc_https.metadata import generate_metadata
from support import workspace


def _dictionary_bytes(second_variable: str = "V1008") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for _ in range(3):
        sheet.append(["header"])
    sheet.append(["Identificação", "", "", "", "", "", "", ""])
    sheet.append([1, 2, "UF", "1", "Unidade da Federação", 11, "Rondônia", "2012-atual"])
    sheet.append([3, 4, second_variable, "8", "Variável", "", "", "2012-atual"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class UpdatePathTests(unittest.TestCase):
    def _repository(self, tmp_path):
        settings = Settings(archive=tmp_path / "archive")
        self.docs = settings.originals / "trimestral" / "Documentacao"
        self.data = settings.originals / "trimestral" / "2012"
        self.docs.mkdir(parents=True)
        self.data.mkdir(parents=True)
        self.dictionary_path = self.docs / "Dicionario_e_input.zip"
        self._write_dictionary()
        return settings

    def _write_dictionary(self, second_variable: str = "V1008") -> None:
        with ZipFile(self.dictionary_path, "w") as archive:
            archive.writestr(
                "dicionario_PNADC_microdados_trimestral.xlsx",
                _dictionary_bytes(second_variable),
            )

    def _write_data(self, name: str, content: str) -> None:
        with ZipFile(self.data / name, "w") as archive:
            archive.writestr("PNADC_012012.txt", content)

    @staticmethod
    def _output(settings):
        return settings.parquet_dir / "trimestral" / "2012" / "PNADC_012012.parquet"

    def test_unchanged_inputs_are_skipped(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            self.assertEqual(convert_catalog(settings), (1, 0, 0))
            # A second run must not redo the work; this is what makes routine
            # re-synchronization cheap.
            self.assertEqual(convert_catalog(settings), (0, 1, 0))

    def test_revised_release_replaces_the_standardized_output(self):
        # PNADC_012012_20250815.zip and PNADC_012012_20260701.zip both map to
        # PNADC_012012.parquet, so an existence check would keep the old data.
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            convert_catalog(settings)
            self.assertEqual(pq.read_table(self._output(settings)).to_pydict()["uf"], [11, 12])

            (self.data / "PNADC_012012_20250815.zip").unlink()
            self._write_data("PNADC_012012_20260701.zip", "990009\n880088\n")
            generate_metadata(settings)
            converted, skipped, _ = convert_catalog(settings)

            self.assertEqual((converted, skipped), (1, 0))
            self.assertEqual(pq.read_table(self._output(settings)).to_pydict()["uf"], [99, 88])

    def test_source_replaced_under_the_same_name_is_reconverted(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            convert_catalog(settings)

            time.sleep(0.01)  # ensure a distinct modification time
            self._write_data("PNADC_012012_20250815.zip", "770007\n660066\n550055\n")
            generate_metadata(settings)
            converted, skipped, _ = convert_catalog(settings)

            self.assertEqual((converted, skipped), (1, 0))
            self.assertEqual(pq.read_table(self._output(settings)).num_rows, 3)

    def test_revised_dictionary_is_reparsed_and_invalidates_output(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            convert_catalog(settings)
            self.assertEqual(
                pq.read_table(self._output(settings)).column_names, ["uf", "v1008"]
            )

            # IBGE reissues the dictionary with a different variable.
            self._write_dictionary("V2007")
            generate_metadata(settings)
            converted, skipped, _ = convert_catalog(settings)

            self.assertEqual((converted, skipped), (1, 0))
            self.assertEqual(
                pq.read_table(self._output(settings)).column_names, ["uf", "v2007"]
            )

    def test_changed_column_selection_invalidates_output(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            convert_catalog(settings)

            converted, skipped, _ = convert_catalog(settings, columns=["uf"])
            self.assertEqual((converted, skipped), (1, 0))
            self.assertEqual(pq.read_table(self._output(settings)).column_names, ["uf"])

            # Selecting the same columns again is a no-op.
            self.assertEqual(convert_catalog(settings, columns=["uf"]), (0, 1, 0))

    def test_unknown_batch_column_is_a_configuration_error(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012.zip", "110001\n120042\n")
            generate_metadata(settings)

            with self.assertRaisesRegex(ValueError, "Unknown column"):
                convert_catalog(settings, columns=["not_a_variable"])

    def test_changed_all_string_invalidates_output(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            convert_catalog(settings)
            self.assertEqual(
                pq.read_table(self._output(settings)).schema.field("uf").type, "int8"
            )

            converted, skipped, _ = convert_catalog(settings, all_string=True)
            self.assertEqual((converted, skipped), (1, 0))
            self.assertEqual(
                pq.read_table(self._output(settings)).schema.field("uf").type, "string"
            )

    def test_csv_and_parquet_outputs_are_tracked_independently(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            self._write_data("PNADC_012012_20250815.zip", "110001\n120042\n")
            generate_metadata(settings)
            self.assertEqual(convert_catalog(settings), (1, 0, 0))
            # A different format is a different output, not a stale one.
            self.assertEqual(convert_catalog(settings, output_format="csv"), (1, 0, 0))
            self.assertEqual(convert_catalog(settings, output_format="csv"), (0, 1, 0))


if __name__ == "__main__":
    unittest.main()
