#!/usr/bin/env python3
"""Build identity must describe the executable, not just regenerated INI files."""

import configparser
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts import check_build_identity as checker
from scripts.check_build_identity import BuildIdentityError, validate_identity


class BuildIdentityTests(unittest.TestCase):
    def setUp(self):
        self.application = configparser.ConfigParser(interpolation=None)
        self.application.read_dict(
            {"App": {"Version": "1.25t-bonsai.1", "BuildID": "20261109175329"}}
        )
        self.platform = configparser.ConfigParser(interpolation=None)
        self.platform.read_dict({"Build": {"BuildID": "20261109175329"}})
        self.output = "Mozilla Zen 1.25t-bonsai.1 20261109175329 20261109175329\n"

    def validate(self, output=None):
        return validate_identity(output or self.output, self.application, self.platform)

    def test_matching_executable_and_metadata(self):
        self.assertEqual(self.validate()["build_id"], "20261109175329")

    def test_actual_shipping_regeneration_regression(self):
        with self.assertRaisesRegex(BuildIdentityError, "build IDs"):
            self.validate("Mozilla Zen 1.25t-bonsai.1 20261109164920 20261109164920")

    def test_runtime_app_and_platform_must_agree(self):
        with self.assertRaisesRegex(BuildIdentityError, "build IDs"):
            self.validate("Mozilla Zen 1.25t-bonsai.1 20261109164920 20261109175329")

    def test_sidecars_must_agree(self):
        self.platform["Build"]["BuildID"] = "20261109164920"
        with self.assertRaisesRegex(BuildIdentityError, "build IDs"):
            self.validate()

    def test_version_must_match(self):
        with self.assertRaisesRegex(BuildIdentityError, "version"):
            self.validate(self.output.replace("1.25t-bonsai.1", "1.24.1b-bonsai.1"))

    def test_missing_build_id_is_rejected(self):
        del self.application["App"]["BuildID"]
        with self.assertRaises(BuildIdentityError):
            self.validate()

    def test_missing_runtime_build_ids_are_rejected(self):
        with self.assertRaisesRegex(BuildIdentityError, "full-version"):
            self.validate("Mozilla Zen 1.25t-bonsai.1")

    def test_copyright_and_spaced_brand_are_supported(self):
        self.assertEqual(
            self.validate(
                self.output.replace("Mozilla Zen", "Mozilla Zen Bonsai").strip()
                + " , Copyright Mozilla\n"
            )["build_id"],
            "20261109175329",
        )


class FirefoxVersionTests(unittest.TestCase):
    def validate(self, version):
        platform = configparser.ConfigParser(interpolation=None)
        platform.read_dict({"Build": {"Milestone": "160.0"}})
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "omni.ja"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr(
                    "modules/AppConstants.sys.mjs",
                    f'export var AppConstants = {{ZEN_FIREFOX_VERSION: "{version}"}};',
                )
            return checker.validate_firefox_version(archive, platform)

    def test_compiled_firefox_version_matches_engine(self):
        self.assertEqual(self.validate("160.0"), "160.0")

    def test_missing_build_variable_is_rejected(self):
        with self.assertRaisesRegex(BuildIdentityError, "Firefox version"):
            self.validate("")

    def test_display_version_is_not_the_firefox_version(self):
        with self.assertRaisesRegex(BuildIdentityError, "Firefox version"):
            self.validate("1.25t-bonsai.3")

    def test_stale_engine_version_is_rejected(self):
        with self.assertRaisesRegex(BuildIdentityError, "Firefox version"):
            self.validate("159.0")


if __name__ == "__main__":
    unittest.main()
