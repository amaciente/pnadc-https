import unittest

from pnadc.layouts import parse_rows


class LayoutTests(unittest.TestCase):
    def test_parse_rows_reads_variables_categories_and_sections(self):
        rows = [
            ["header"],
            ["header"],
            ["header"],
            ["Identificação", "", "", "", "", "", "", ""],
            [1, 2, "UF", "1", "Unidade da Federação", 11, "Rondônia", "2012-atual"],
            ["", "", "", "", "", 12, "Acre", ""],
            [3, 4, "V1008", "8", "Número do domicílio", "", "", "2012-atual"],
        ]
        layout = parse_rows(rows, {"path": "synthetic.xls"})

        self.assertEqual([item.name for item in layout.variables], ["uf", "v1008"])
        self.assertEqual(layout.variables[0].start, 1)
        self.assertEqual(layout.variables[0].end, 2)
        self.assertEqual(layout.variables[0].categories, {"11": "rondônia", "12": "acre"})
        self.assertEqual(layout.variables[1].storage_type, "int16")
