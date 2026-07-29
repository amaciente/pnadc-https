import json
import unittest
from pathlib import Path

import pyarrow.parquet as pq

from pnadc_https.convert import (
    _is_current,
    convert_file,
    simplified_output_stem,
)
from support import workspace


def _layout(path: Path) -> None:
    value = {
        "schema_version": 1,
        "source": {"path": "synthetic"},
        "variables": [
            {"name": "uf", "start": 1, "width": 2, "end": 2, "label": "uf", "section": "", "question": "", "period": "", "categories": {}, "storage_type": "int8"},
            {"name": "dom", "start": 3, "width": 4, "end": 6, "label": "dom", "section": "", "question": "", "period": "", "categories": {}, "storage_type": "int16"},
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")


class ConvertTests(unittest.TestCase):
    def test_legacy_provenance_is_reconverted_once(self):
        expected = {
            "source_name": "PNADC_012012.zip",
            "columns": None,
            "all_string": False,
            "output_format": "parquet",
        }
        legacy = {
            "source_name": "PNADC_012012.zip",
            "all_string": False,
        }
        # A record without a fingerprint cannot prove anything about the
        # dictionary or the options used, so it is reconverted once to
        # establish one. This is what migrates a pre-0.4 archive; the
        # conversion format version is deliberately not involved, since
        # bumping that would rebuild every output whether or not its content
        # would change.
        self.assertFalse(_is_current(legacy, expected))

    def test_simplifies_trailing_revision_date(self):
        self.assertEqual(
            simplified_output_stem("PNADC_012012_20250815"),
            "PNADC_012012",
        )
        self.assertEqual(simplified_output_stem("PNADC_012025"), "PNADC_012025")

    def test_convert_fixed_width_to_csv_and_parquet(self):
        with workspace() as tmp_path:
            source = tmp_path / "data.txt"
            source.write_text("110001\n120042\n", encoding="utf-8")
            layout = tmp_path / "layout.json"
            _layout(layout)

            csv_target = tmp_path / "data.csv"
            result = convert_file(source, layout, csv_target)
            self.assertEqual(result["rows"], 2)
            self.assertEqual(csv_target.read_text(encoding="utf-8").splitlines(), ["uf,dom", "11,0001", "12,0042"])

            parquet_target = tmp_path / "data.parquet"
            convert_file(source, layout, parquet_target)
            table = pq.read_table(parquet_target)
            self.assertEqual(table.to_pydict(), {"uf": [11, 12], "dom": [1, 42]})

    def test_convert_can_select_a_column_subset(self):
        with workspace() as tmp_path:
            source = tmp_path / "data.txt"
            source.write_text("110001\n120042\n", encoding="utf-8")
            layout = tmp_path / "layout.json"
            _layout(layout)

            csv_target = tmp_path / "data.csv"
            result = convert_file(source, layout, csv_target, columns=["DOM"])
            self.assertEqual(result["columns"], 1)
            self.assertEqual(result["variables"], ["dom"])
            self.assertEqual(csv_target.read_text(encoding="utf-8").splitlines(), ["dom", "0001", "0042"])

            parquet_target = tmp_path / "data.parquet"
            convert_file(source, layout, parquet_target, columns=["dom"])
            self.assertEqual(pq.read_table(parquet_target).to_pydict(), {"dom": [1, 42]})

            with self.assertRaises(ValueError):
                convert_file(source, layout, tmp_path / "bad.csv", columns=["nope"])
