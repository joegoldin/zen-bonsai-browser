#!/usr/bin/env python3
"""Check the app-local compiler runtimes needed on a clean Windows machine."""

import argparse
import json
from pathlib import Path
from zipfile import BadZipFile, Path as ZipPath, ZipFile


class RuntimePackagingError(ValueError):
    pass


def validate_runtime_files(config, directory):
    for key in (
        "MSVC_C_RUNTIME_DLL",
        "MSVC_C_RUNTIME_1_DLL",
        "MSVC_CXX_RUNTIME_DLL",
        "MSVC_CXX_RUNTIME_ATOMIC_WAIT_DLL",
    ):
        name = config.get(key)
        if not name and key == "MSVC_CXX_RUNTIME_ATOMIC_WAIT_DLL":
            continue
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise RuntimePackagingError(
                f"Missing or invalid Windows runtime configuration: {key}"
            )
        if not (directory / name).is_file():
            raise RuntimePackagingError(f"Missing Windows runtime: {directory / name}")


def check_windows_runtime(config, application=None):
    redist = config.get("WIN32_REDIST_DIR")
    if not isinstance(redist, str) or not redist:
        raise RuntimePackagingError(
            "Windows releases require WIN32_REDIST_DIR (--with-redist)"
        )
    validate_runtime_files(config, Path(redist))
    if application is not None:
        validate_runtime_files(config, application)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("application", nargs="?", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())["substs"]
        check_windows_runtime(config, args.application)
        if args.archive:
            with ZipFile(args.archive) as archive:
                validate_runtime_files(
                    config, ZipPath(archive, config["MOZ_APP_NAME"] + "/")
                )
    except (OSError, ValueError, KeyError, BadZipFile) as error:
        parser.exit(1, f"Windows runtime packaging check failed: {error}\n")
    print("Windows compiler runtime files verified")
