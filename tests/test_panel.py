import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pnadc_https.panel import build_panel
from support import workspace


class PanelTests(unittest.TestCase):
    def test_build_panel_links_same_birth_signature(self):
        with workspace() as tmp_path:
            paths = []
            for wave in (1, 2):
                frame = pd.DataFrame(
                    {
                        "ano": [2024, 2024],
                        "trimestre": [wave, wave],
                        "upa": [100, 100],
                        "v1008": [1, 1],
                        "v1016": [wave, wave],
                        "v2003": [1, 2],
                        "v2007": [1, 2],
                        "v2008": [10, 20],
                        "v20081": [5, 6],
                        "v20082": [1980, 1985],
                        "income": [100 * wave, 200 * wave],
                    }
                )
                path = tmp_path / f"wave{wave}.parquet"
                pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)
                paths.append(path)

            output = tmp_path / "panel.parquet"
            result = build_panel(paths, output, "20241")
            panel = pq.read_table(output).to_pandas()
            self.assertEqual(result["rows"], 4)
            self.assertEqual(result["persons"], 2)
            self.assertEqual(panel.groupby("person_id")["panel_wave"].nunique().tolist(), [2, 2])

    def test_rejects_reversed_or_nonconsecutive_inputs(self):
        with workspace() as tmp_path:
            paths = []
            for quarter in (1, 2):
                frame = pd.DataFrame(
                    {
                        "ano": [2024, 2024],
                        "trimestre": [quarter, quarter],
                        "upa": [100, 100],
                        "v1008": [1, 1],
                        "v1016": [1, 2],
                        "v2003": [1, 1],
                        "v2007": [1, 1],
                        "v2008": [10, 10],
                        "v20081": [5, 5],
                        "v20082": [1980, 1980],
                    }
                )
                path = tmp_path / f"q{quarter}.parquet"
                pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)
                paths.append(path)

            with self.assertRaisesRegex(ValueError, "expected 2024Q1"):
                build_panel(list(reversed(paths)), tmp_path / "reversed.parquet", "20241")

            with self.assertRaisesRegex(ValueError, "panel_id must"):
                build_panel(paths, tmp_path / "bad-id.parquet", "panel-a")
