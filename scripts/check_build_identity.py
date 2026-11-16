#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Reject packages whose generated metadata no longer matches their executables."""

import argparse
import configparser
import json
import re
import subprocess
import zipfile
from pathlib import Path


class BuildIdentityError(ValueError):
    pass


def validate_identity(output, application, platform):
    match = re.search(r"(?:^|\s)(\S+) (\d{14}) (\d{14})(?:\s*,.*)?$", output.strip())
    if not match:
        raise BuildIdentityError(
            "Executable did not return version and two build IDs with --full-version"
        )
    version = application.get("App", "Version", fallback="")
    if match[1] != version:
        raise BuildIdentityError("Executable and application.ini version do not match")
    identities = (
        match[2],
        match[3],
        application.get("App", "BuildID", fallback=""),
        platform.get("Build", "BuildID", fallback=""),
    )
    if (
        any(not re.fullmatch(r"\d{14}", value) for value in identities)
        or len(set(identities)) != 1
    ):
        raise BuildIdentityError(
            "Executable and INI build IDs do not match; pin MOZ_BUILD_DATE throughout compilation and packaging"
        )
    return {"version": version, "build_id": identities[0]}


def validate_firefox_version(archive, platform):
    try:
        with zipfile.ZipFile(archive) as package:
            constants = package.read("modules/AppConstants.sys.mjs").decode("utf-8")
    except (OSError, KeyError, UnicodeError, zipfile.BadZipFile) as error:
        raise BuildIdentityError("Cannot inspect compiled Firefox version") from error
    match = re.search(r'ZEN_FIREFOX_VERSION:\s*"([^"]*)"', constants)
    version = platform.get("Build", "Milestone", fallback="")
    if not match or not version or match[1] != version:
        raise BuildIdentityError(
            "Compiled Firefox version is missing or does not match platform.ini Milestone"
        )
    return version


def check_build_identity(binary):
    application = configparser.ConfigParser(interpolation=None)
    platform = configparser.ConfigParser(interpolation=None)
    try:
        application.read(binary.parent / "application.ini")
        platform.read(binary.parent / "platform.ini")
        result = subprocess.run(
            [str(binary), "--full-version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, configparser.Error) as error:
        raise BuildIdentityError("Cannot inspect executable build identity") from error
    if result.returncode:
        raise BuildIdentityError(
            f"Executable identity command failed with status {result.returncode}"
        )
    identity = validate_identity(result.stdout, application, platform)
    identity["firefox_version"] = validate_firefox_version(
        binary.parent / "omni.ja", platform
    )
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument(
        "--firefox-version-only",
        action="store_true",
        help="Inspect omni.ja and sibling platform.ini without running the browser",
    )
    arguments = parser.parse_args()
    path = arguments.binary.resolve(strict=True)
    if arguments.firefox_version_only:
        platform = configparser.ConfigParser(interpolation=None)
        platform.read(path.parent / "platform.ini")
        print(validate_firefox_version(path, platform))
    else:
        print(json.dumps(check_build_identity(path)))
