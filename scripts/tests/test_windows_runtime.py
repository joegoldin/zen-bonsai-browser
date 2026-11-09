#!/usr/bin/env python3
import tempfile
from pathlib import Path
import unittest
from zipfile import Path as ZipPath, ZipFile

from scripts.check_windows_runtime import (
    RuntimePackagingError,
    check_windows_runtime,
    validate_runtime_files,
)


class WindowsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = {
            "MSVC_C_RUNTIME_DLL": "vcruntime140.dll",
            "MSVC_C_RUNTIME_1_DLL": "vcruntime140_1.dll",
            "MSVC_CXX_RUNTIME_DLL": "msvcp140.dll",
            "MSVC_CXX_RUNTIME_ATOMIC_WAIT_DLL": "msvcp140_atomic_wait.dll",
        }
        for name in self.config.values():
            (self.root / name).write_bytes(b"runtime fixture")

    def test_unconfigured_redistribution_is_rejected(self):
        with self.assertRaisesRegex(RuntimePackagingError, "WIN32_REDIST_DIR"):
            check_windows_runtime(self.config)

    def test_source_and_staging_runtimes_are_verified(self):
        self.config["WIN32_REDIST_DIR"] = str(self.root)
        check_windows_runtime(self.config, self.root)

    def test_complete_archive_runtimes_are_accepted(self):
        archive = self.root / "complete.zip"
        with ZipFile(archive, "w") as output:
            for name in self.config.values():
                output.writestr("zen/" + name, b"runtime fixture")
        with ZipFile(archive) as package:
            validate_runtime_files(self.config, ZipPath(package, "zen/"))

    def test_archive_without_runtimes_is_rejected(self):
        archive = self.root / "missing.zip"
        with ZipFile(archive, "w") as output:
            output.writestr("zen/zen.exe", b"application fixture")
        with ZipFile(archive) as package:
            with self.assertRaisesRegex(
                RuntimePackagingError, "Missing Windows runtime"
            ):
                validate_runtime_files(self.config, ZipPath(package, "zen/"))

    def test_complete_compiler_runtimes_are_accepted(self):
        validate_runtime_files(self.config, self.root)

    def test_actual_package_without_any_runtime_is_rejected(self):
        for path in self.root.iterdir():
            path.unlink()
        with self.assertRaisesRegex(RuntimePackagingError, "Missing Windows runtime"):
            validate_runtime_files(self.config, self.root)

    def test_missing_one_runtime_is_rejected(self):
        (self.root / "vcruntime140_1.dll").unlink()
        with self.assertRaisesRegex(RuntimePackagingError, "vcruntime140_1"):
            validate_runtime_files(self.config, self.root)

    def test_missing_atomic_wait_runtime_is_rejected_when_required(self):
        (self.root / "msvcp140_atomic_wait.dll").unlink()
        with self.assertRaisesRegex(RuntimePackagingError, "atomic_wait"):
            validate_runtime_files(self.config, self.root)

    def test_atomic_wait_is_optional_when_compiler_does_not_require_it(self):
        self.config["MSVC_CXX_RUNTIME_ATOMIC_WAIT_DLL"] = None
        validate_runtime_files(self.config, self.root)

    def test_missing_compiler_runtime_configuration_is_rejected(self):
        del self.config["MSVC_CXX_RUNTIME_DLL"]
        with self.assertRaisesRegex(RuntimePackagingError, "configuration"):
            validate_runtime_files(self.config, self.root)


if __name__ == "__main__":
    unittest.main()
