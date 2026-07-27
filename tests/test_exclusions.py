"""Superseded trees, adopted files, and multi-year dictionaries.

Each of these was found by enumerating IBGE's real tree: the archive is 44%
superseded projections, an archive whose manifest is missing would be
re-downloaded in full, and some annual dictionaries cover a span of years.
"""

import json
import unittest
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook

from pnadc_https.config import DEFAULT_EXCLUDE, Settings, load_settings
from pnadc_https.metadata import _covered_years, generate_metadata
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


class ExclusionTests(unittest.TestCase):
    def test_superseded_projections_are_excluded_by_default(self):
        settings = Settings(archive="unused")
        self.assertEqual(settings.exclude, DEFAULT_EXCLUDE)
        self.assertTrue(settings.is_excluded("anual/Projecoes_Anteriores/Projecao_2021/x.zip"))
        self.assertTrue(settings.is_excluded("trimestral\\Projecoes_Anteriores\\x.zip"))
        self.assertFalse(settings.is_excluded("trimestral/2025/PNADC_012025.zip"))
        self.assertFalse(settings.is_excluded("anual/Visita/Visita_1/Dados/x.zip"))

    def test_exclusions_can_be_configured_and_cleared(self):
        with workspace() as tmp_path:
            config = tmp_path / "pnadc.yml"
            config.write_text("archive: .\n", encoding="utf-8")
            self.assertEqual(load_settings(config).exclude, DEFAULT_EXCLUDE)

            # An explicit empty list means "exclude nothing", which differs
            # from the key being absent.
            config.write_text("archive: .\nexclude: []\n", encoding="utf-8")
            settings = load_settings(config)
            self.assertEqual(settings.exclude, ())
            self.assertFalse(settings.is_excluded("anual/Projecoes_Anteriores/x.zip"))

            config.write_text("archive: .\nexclude: [Trimestre_3]\n", encoding="utf-8")
            settings = load_settings(config)
            self.assertTrue(settings.is_excluded("anual/Trimestre/Trimestre_3/x.zip"))
            self.assertFalse(settings.is_excluded("anual/Projecoes_Anteriores/x.zip"))

    def test_excluded_files_already_on_disk_are_not_cataloged(self):
        # A repository synced before the exclusion existed still holds the
        # files; they must not be silently cataloged and converted.
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            docs = settings.originals / "trimestral" / "Documentacao"
            wanted = settings.originals / "trimestral" / "2025"
            superseded = settings.originals / "trimestral" / "Projecoes_Anteriores" / "Projecao_2021"
            for directory in (docs, wanted, superseded):
                directory.mkdir(parents=True)
            with ZipFile(docs / "Dicionario_e_input.zip", "w") as handle:
                handle.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())
            with ZipFile(wanted / "PNADC_012025.zip", "w") as handle:
                handle.writestr("PNADC_012025.txt", "110001\n120042\n")
            with ZipFile(superseded / "proj_tri_012012.zip", "w") as handle:
                handle.writestr("proj_tri_012012.txt", "110001\n120042\n")

            catalog = generate_metadata(settings)
            sources = [record["source"] for record in catalog["microdata"]]
            self.assertEqual(len(sources), 1)
            self.assertNotIn("Projecoes_Anteriores", " ".join(sources))

            # Opting in picks the superseded file up.
            settings.exclude = ()
            catalog = generate_metadata(settings, force=True)
            sources = [record["source"] for record in catalog["microdata"]]
            self.assertEqual(len(sources), 2)
            self.assertIn("Projecoes_Anteriores", " ".join(sources))


class CoveredYearTests(unittest.TestCase):
    def test_multi_year_dictionary_names_expand(self):
        # IBGE ships one dictionary for 2012-2014 of the annual visit data.
        self.assertEqual(
            _covered_years("dicionario_PNADC_microdados_2012_a_2014_visita1_20220224.xls"),
            {2012, 2013, 2014},
        )
        self.assertEqual(
            _covered_years("dicionario_PNADC_microdados_2015_visita1_20220224.xls"), {2015}
        )
        # A trailing revision date is not a survey year.
        self.assertEqual(_covered_years("PNADC_2013_visita1_20250822.zip"), {2013})
        self.assertEqual(_covered_years("no_year_here.xls"), set())

    def test_data_inside_a_dictionary_span_resolves(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            docs = settings.originals / "anual" / "Visita" / "Visita_1" / "Documentacao"
            data = settings.originals / "anual" / "Visita" / "Visita_1" / "Dados"
            docs.mkdir(parents=True)
            data.mkdir(parents=True)
            (docs / "dicionario_PNADC_microdados_2012_a_2014_visita1_20220224.xlsx").write_bytes(
                _dictionary_bytes()
            )
            for year in (2012, 2013, 2014):
                with ZipFile(data / f"PNADC_{year}_visita1_20250822.zip", "w") as handle:
                    handle.writestr(f"PNADC_{year}_visita1.txt", "110001\n120042\n")

            catalog = generate_metadata(settings)
            self.assertEqual(len(catalog["layouts"]), 1)
            self.assertEqual(sorted(catalog["layouts"][0]["years"]), [2012, 2013, 2014])

            # Every year in the span resolves, not only the first.
            resolved = {
                record["year"]: record["layout"] for record in catalog["microdata"]
            }
            self.assertEqual(sorted(resolved), [2012, 2013, 2014])
            for year, layout in resolved.items():
                self.assertIsNotNone(layout, f"{year} was left unresolved")


if __name__ == "__main__":
    unittest.main()
