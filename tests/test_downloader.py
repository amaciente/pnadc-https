import unittest

from pnadc.downloader import LinkParser, _child_url, _period_quarter, _period_year


class DownloaderTests(unittest.TestCase):
    def test_link_parser_and_child_url_stay_inside_root(self):
        parser = LinkParser()
        parser.feed('<a href="2025/">year</a><a href="file.zip">file</a>')
        self.assertEqual(parser.links, ["2025/", "file.zip"])

        root = "https://ftp.ibge.gov.br/base/"
        self.assertEqual(_child_url(root, root, "2025/"), "https://ftp.ibge.gov.br/base/2025/")
        self.assertIsNone(_child_url(root, root, "../secret"))
        self.assertIsNone(_child_url(root, root, "https://example.com/file"))

    def test_reference_period_ignores_revision_date(self):
        relative = "2012/PNADC_012012_20250815.zip"
        self.assertEqual(_period_year(relative), 2012)
        self.assertEqual(_period_quarter(relative), 1)

        annual = "Visita_5/Dados/PNADC_2023_visita5_20250815.zip"
        self.assertEqual(_period_year(annual), 2023)
        self.assertIsNone(_period_quarter(annual))
