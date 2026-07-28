"""Output that `pynad` can consume directly.

`pynad`'s panel stage does not list the output directory. It reads an index,
`pnadc.microdados.dicionarios.json`, one JSON object per line, and selects
files by the `.trimestral.` / `.anual.visita` / `.anual.trimestre` markers in
each name, taking the period from the name's last components:

    ano = int(name.split('.')[-3])
    tri = int(name.split('.')[-2])

Writing that index means a repository built here can be handed to `pynad` for
panel assembly as though `pynad` had produced it.
"""

import json
import unittest
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook

from pnadc_https.config import Settings
from pnadc_https.convert import PYNAD_INDEX_NAME, convert_catalog
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


class PynadIndexTests(unittest.TestCase):
    def _repository(self, tmp_path):
        settings = Settings(archive=tmp_path / "archive", output_layout="flat")
        docs = settings.originals / "trimestral" / "Documentacao"
        docs.mkdir(parents=True)
        with ZipFile(docs / "Dicionario_e_input.zip", "w") as handle:
            handle.writestr("dicionario_PNADC_microdados_trimestral.xlsx", _dictionary_bytes())

        quarterly = settings.originals / "trimestral" / "2012"
        quarterly.mkdir(parents=True)
        for quarter in (1, 2):
            with ZipFile(quarterly / f"PNADC_0{quarter}2012_20250815.zip", "w") as handle:
                handle.writestr(f"PNADC_0{quarter}2012.txt", "110001\n120042\n")

        visita = settings.originals / "anual" / "Visita" / "Visita_1" / "Dados"
        visita.mkdir(parents=True)
        with ZipFile(visita / "PNADC_2012_visita1_20250822.zip", "w") as handle:
            handle.writestr("PNADC_2012_visita1.txt", "110001\n120042\n")
        vdocs = settings.originals / "anual" / "Visita" / "Visita_1" / "Documentacao"
        vdocs.mkdir(parents=True)
        (vdocs / "dicionario_PNADC_microdados_2012_visita1.xlsx").write_bytes(
            _dictionary_bytes()
        )
        return settings

    def test_index_is_written_and_parses_the_way_pynad_reads_it(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            generate_metadata(settings)
            convert_catalog(settings)

            index = settings.parquet_dir / PYNAD_INDEX_NAME
            self.assertTrue(index.is_file())

            # pynad: [loads(reg[:-1]) for reg in src] — one object per line,
            # each line ending in a newline.
            with index.open(encoding="utf-8") as handle:
                records = [json.loads(line[:-1]) for line in handle]
            self.assertEqual(len(records), 3)
            for record in records:
                self.assertIn("name", record)
                self.assertIn("size", record)
                self.assertIn("files", record)
                self.assertTrue((settings.parquet_dir / record["name"]).is_file())
                self.assertEqual(
                    record["size"], (settings.parquet_dir / record["name"]).stat().st_size
                )

    def test_pynad_can_classify_and_date_every_entry(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            generate_metadata(settings)
            convert_catalog(settings)
            with (settings.parquet_dir / PYNAD_INDEX_NAME).open(encoding="utf-8") as handle:
                records = [json.loads(line[:-1]) for line in handle]

            # The three buckets pynad splits the index into.
            quarterly = [r for r in records if ".trimestral." in r["name"]]
            visits = [r for r in records if ".anual.visita" in r["name"]]
            topics = [r for r in records if ".anual.trimestre" in r["name"]]
            self.assertEqual((len(quarterly), len(visits), len(topics)), (2, 1, 0))
            # Nothing may fall outside all three, or pynad would ignore it.
            self.assertEqual(len(quarterly) + len(visits) + len(topics), len(records))

            # pynad derives the panel id from the name's last components.
            quarterly.sort(key=lambda record: record["name"])
            for record, expected in zip(quarterly, ((2012, 1), (2012, 2))):
                year = int(record["name"].split(".")[-3])
                quarter = int(record["name"].split(".")[-2])
                self.assertEqual((year, quarter), expected)
                self.assertEqual(year * 10 + quarter, expected[0] * 10 + expected[1])

    def test_index_tracks_the_current_contents(self):
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            generate_metadata(settings)
            convert_catalog(settings)
            index = settings.parquet_dir / PYNAD_INDEX_NAME
            first = index.read_text(encoding="utf-8")

            # A re-run that converts nothing must still describe what is there.
            self.assertEqual(convert_catalog(settings), (0, 3, 0))
            self.assertEqual(index.read_text(encoding="utf-8"), first)

    def test_no_index_for_the_nested_layout(self):
        # The index describes a single directory; it would be meaningless
        # spread across the nested tree.
        with workspace() as tmp_path:
            settings = self._repository(tmp_path)
            settings.output_layout = "nested"
            generate_metadata(settings)
            convert_catalog(settings)
            self.assertFalse((settings.parquet_dir / PYNAD_INDEX_NAME).exists())


if __name__ == "__main__":
    unittest.main()
