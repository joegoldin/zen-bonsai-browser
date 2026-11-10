# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
from contextlib import redirect_stderr
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "download_firefox_source.py"


class FirefoxSourceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            SCRIPT.is_file(), "Candidate source needs checksum-verified cache staging"
        )
        spec = importlib.util.spec_from_file_location("firefox_source", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)
        self.archive = b"source archive fixture"
        self.opener = Mock(return_value=io.BytesIO(self.archive))
        self.config = {
            "version": {
                "version": "160.0",
                "source": {
                    "url": "https://archive.mozilla.org/pub/firefox/candidates/160.0-candidates/build1/source/firefox-160.0.source.tar.xz",
                    "hash": "sha512-"
                    + base64.b64encode(hashlib.sha512(self.archive).digest()).decode(),
                },
            }
        }

    def stage(self):
        return self.module.stage_source(self.config, self.cache, opener=self.opener)

    def test_candidate_is_verified_and_staged_for_surfer(self):
        archive = self.stage()
        self.assertEqual(archive, self.cache / "firefox-160.0.source.tar.xz")
        self.assertEqual(archive.read_bytes(), self.archive)
        self.opener.assert_called_once()

    def test_matching_cached_archive_never_downloads_again(self):
        self.stage()
        self.stage()
        self.opener.assert_called_once()

    def test_wrong_download_digest_is_rejected_without_staging(self):
        self.opener.return_value = io.BytesIO(b"corrupt archive")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.stage()
        self.assertFalse((self.cache / "firefox-160.0.source.tar.xz").exists())

    def test_corrupt_cache_is_not_silently_reused_or_overwritten(self):
        path = self.cache / "firefox-160.0.source.tar.xz"
        path.write_bytes(b"corrupt cache")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.stage()
        self.assertEqual(path.read_bytes(), b"corrupt cache")
        self.opener.assert_not_called()

    def test_wrong_version_url_is_rejected(self):
        self.config["version"]["version"] = "161.0"
        with self.assertRaises(ValueError):
            self.stage()
        self.opener.assert_not_called()

    def test_untrusted_or_insecure_source_is_rejected(self):
        self.config["version"]["source"]["url"] = (
            "http://untrusted.invalid/source/firefox-160.0.source.tar.xz"
        )
        with self.assertRaises(ValueError):
            self.stage()
        self.opener.assert_not_called()

    def test_invalid_digest_is_rejected(self):
        self.config["version"]["source"]["hash"] = "sha512-bad"
        with self.assertRaises(ValueError):
            self.stage()
        self.opener.assert_not_called()

    def test_unpinned_release_keeps_surfer_download_behavior(self):
        del self.config["version"]["source"]
        self.assertIsNone(self.stage())
        self.opener.assert_not_called()

    def test_main_reports_missing_config_without_starting_surfer(self):
        with (
            patch.object(self.module, "ROOT", self.cache),
            patch.object(self.module.subprocess, "run") as run,
            redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(self.module.main(), 1)
        self.assertIn("Firefox source setup failed", error.getvalue())
        run.assert_not_called()

    def test_main_reports_invalid_json_without_starting_surfer(self):
        (self.cache / "surfer.json").write_text("{invalid json")
        with (
            patch.object(self.module, "ROOT", self.cache),
            patch.object(self.module.subprocess, "run") as run,
            redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(self.module.main(), 1)
        self.assertIn("Firefox source setup failed", error.getvalue())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
