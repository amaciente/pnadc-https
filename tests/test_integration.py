import unittest
from io import BytesIO
from zipfile import ZipFile

import pyarrow.parquet as pq
from openpyxl import Workbook

from pnadc.config import Settings
from pnadc.convert import convert_catalog
from pnadc.metadata import generate_metadata
from support import workspace


def _dictionary_bytes(second_variable: str = "V1008") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["header"])
    sheet.append(["header"])
    sheet.append(["header"])
    sheet.append(["Identificação", "", "", "", "", "", "", ""])
    sheet.append([1, 2, "UF", "1", "Unidade da Federação", 11, "Rondônia", "2012-atual"])
    sheet.append([3, 4, second_variable, "8", "Variável", "", "", "2012-atual"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class IntegrationTests(unittest.TestCase):
    def test_catalog_and_batch_conversion(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            docs = settings.originals / "trimestral" / "Documentacao"
            data = settings.originals / "trimestral" / "2025"
            docs.mkdir(parents=True)
            data.mkdir(parents=True)

            dictionary_zip = docs / "Dicionario_e_input.zip"
            with ZipFile(dictionary_zip, "w") as archive:
                archive.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())
            data_zip = data / "PNADC_012025.zip"
            with ZipFile(data_zip, "w") as archive:
                archive.writestr("PNADC_012025.txt", "110001\n120042\n")

            catalog = generate_metadata(settings)
            self.assertEqual(len(catalog["layouts"]), 1)
            self.assertEqual(len(catalog["microdata"]), 1)
            self.assertEqual(catalog["microdata"][0]["quarter"], 1)
            self.assertIsNotNone(catalog["microdata"][0]["layout"])

            converted, skipped, unresolved = convert_catalog(settings)
            self.assertEqual((converted, skipped, unresolved), (1, 0, 0))
            output = settings.parquet_dir / "trimestral" / "2025" / "PNADC_012025.parquet"
            self.assertEqual(pq.read_table(output).to_pydict(), {"uf": [11, 12], "v1008": [1, 42]})

    def test_batch_conversion_to_csv(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            docs = settings.originals / "trimestral" / "Documentacao"
            data = settings.originals / "trimestral" / "2025"
            docs.mkdir(parents=True)
            data.mkdir(parents=True)

            dictionary_zip = docs / "Dicionario_e_input.zip"
            with ZipFile(dictionary_zip, "w") as archive:
                archive.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())
            data_zip = data / "PNADC_012025.zip"
            with ZipFile(data_zip, "w") as archive:
                archive.writestr("PNADC_012025.txt", "110001\n120042\n")

            generate_metadata(settings)
            converted, skipped, unresolved = convert_catalog(settings, output_format="csv")
            self.assertEqual((converted, skipped, unresolved), (1, 0, 0))
            output = settings.csv_dir / "trimestral" / "2025" / "PNADC_012025.csv"
            self.assertEqual(output.read_text(encoding="utf-8").splitlines(), ["uf,v1008", "11,0001", "12,0042"])

    def test_anual_visita_and_trimestre_never_cross_match(self):
        # Anual/Visita and Anual/Trimestre are separate IBGE products that
        # merely share the same "anual" URL tree; a dictionary from one must
        # never be picked for data from the other (see metadata._anual_kind).
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            visita_docs = settings.originals / "anual" / "Visita" / "Documentacao_Geral"
            visita_data = settings.originals / "anual" / "Visita" / "Visita_1" / "2022"
            trimestre_docs = settings.originals / "anual" / "Trimestre" / "Documentacao_Geral"
            trimestre_data = settings.originals / "anual" / "Trimestre" / "Trimestre_2" / "2022"
            for directory in (visita_docs, visita_data, trimestre_docs, trimestre_data):
                directory.mkdir(parents=True)

            with ZipFile(visita_docs / "Dicionario_visita.zip", "w") as archive:
                archive.writestr("dicionario_visita.xlsx", _dictionary_bytes("V2007"))
            with ZipFile(visita_data / "PNADC_2022_visita1.zip", "w") as archive:
                archive.writestr("PNADC_2022_visita1.txt", "110001\n120042\n")

            with ZipFile(trimestre_docs / "Dicionario_trimestre.zip", "w") as archive:
                archive.writestr("dicionario_trimestre.xlsx", _dictionary_bytes("S07006"))
            with ZipFile(trimestre_data / "PNADC_2022_trimestre2.zip", "w") as archive:
                archive.writestr("PNADC_2022_trimestre2.txt", "110001\n120042\n")

            catalog = generate_metadata(settings)
            self.assertEqual(len(catalog["layouts"]), 2)
            by_source = {record["source"]: record for record in catalog["microdata"]}
            visita_record = next(r for path, r in by_source.items() if "Visita" in path)
            trimestre_record = next(r for path, r in by_source.items() if "Trimestre" in path)
            self.assertIn("visita", visita_record["layout_id"])
            self.assertIn("trimestre", trimestre_record["layout_id"])
            self.assertNotEqual(visita_record["layout"], trimestre_record["layout"])

            convert_catalog(settings, scope="anual")
            visita_output = settings.parquet_dir / "anual" / "Visita" / "Visita_1" / "2022" / "PNADC_2022_visita1.parquet"
            trimestre_output = settings.parquet_dir / "anual" / "Trimestre" / "Trimestre_2" / "2022" / "PNADC_2022_trimestre2.parquet"
            self.assertEqual(set(pq.read_table(visita_output).column_names), {"uf", "v2007"})
            self.assertEqual(set(pq.read_table(trimestre_output).column_names), {"uf", "s07006"})
