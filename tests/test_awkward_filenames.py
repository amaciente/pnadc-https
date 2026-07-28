"""Filenames that are legal on IBGE's server but hostile to naive clients.

IBGE publishes at least one file whose name contains a space:

    06_Definicao_variaveis_derivadas_parte05_ Rendimento_de_outras_fontes.pdf

A crawler must keep two different strings for such a file: the URL, where the
space stays percent-encoded, and the local path, where it must be a real
space. Collapsing them into one — decoding once and using the result for both
— either requests a URL containing a raw space or writes a file literally
named ``%20``. Portuguese names with accents (``Ação``) have the same shape,
encoded as multi-byte UTF-8 rather than ``%20``.
"""

import tempfile
import unittest
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from pnadc_https.downloader import LinkParser, _child_url

ROOT = "https://ftp.ibge.gov.br/base/"

# The real file, as IBGE serves it.
IBGE_SPACED = "06_Definicao_variaveis_derivadas_parte05_%20Rendimento_de_outras_fontes.pdf"


def _local_relative(child: str) -> str:
    """Reproduce how crawl_files derives a repository-relative path."""
    relative = unquote(urlsplit(child).path[len(urlsplit(ROOT).path) :])
    return str(PurePosixPath(relative))


class AwkwardFilenameTests(unittest.TestCase):
    def test_percent_encoding_is_kept_in_the_url(self):
        # The request must not contain a raw space, which is not legal in a
        # URL and which some servers reject outright.
        child = _child_url(ROOT, ROOT, IBGE_SPACED)
        self.assertIn("%20", child)
        self.assertNotIn(" ", child)

    def test_local_path_uses_a_real_space(self):
        child = _child_url(ROOT, ROOT, IBGE_SPACED)
        relative = _local_relative(child)
        self.assertEqual(
            relative,
            "06_Definicao_variaveis_derivadas_parte05_ Rendimento_de_outras_fontes.pdf",
        )
        # A file named "%20" would be the classic wrong outcome.
        self.assertNotIn("%20", relative)

    def test_accented_names_decode_to_utf8(self):
        child = _child_url(ROOT, ROOT, "Deflatores_A%C3%A7%C3%A3o.xls")
        self.assertIn("%C3%A7", child)  # still encoded in the request
        self.assertEqual(_local_relative(child), "Deflatores_Ação.xls")

    def test_spaces_survive_a_directory_listing(self):
        parser = LinkParser()
        parser.feed(f'<a href="{IBGE_SPACED}">06_Definicao ... .pdf</a>')
        self.assertEqual(parser.links, [IBGE_SPACED])
        child = _child_url(ROOT, ROOT, parser.links[0])
        self.assertIn("%20", child)
        self.assertIn(" ", _local_relative(child))

    def test_such_files_can_be_written_and_read_back(self):
        # Deriving the path correctly is only useful if it is also usable.
        names = [
            "06_Definicao_variaveis_derivadas_parte05_ Rendimento_de_outras_fontes.pdf",
            "Deflatores_Ação.xls",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for name in names:
                path = Path(temporary) / name
                path.write_bytes(b"payload")
                self.assertEqual(path.read_bytes(), b"payload")
                self.assertIn(name, [p.name for p in Path(temporary).iterdir()])

    def test_a_spaced_name_does_not_escape_the_archive(self):
        # Path traversal defences must not be confused by encoded characters.
        self.assertIsNone(_child_url(ROOT, ROOT, "..%2F..%2Fsecret.txt"))
        self.assertIsNone(_child_url(ROOT, ROOT, "../secret.txt"))


if __name__ == "__main__":
    unittest.main()
