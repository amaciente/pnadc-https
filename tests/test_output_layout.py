"""The flat, `pynad`-style output layout.

`pynad` keeps every converted file in one directory, with the survey, period
and edition carried by the filename. That is convenient for globbing a whole
series at once. The nested layout mirroring the IBGE tree remains the default,
because changing it moves every existing output.
"""

import unittest
from io import BytesIO
from zipfile import ZipFile

import pyarrow.parquet as pq
from openpyxl import Workbook

from pnadc_https.config import Settings, load_settings
from pnadc_https.convert import convert_catalog, pynad_output_stem
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


class PynadNamingTests(unittest.TestCase):
    def test_quarterly_names_match_pynad(self):
        self.assertEqual(
            pynad_output_stem("PNADC_012012_20250815.zip", "trimestral"),
            "pnadc.microdados.trimestral.2012.1",
        )
        # An undated release names identically; the revision is not part of it.
        self.assertEqual(
            pynad_output_stem("PNADC_042025.zip", "trimestral"),
            "pnadc.microdados.trimestral.2025.4",
        )

    def test_annual_names_match_pynad(self):
        self.assertEqual(
            pynad_output_stem("PNADC_2012_visita1_20250822.zip", "anual"),
            "pnadc.microdados.anual.visita1.2012",
        )
        self.assertEqual(
            pynad_output_stem("PNADC_2023_trimestre1.zip", "anual"),
            "pnadc.microdados.anual.trimestre1.2023",
        )

    def test_unrecognised_names_are_not_mangled(self):
        stem = pynad_output_stem("something_else.zip", "trimestral")
        self.assertEqual(stem, "pnadc.microdados.trimestral.something_else")


class FlatLayoutTests(unittest.TestCase):
    def _repository(self, tmp_path, layout):
        settings = Settings(archive=tmp_path / "archive", output_layout=layout)
        docs = settings.originals / "trimestral" / "Documentacao"
        docs.mkdir(parents=True)
        with ZipFile(docs / "Dicionario_e_input.zip", "w") as handle:
            handle.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())
        for year, quarter in ((2012, 1), (2013, 2)):
            folder = settings.originals / "trimestral" / str(year)
            folder.mkdir(parents=True, exist_ok=True)
            with ZipFile(folder / f"PNADC_0{quarter}{year}_20250815.zip", "w") as handle:
                handle.writestr(f"PNADC_0{quarter}{year}.txt", "110001\n120042\n")
        return settings

    def test_flat_layout_writes_one_directory(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path, "flat")
            generate_metadata(settings)
            self.assertEqual(convert_catalog(settings), (2, 0, 0))

            files = sorted(p.name for p in settings.parquet_dir.glob("*.parquet"))
            self.assertEqual(
                files,
                [
                    "pnadc.microdados.trimestral.2012.1.parquet",
                    "pnadc.microdados.trimestral.2013.2.parquet",
                ],
            )
            # No survey or year directories were created.
            self.assertEqual([d.name for d in settings.parquet_dir.iterdir() if d.is_dir()], [])
            table = pq.read_table(settings.parquet_dir / files[0])
            self.assertEqual(table.to_pydict(), {"uf": [11, 12], "v1008": [1, 42]})

    def test_nested_remains_the_default(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path, "nested")
            generate_metadata(settings)
            convert_catalog(settings)
            self.assertTrue(
                (settings.parquet_dir / "trimestral" / "2012" / "PNADC_012012.parquet").is_file()
            )

    def test_flat_layout_is_still_idempotent(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path, "flat")
            generate_metadata(settings)
            self.assertEqual(convert_catalog(settings), (2, 0, 0))
            self.assertEqual(convert_catalog(settings), (0, 2, 0))

    def test_flat_layout_collapses_retained_revisions(self):
        # Two revisions of one quarter share a flat name just as they share a
        # nested one, so only the newer may be written.
        with workspace() as tmp_path:
            settings = self._repository(tmp_path, "flat")
            folder = settings.originals / "trimestral" / "2012"
            with ZipFile(folder / "PNADC_012012_20260701.zip", "w") as handle:
                handle.writestr("PNADC_012012.txt", "990009\n880088\n")
            generate_metadata(settings)
            converted, skipped, unresolved = convert_catalog(settings)

            self.assertEqual((converted, skipped, unresolved), (2, 0, 0))
            output = settings.parquet_dir / "pnadc.microdados.trimestral.2012.1.parquet"
            self.assertEqual(pq.read_table(output).to_pydict()["uf"], [99, 88])

    def test_layout_is_configurable_and_validated(self):
        with workspace() as tmp_path:
            config = tmp_path / "pnadc.yml"
            config.write_text("archive: .\noutput_layout: flat\n", encoding="utf-8")
            self.assertEqual(load_settings(config).output_layout, "flat")

            config.write_text("archive: .\n", encoding="utf-8")
            self.assertEqual(load_settings(config).output_layout, "nested")

            config.write_text("archive: .\noutput_layout: sideways\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(config)

    def test_empty_flat_catalog_writes_an_empty_index(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive", output_layout="flat")
            settings.metadata_dir.mkdir(parents=True)
            (settings.metadata_dir / "catalog.json").write_text(
                '{"microdata": []}\n', encoding="utf-8"
            )

            self.assertEqual(convert_catalog(settings), (0, 0, 0))
            index = settings.parquet_dir / "pnadc.microdados.dicionarios.json"
            self.assertTrue(index.is_file())
            self.assertEqual(index.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
