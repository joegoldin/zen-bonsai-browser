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
    return validate_identity(result.stdout, application, platform)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(check_build_identity(arguments.binary.resolve(strict=True))))
