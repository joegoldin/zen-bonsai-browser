#!/usr/bin/env python3
"""Build identity must describe the executable, not just regenerated INI files."""

import configparser
import unittest

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
                + ", Copyright Mozilla\n"
            )["build_id"],
            "20261109175329",
        )


if __name__ == "__main__":
    unittest.main()
