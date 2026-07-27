import tempfile
import unittest
from pathlib import Path

from pnadc import Repository, __version__, init_repository


class RepositoryApiTests(unittest.TestCase):
    def test_init_creates_portable_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            config = init_repository(root)
            # init_repository resolves its argument, so compare against a
            # resolved path. On Windows CI the temporary directory can be an
            # 8.3 short path (RUNNER~1) that resolves to a different string.
            self.assertEqual(config, (root / "pnadc.yml").resolve())
            self.assertTrue((root / "originals" / "trimestral").is_dir())
            self.assertTrue((root / "metadata" / "layouts").is_dir())
            repository = Repository(config)
            self.assertEqual(repository.settings.archive, root.resolve())
            self.assertEqual(repository.settings.parquet_dir, (root / "parquet").resolve())

    def test_init_never_overwrites_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_repository(root)
            with self.assertRaises(FileExistsError):
                init_repository(root)

    def test_version_is_single_sourced(self):
        # pyproject.toml reads pnadc._version.__version__, and the default
        # user agent is derived from it, so nothing can drift out of step.
        from pnadc.config import DEFAULT_USER_AGENT, NetworkSettings

        self.assertEqual(DEFAULT_USER_AGENT, f"pnadc/{__version__}")
        self.assertEqual(NetworkSettings().user_agent, f"pnadc/{__version__}")

    def test_generated_configuration_records_the_current_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = init_repository(Path(temporary))
            self.assertIn(f"user_agent: pnadc/{__version__}", config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
