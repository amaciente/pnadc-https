import json
import unittest
from io import BytesIO
from unittest import mock
from zipfile import ZipFile

from pnadc_https.config import Settings
from pnadc_https.downloader import (
    LinkParser,
    RemoteFile,
    _child_url,
    _period_quarter,
    _period_year,
    sync_archive,
    verify_archive,
)
from support import workspace


class AdoptionTests(unittest.TestCase):
    """An archive whose manifest is missing must not be downloaded again."""

    @staticmethod
    def _remote(size):
        return RemoteFile(
            survey="trimestral",
            path="2025/PNADC_012025.zip",
            url="https://ftp.ibge.gov.br/x/2025/PNADC_012025.zip",
            size=size,
            etag='"abc"',
            last_modified="Mon, 01 Jan 2025 00:00:00 GMT",
        )

    @staticmethod
    def _zip_bytes(payload=b"110001\n120042\n"):
        """A real ZIP, because adoption now validates archive structure."""
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("PNADC_012025.txt", payload)
        return stream.getvalue()

    def _place(self, settings, data):
        local = settings.originals / "trimestral" / "2025" / "PNADC_012025.zip"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return local

    def _sync(self, tmp_path, data, remote_size=None):
        settings = Settings(archive=tmp_path / "archive")
        self._place(settings, data)
        remote = self._remote(len(data) if remote_size is None else remote_size)
        with mock.patch(
            "pnadc_https.downloader.discover_remote_files", return_value=[remote]
        ):
            return settings, sync_archive(settings)

    def test_existing_file_of_the_right_size_is_adopted(self):
        with workspace() as tmp_path:
            data = self._zip_bytes()
            settings, result = self._sync(tmp_path, data)
            self.assertEqual((result.adopted, result.downloaded), (1, 0))

            manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
            entry = manifest["files"]["trimestral/2025/PNADC_012025.zip"]
            self.assertTrue(entry["adopted"])
            self.assertEqual(entry["local"], "originals/trimestral/2025/PNADC_012025.zip")
            self.assertIsNone(entry["sha256"])  # not read, so not claimed

    def test_adopted_file_is_unchanged_on_the_next_run(self):
        with workspace() as tmp_path:
            data = self._zip_bytes()
            settings, first = self._sync(tmp_path, data)
            self.assertEqual(first.adopted, 1)
            with mock.patch(
                "pnadc_https.downloader.discover_remote_files",
                return_value=[self._remote(len(data))],
            ):
                second = sync_archive(settings)
            self.assertEqual((second.unchanged, second.adopted, second.downloaded), (1, 0, 0))

    def test_file_of_the_wrong_size_is_not_adopted(self):
        # A truncated or superseded local copy must still be fetched.
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            self._place(settings, self._zip_bytes())
            with mock.patch(
                "pnadc_https.downloader.discover_remote_files",
                return_value=[self._remote(999_999)],
            ):
                result = sync_archive(settings, dry_run=True)
            self.assertEqual(result.adopted, 0)

    def test_corrupt_archive_of_the_right_size_is_not_adopted(self):
        # Size alone cannot distinguish a valid archive from a damaged one, so
        # the central directory is read before the file is trusted.
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            corrupt = b"not a zip at all" * 8
            self._place(settings, corrupt)
            with mock.patch(
                "pnadc_https.downloader.discover_remote_files",
                return_value=[self._remote(len(corrupt))],
            ):
                result = sync_archive(settings, dry_run=True)
            self.assertEqual(result.adopted, 0)

    def test_verify_reports_adopted_files_as_unverifiable(self):
        with workspace() as tmp_path:
            data = self._zip_bytes()
            settings, _ = self._sync(tmp_path, data)

            shallow = verify_archive(settings)
            self.assertEqual((shallow.checked, shallow.ok, shallow.failed), (1, 0, []))
            self.assertEqual(shallow.unverifiable, 1)  # adopted, so no hash

            # A deep check can still validate the archive's own CRCs.
            deep = verify_archive(settings, deep=True)
            self.assertEqual((deep.ok, deep.failed, deep.unverifiable), (1, [], 0))

            # Corrupt the stored payload while keeping the size identical, so
            # only a CRC check can detect it. The byte is located rather than
            # guessed, since a blind flip may land in ZIP metadata instead.
            local = settings.originals / "trimestral" / "2025" / "PNADC_012025.zip"
            blob = bytearray(local.read_bytes())
            offset = blob.find(b"110001")
            self.assertNotEqual(offset, -1, "payload not stored verbatim")
            blob[offset] ^= 0xFF
            local.write_bytes(bytes(blob))

            failures = verify_archive(settings, deep=True).failed
            self.assertTrue(failures, "a CRC failure should have been reported")
            self.assertIn("CRC", failures[0])

    def test_verify_rejects_manifest_paths_outside_repository(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            settings.state_dir.mkdir(parents=True)
            outside = tmp_path / "outside.zip"
            outside.write_bytes(self._zip_bytes())
            settings.manifest_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "trimestral/outside.zip": {
                                "local": "../outside.zip",
                                "size": outside.stat().st_size,
                                "sha256": None,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = verify_archive(settings, deep=True)
            self.assertEqual(result.ok, 0)
            self.assertEqual(len(result.failed), 1)
            self.assertIn("escapes", result.failed[0])

    def test_successful_downloads_are_recorded_when_another_fails(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            good = RemoteFile(
                "trimestral", "2025/good.zip", "https://example/good.zip",
                4, '"good"', "today",
            )
            bad = RemoteFile(
                "trimestral", "2025/bad.zip", "https://example/bad.zip",
                4, '"bad"', "today",
            )

            def download(remote, target, _chunk_size):
                if remote is bad:
                    raise OSError("simulated network failure")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"good")
                return 4, "recorded-hash"

            client = mock.Mock()
            client.download.side_effect = download
            with mock.patch(
                "pnadc_https.downloader.discover_remote_files",
                return_value=[bad, good],
            ), mock.patch(
                "pnadc_https.downloader.HttpClient",
                return_value=client,
            ):
                with self.assertRaisesRegex(RuntimeError, "1 download"):
                    sync_archive(settings)

            manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
            self.assertIn(good.key, manifest["files"])
            self.assertEqual(manifest["files"][good.key]["sha256"], "recorded-hash")
            self.assertNotIn(bad.key, manifest["files"])


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

    def test_generator_surveys_still_define_prune_scope(self):
        with workspace() as tmp_path:
            settings = Settings(archive=tmp_path / "archive")
            local = settings.originals / "trimestral" / "old.zip"
            local.parent.mkdir(parents=True)
            local.write_bytes(b"old")
            settings.state_dir.mkdir(parents=True)
            settings.manifest_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "trimestral/old.zip": {
                                "local": "originals/trimestral/old.zip"
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            surveys = (name for name in ("trimestral",))
            with mock.patch(
                "pnadc_https.downloader.discover_remote_files", return_value=[]
            ):
                result = sync_archive(
                    settings, surveys=surveys, prune=True, dry_run=True
                )
            self.assertEqual(result.pruned, 1)
