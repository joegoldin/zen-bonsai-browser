#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Real NSS/signmar integration tests; SIGNMAR must name the compiled tool."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/bonsai_mar.py"
VERSION = "1.25t-bonsai.1"
PAYLOAD = b"Bonsai disposable MAR test payload\n"


def checked(*command):
    return subprocess.run(command, check=True, capture_output=True)


class BonsaiMarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signmar = Path(os.environ["SIGNMAR"])
        cls.temporary = tempfile.TemporaryDirectory(prefix="bonsai-mar-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.certificates = {}
        for name in ("own", "foreign"):
            key = cls.directory / f"{name}.key"
            pem = cls.directory / f"{name}.pem"
            certificate = cls.directory / f"{name}.der"
            checked(
                "openssl",
                "req",
                "-new",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(pem),
                "-days",
                "1",
                "-subj",
                f"/CN=Disposable {name} MAR test/",
            )
            key.chmod(0o600)
            checked(
                "openssl",
                "x509",
                "-in",
                str(pem),
                "-outform",
                "DER",
                "-out",
                str(certificate),
            )
            cls.certificates[name] = (key, certificate)
        payload = cls.directory / "payload"
        payload.write_bytes(PAYLOAD)
        cls.unsigned = cls.directory / "unsigned.mar"
        checked(
            str(cls.signmar),
            "-H",
            "release",
            "-V",
            VERSION,
            "-C",
            str(cls.directory),
            "-c",
            str(cls.unsigned),
            "payload",
        )
        cls.signed = cls.directory / "signed.mar"
        cls.invoke_sign(cls.unsigned, cls.signed)

    @classmethod
    def invoke(cls, command, archive, *extra, certificate="own", environment=None):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                command,
                str(archive),
                "--signmar",
                str(cls.signmar),
                "--certificate",
                str(cls.certificates[certificate][1]),
                "--channel",
                "release",
                "--version",
                VERSION,
                *map(str, extra),
            ],
            capture_output=True,
            env=environment,
        )

    @classmethod
    def invoke_sign(
        cls, archive, output, certificate="own", key=None, environment=None
    ):
        result = cls.invoke(
            "sign",
            archive,
            "--key",
            key or cls.certificates[certificate][0],
            "--output",
            output,
            certificate=certificate,
            environment=environment,
        )
        if result.returncode:
            raise AssertionError(result.stderr.decode())
        return result

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="case-", dir=self.directory))
        self.addCleanup(shutil.rmtree, self.work)
        self.crypto = self.work / "crypto"
        self.crypto.mkdir()
        self.environment = dict(os.environ, TMPDIR=str(self.crypto))

    def test_valid_signature_verifies_with_public_certificate_only(self):
        result = self.invoke("verify", self.signed, environment=self.environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(list(self.crypto.iterdir()), [])

    def test_unsigned_archive_is_rejected(self):
        result = self.invoke("verify", self.unsigned)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"exactly one MAR signature", result.stderr)

    def test_tampered_payload_is_rejected(self):
        data = bytearray(self.signed.read_bytes())
        data[data.index(PAYLOAD)] ^= 1
        tampered = self.work / "tampered.mar"
        tampered.write_bytes(data)
        result = self.invoke("verify", tampered, environment=self.environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.crypto.iterdir()), [])

    def test_archive_signed_by_another_root_is_rejected(self):
        foreign = self.work / "foreign.mar"
        self.invoke_sign(self.unsigned, foreign, certificate="foreign")
        self.assertNotEqual(self.invoke("verify", foreign).returncode, 0)

    def test_wrong_version_and_channel_are_rejected(self):
        for flag, value in (("--version", "1.25t-bonsai.2"), ("--channel", "twilight")):
            with self.subTest(flag=flag):
                result = self.invoke("verify", self.signed, flag, value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"channel or version", result.stderr)

    def test_truncated_archive_is_rejected(self):
        truncated = self.work / "truncated.mar"
        truncated.write_bytes(self.signed.read_bytes()[:20])
        self.assertNotEqual(self.invoke("verify", truncated).returncode, 0)

    def test_signing_preserves_input_and_cleans_private_workspace(self):
        before = self.unsigned.read_bytes()
        output = self.work / "output.mar"
        self.invoke_sign(self.unsigned, output, environment=self.environment)
        self.assertEqual(self.unsigned.read_bytes(), before)
        self.assertEqual(list(self.crypto.iterdir()), [])
        self.assertEqual(self.invoke("verify", output).returncode, 0)

    def test_existing_output_is_never_overwritten(self):
        output = self.work / "existing.mar"
        output.write_bytes(b"keep existing bytes")
        result = self.invoke(
            "sign",
            self.unsigned,
            "--key",
            self.certificates["own"][0],
            "--output",
            output,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b"keep existing bytes")

    def test_mismatched_private_key_is_rejected_and_cleaned(self):
        output = self.work / "bad-key.mar"
        result = self.invoke(
            "sign",
            self.unsigned,
            "--key",
            self.certificates["foreign"][0],
            "--output",
            output,
            environment=self.environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.crypto.iterdir()), [])
        self.assertNotIn(b"PRIVATE KEY", result.stderr)

    def test_world_readable_private_key_is_rejected(self):
        key = self.work / "insecure.key"
        shutil.copyfile(self.certificates["own"][0], key)
        key.chmod(0o644)
        result = self.invoke(
            "sign", self.unsigned, "--key", key, "--output", self.work / "bad.mar"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"group or other users", result.stderr)

    def test_private_workspace_inside_checkout_is_rejected(self):
        result = self.invoke(
            "verify", self.signed, environment=dict(os.environ, TMPDIR=str(ROOT))
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"outside the checkout", result.stderr)

    def test_already_signed_input_is_rejected(self):
        result = self.invoke(
            "sign",
            self.signed,
            "--key",
            self.certificates["own"][0],
            "--output",
            self.work / "again.mar",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"already signed", result.stderr)

    def bundle(self, output):
        spec = importlib.util.spec_from_file_location("bonsai_mar", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        generate = getattr(module, "build_bundle", None)
        self.assertTrue(
            callable(generate),
            "Signed, two-platform update bundle generation is missing",
        )
        return generate(
            self.signmar,
            self.artifacts,
            output,
            "release",
            VERSION,
            certificate=self.certificates["own"][1],
        )

    def make_artifacts(self):
        self.artifacts = self.work / "artifacts"
        self.artifacts.mkdir()
        for platform in ("linux", "windows"):
            shutil.copyfile(self.signed, self.artifacts / f"{platform}.mar")
            (self.artifacts / f"{platform}.application.ini").write_text(
                f"[App]\nName=Zen Bonsai\nVersion={VERSION}\nBuildID=20261109010101\n"
                "[AppUpdate]\nURL=https://updates.zen-bonsai.dev/updates/browser/%BUILD_TARGET%/%CHANNEL%/update.xml\n"
            )
            (self.artifacts / f"{platform}.platform.ini").write_text(
                "[Build]\nBuildID=20261109010101\nMilestone=160.0\n"
            )

    def test_bundle_contains_both_platforms_and_matching_owned_manifests(self):
        self.make_artifacts()
        output = self.work / "bundle"
        self.bundle(output)
        index = json.loads((output / "release.json").read_text())
        self.assertEqual(index["version"], VERSION)
        self.assertEqual(len(index["mar_files"]), 2)
        self.assertEqual(len(index["xml_files"]), 3)
        for name in index["xml_files"]:
            update = ET.parse(output / name).getroot().find("update")
            self.assertEqual(update.attrib["appVersion"], VERSION)
            self.assertEqual(update.attrib["platformVersion"], "160.0")
            self.assertEqual(update.attrib["buildID"], "20261109010101")
            patch = update.find("patch")
            self.assertTrue(
                patch.attrib["URL"].startswith(
                    "https://updates.zen-bonsai.dev/releases/"
                )
            )
            archive = (
                output / patch.attrib["URL"].split("updates.zen-bonsai.dev/", 1)[1]
            )
            self.assertEqual(
                patch.attrib["hashValue"],
                hashlib.sha512(archive.read_bytes()).hexdigest(),
            )
            self.assertEqual(patch.attrib["size"], str(archive.stat().st_size))

    def test_bundle_rejects_unsigned_platform_without_partial_output(self):
        self.make_artifacts()
        shutil.copyfile(self.unsigned, self.artifacts / "windows.mar")
        output = self.work / "bundle"
        with self.assertRaisesRegex(Exception, "exactly one MAR signature"):
            self.bundle(output)
        self.assertFalse(output.exists())

    def test_bundle_rejects_foreign_signature_without_partial_output(self):
        self.make_artifacts()
        foreign = self.work / "foreign.mar"
        self.invoke_sign(self.unsigned, foreign, certificate="foreign")
        shutil.copyfile(foreign, self.artifacts / "windows.mar")
        output = self.work / "bundle"
        with self.assertRaisesRegex(Exception, "exited"):
            self.bundle(output)
        self.assertFalse(output.exists())

    def test_bundle_rejects_application_version_mismatch(self):
        self.make_artifacts()
        path = self.artifacts / "windows.application.ini"
        path.write_text(path.read_text().replace(VERSION, "160.0"))
        with self.assertRaisesRegex(Exception, "version"):
            self.bundle(self.work / "bundle")

    def test_bundle_rejects_an_upstream_compiled_update_endpoint(self):
        self.make_artifacts()
        path = self.artifacts / "windows.application.ini"
        path.write_text(
            path.read_text().replace(
                "updates.zen-bonsai.dev", "updates.zen-browser.app"
            )
        )
        output = self.work / "bundle"
        with self.assertRaisesRegex(Exception, "update URL"):
            self.bundle(output)
        self.assertFalse(output.exists())

    def test_bundle_rejects_missing_compiled_update_endpoint(self):
        self.make_artifacts()
        path = self.artifacts / "linux.application.ini"
        path.write_text(path.read_text().split("[AppUpdate]")[0])
        output = self.work / "bundle"
        with self.assertRaisesRegex(Exception, "update URL"):
            self.bundle(output)
        self.assertFalse(output.exists())

    def test_bundle_rejects_build_id_mismatch(self):
        self.make_artifacts()
        path = self.artifacts / "windows.platform.ini"
        path.write_text(path.read_text().replace("20261109010101", "20261109010102"))
        with self.assertRaisesRegex(Exception, "build ID"):
            self.bundle(self.work / "bundle")

    def test_bundle_rejects_wrong_firefox_milestone(self):
        self.make_artifacts()
        path = self.artifacts / "windows.platform.ini"
        path.write_text(path.read_text().replace("160.0", "159.0"))
        with self.assertRaisesRegex(Exception, "milestone"):
            self.bundle(self.work / "bundle")

    def test_bundle_rejects_input_symlinks(self):
        self.make_artifacts()
        path = self.artifacts / "windows.mar"
        path.unlink()
        path.symlink_to(self.signed)
        with self.assertRaisesRegex(Exception, "symlink"):
            self.bundle(self.work / "bundle")

    def test_bundle_does_not_replace_existing_directory(self):
        self.make_artifacts()
        output = self.work / "bundle"
        output.mkdir()
        marker = output / "keep"
        marker.write_text("existing release")
        with self.assertRaisesRegex(Exception, "overwrite"):
            self.bundle(output)
        self.assertEqual(marker.read_text(), "existing release")

    def authenticated_bundle(self):
        self.make_artifacts()
        output = self.work / "bundle"
        self.bundle(output)
        spec = importlib.util.spec_from_file_location("bonsai_mar", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(
            callable(getattr(module, "attest_bundle", None)),
            "Offline bundle attestation is missing",
        )
        module.attest_bundle(
            self.signmar,
            output,
            self.certificates["own"][1],
            self.certificates["own"][0],
            "release",
            VERSION,
        )
        return module, output

    def test_attestation_verifies_without_a_private_key(self):
        module, output = self.authenticated_bundle()
        index = module.verify_bundle(
            output, self.certificates["own"][1], "release", VERSION
        )
        self.assertEqual(index["version"], VERSION)
        self.assertTrue((output / "release.sig").is_file())

    def test_attestation_rejects_modified_xml(self):
        module, output = self.authenticated_bundle()
        path = next(output.rglob("update.xml"))
        path.write_bytes(path.read_bytes() + b"<!-- changed -->")
        with self.assertRaisesRegex(Exception, "hash"):
            module.verify_bundle(
                output, self.certificates["own"][1], "release", VERSION
            )

    def test_attestation_rejects_modified_index(self):
        module, output = self.authenticated_bundle()
        path = output / "release.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(Exception, "exited"):
            module.verify_bundle(
                output, self.certificates["own"][1], "release", VERSION
            )

    def test_attestation_rejects_another_public_root(self):
        module, output = self.authenticated_bundle()
        with self.assertRaisesRegex(Exception, "exited"):
            module.verify_bundle(
                output, self.certificates["foreign"][1], "release", VERSION
            )

    def test_firefox_full_update_script_creates_a_real_signable_archive(self):
        script = self.signmar.parents[3] / "tools/update-packaging/make_full_update.sh"
        application = self.work / "application with spaces"
        application.mkdir()
        (application / "precomplete").write_text("")
        (application / "zen").write_bytes(PAYLOAD)
        archive = self.work / "full update.mar"
        result = subprocess.run(
            ["bash", str(script), str(archive), str(application), "zen"],
            env=dict(
                os.environ,
                MAR=str(self.signmar),
                MOZ_PRODUCT_VERSION=VERSION,
                MAR_CHANNEL_ID="release",
            ),
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue(archive.is_file())
        signed = self.work / "full-update-signed.mar"
        self.invoke_sign(archive, signed)
        self.assertEqual(self.invoke("verify", signed).returncode, 0)

    def test_public_cli_verifies_packs_and_dry_runs_without_signmar_or_key(self):
        _, output = self.authenticated_bundle()
        isolated = self.work / "public-verifier"
        scripts = isolated / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(SCRIPT, scripts / "bonsai_mar.py")
        shutil.copyfile(
            ROOT / "scripts/bonsai_publish.py", scripts / "bonsai_publish.py"
        )
        trust = isolated / "build/signing"
        trust.mkdir(parents=True)
        shutil.copyfile(self.certificates["own"][1], trust / "public_key.der")
        commands = [
            [
                sys.executable,
                str(scripts / "bonsai_mar.py"),
                "verify-bundle",
                str(output),
            ],
            [
                sys.executable,
                str(scripts / "bonsai_mar.py"),
                "pack",
                str(output),
                "--output",
                str(self.work / "public.tar"),
            ],
            [sys.executable, "-m", "scripts.bonsai_publish", str(output)],
        ]
        for command in commands:
            with self.subTest(command=command[1:3]):
                result = subprocess.run(
                    command + ["--version", VERSION, "--channel", "release"],
                    cwd=isolated,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_pack_includes_only_authenticated_public_files(self):
        module, output = self.authenticated_bundle()
        (output / "unrelated.key").write_text("disposable marker, not a private key")
        archive = self.work / "bundle.tar"
        module.pack_bundle(
            output, archive, self.certificates["own"][1], "release", VERSION
        )
        index = json.loads((output / "release.json").read_text())
        with tarfile.open(archive) as packed:
            self.assertEqual(
                set(packed.getnames()),
                {
                    "release.json",
                    "release.sig",
                    *index["mar_files"],
                    *index["xml_files"],
                },
            )
            self.assertTrue(all(member.isfile() for member in packed))
        with self.assertRaisesRegex(Exception, "overwrite"):
            module.pack_bundle(
                output, archive, self.certificates["own"][1], "release", VERSION
            )

    def test_invalid_source_configuration_fails_cleanly(self):
        self.make_artifacts()
        spec = importlib.util.spec_from_file_location("bonsai_mar", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.work
        for contents in (None, "{not valid JSON"):
            with self.subTest(contents=contents):
                if contents is not None:
                    (self.work / "surfer.json").write_text(contents)
                with self.assertRaisesRegex(
                    module.MarError, "Cannot read the source version"
                ):
                    module.build_bundle(
                        self.signmar,
                        self.artifacts,
                        self.work / "bundle",
                        "release",
                        VERSION,
                    )
                self.assertFalse((self.work / "bundle").exists())

    def test_publisher_is_read_only_by_default(self):
        from scripts import bonsai_publish as publisher

        _, output = self.authenticated_bundle()
        with patch.object(
            publisher, "run", side_effect=AssertionError("Unexpected AWS invocation")
        ):
            publisher.publish(
                output,
                "release",
                VERSION,
                None,
                None,
                certificate=self.certificates["own"][1],
            )

    def test_publisher_advertises_only_after_both_archives_are_public(self):
        from scripts import bonsai_publish as publisher

        _, output = self.authenticated_bundle()
        events = []

        def upload(*command):
            events.append(("upload", command[4]))

        def public_check(path, relative, opener):
            events.append(("public", relative))

        with patch.dict(
            os.environ,
            AWS_ACCESS_KEY_ID="disposable-test",
            AWS_SECRET_ACCESS_KEY="disposable-test",
        ):
            with (
                patch.object(publisher, "run", side_effect=upload),
                patch.object(publisher, "check_public_file", side_effect=public_check),
            ):
                publisher.publish(
                    output,
                    "release",
                    VERSION,
                    "a" * 32,
                    "test-bonsai-bucket",
                    execute=True,
                    certificate=self.certificates["own"][1],
                )
        kinds = [
            (kind, "xml" if name.endswith(".xml") else "mar") for kind, name in events
        ]
        self.assertEqual(
            kinds,
            [("upload", "mar")] * 2
            + [("public", "mar")] * 2
            + [("upload", "xml")] * 3
            + [("public", "xml")] * 3,
        )

    def test_publisher_does_not_advertise_when_public_archive_check_fails(self):
        from scripts import bonsai_publish as publisher

        _, output = self.authenticated_bundle()
        uploaded = []
        with patch.dict(
            os.environ,
            AWS_ACCESS_KEY_ID="disposable-test",
            AWS_SECRET_ACCESS_KEY="disposable-test",
        ):
            with patch.object(
                publisher,
                "run",
                side_effect=lambda *command: uploaded.append(command[4]),
            ):
                with patch.object(
                    publisher,
                    "check_public_file",
                    side_effect=publisher.MarError("HTTP 404"),
                ):
                    with self.assertRaisesRegex(publisher.MarError, "HTTP 404"):
                        publisher.publish(
                            output,
                            "release",
                            VERSION,
                            "a" * 32,
                            "test-bonsai-bucket",
                            execute=True,
                            certificate=self.certificates["own"][1],
                        )
        self.assertEqual(len(uploaded), 2)
        self.assertTrue(all(name.endswith(".mar") for name in uploaded))

    def test_public_file_check_compares_real_response_bytes(self):
        from scripts import bonsai_publish as publisher

        path = self.work / "file.mar"
        path.write_bytes(PAYLOAD)
        response = io.BytesIO(PAYLOAD)
        response.status = 200
        opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        publisher.check_public_file(path, "test.mar", opener)

    def test_public_file_check_rejects_wrong_response_bytes(self):
        from scripts import bonsai_publish as publisher

        path = self.work / "file.mar"
        path.write_bytes(PAYLOAD)
        response = io.BytesIO(PAYLOAD[:-1] + b"!")
        response.status = 200
        opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        with self.assertRaisesRegex(publisher.MarError, "hash/size"):
            publisher.check_public_file(path, "test.mar", opener)

    def test_public_downloads_do_not_follow_redirects(self):
        from scripts import bonsai_publish as publisher

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/should-not-fetch")
                self.end_headers()

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Redirect) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                opener = urllib.request.build_opener(publisher.NoRedirect())
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(f"http://127.0.0.1:{server.server_port}/", timeout=5)
                self.assertEqual(raised.exception.code, 302)
                raised.exception.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_publisher_rejects_tampering_before_upload(self):
        from scripts import bonsai_publish as publisher

        _, output = self.authenticated_bundle()
        path = next(output.rglob("update.xml"))
        path.write_bytes(b"untrusted XML")
        with patch.object(
            publisher, "run", side_effect=AssertionError("Unexpected AWS invocation")
        ):
            with self.assertRaisesRegex(publisher.MarError, "hash"):
                publisher.publish(
                    output,
                    "release",
                    VERSION,
                    "a" * 32,
                    "test-bonsai-bucket",
                    execute=True,
                    certificate=self.certificates["own"][1],
                )


if __name__ == "__main__":
    unittest.main()
