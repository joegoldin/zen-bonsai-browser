#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Sign offline and verify MARs without putting private material in the checkout."""

import argparse
import contextlib
import configparser
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERTIFICATE = ROOT / "build/signing/public_key.der"
NICKNAME = "bonsai-mar"
BUNDLE_SCHEMA = "zen-bonsai-update-bundle-v1"
TARGETS = {
    "linux": ("Linux_x86_64-gcc3",),
    "windows": ("WINNT_x86_64-msvc", "WINNT_x86_64-msvc-x64"),
}


class MarError(Exception):
    pass


def run(*command):
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except OSError as error:
        raise MarError(
            f"Cannot execute {Path(command[0]).name}: {error.strerror}"
        ) from error
    if result.returncode:
        # OpenSSL/NSS diagnostics can include sensitive input. Report only the
        # tool/status and NSS error identifiers, never captured key material.
        identifiers = re.findall(rb"SEC_ERROR_[A-Z_]+", result.stderr)
        detail = ": " + identifiers[0].decode() if identifiers else ""
        raise MarError(f"{Path(command[0]).name} exited {result.returncode}{detail}")
    return result.stdout


@contextlib.contextmanager
def private_workspace():
    base = Path(tempfile.gettempdir()).resolve()
    if base.is_relative_to(ROOT):
        raise MarError("Private NSS databases must be created outside the checkout")
    with tempfile.TemporaryDirectory(prefix="bonsai-mar-", dir=base) as name:
        yield Path(name)


def make_database(workspace, certificate):
    database = workspace / "nss"
    database.mkdir(mode=0o700)
    location = f"sql:{database}"
    run("certutil", "-N", "-d", location, "--empty-password")
    run(
        "certutil",
        "-A",
        "-d",
        location,
        "-n",
        NICKNAME,
        "-t",
        ",,",
        "-i",
        str(certificate),
    )
    return location


def information(signmar, archive):
    output = run(str(signmar), "-T", str(archive)).decode("utf-8", errors="replace")
    signatures = re.findall(r"Signature block found with (\d+) signature", output)
    channel = re.search(r"MAR channel (?:name|ID):\s*(\S+)", output, re.IGNORECASE)
    version = re.search(r"Product version:\s*(\S+)", output, re.IGNORECASE)
    if not channel or not version:
        raise MarError("MAR lacks readable channel/product metadata")
    return signatures, channel.group(1), version.group(1)


def verify(signmar, archive, certificate, channel, version):
    signatures, actual_channel, actual_version = information(signmar, archive)
    if signatures != ["1"]:
        raise MarError("Expected exactly one MAR signature")
    if actual_channel != channel or actual_version != version:
        raise MarError("MAR channel or version does not match the release")
    # This database contains only the public trust root, never a private key.
    with private_workspace() as workspace:
        database = make_database(workspace, certificate)
        run(str(signmar), "-d", database, "-n", NICKNAME, "-v", str(archive))


def private_key(key):
    key = key.resolve(strict=True)
    if key.is_relative_to(ROOT):
        raise MarError("The signing key must be stored outside the checkout")
    if key.stat().st_mode & 0o077:
        raise MarError("The signing key must not be readable by group or other users")
    return key


def sign(signmar, archive, output, certificate, key, channel, version):
    key = private_key(key)
    if output.exists():
        raise MarError("Refusing to overwrite an existing output archive")
    signatures, actual_channel, actual_version = information(signmar, archive)
    if signatures and signatures != ["0"]:
        raise MarError("Input MAR is already signed")
    if actual_channel != channel or actual_version != version:
        raise MarError("MAR channel or version does not match the release")

    with private_workspace() as workspace:
        database = make_database(workspace, certificate)
        pem = workspace / "certificate.pem"
        # The repository trust root is a DER certificate, not a PEM key bundle.
        run(
            "openssl",
            "x509",
            "-inform",
            "DER",
            "-in",
            str(certificate),
            "-out",
            str(pem),
        )
        password = workspace / "password"
        password.write_text(os.urandom(32).hex() + "\n")
        password.chmod(0o600)
        bundle = workspace / "key.p12"
        run(
            "openssl",
            "pkcs12",
            "-export",
            "-inkey",
            str(key),
            "-in",
            str(pem),
            "-name",
            NICKNAME,
            "-passout",
            f"file:{password}",
            "-out",
            str(bundle),
        )
        bundle.chmod(0o600)
        empty_password = workspace / "empty-password"
        empty_password.write_bytes(b"")
        empty_password.chmod(0o600)
        run(
            "pk12util",
            "-i",
            str(bundle),
            "-d",
            database,
            "-w",
            str(password),
            "-k",
            str(empty_password),
        )
        signed = workspace / "signed.mar"
        run(
            str(signmar),
            "-d",
            database,
            "-n",
            NICKNAME,
            "-s",
            str(archive),
            str(signed),
        )
        verify(signmar, signed, certificate, channel, version)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Stage on the destination filesystem. link() publishes without ever
        # replacing an existing file, even if another process created it meanwhile.
        descriptor, staged_name = tempfile.mkstemp(
            prefix=".bonsai-mar-", dir=output.parent
        )
        os.close(descriptor)
        staged = Path(staged_name)
        try:
            shutil.copyfile(signed, staged)
            staged.chmod(0o644)
            os.link(staged, output)
        finally:
            staged.unlink(missing_ok=True)


def validate_update_endpoint(application):
    expected = "https://updates.zen-bonsai.dev/updates/browser/%BUILD_TARGET%/%CHANNEL%/update.xml"
    if application.get("AppUpdate", "URL", fallback="") != expected:
        raise MarError(
            "Compiled application update URL must use the fork-owned host and path"
        )


def build_bundle(signmar, artifacts, output, channel, version, certificate=CERTIFICATE):
    if not re.fullmatch(r"[0-9][0-9A-Za-z.]*-bonsai\.[0-9]+", version):
        raise MarError("Expected a Bonsai version")
    if channel not in ("release", "twilight"):
        raise MarError("Unknown update channel")
    if output.exists():
        raise MarError("Refusing to overwrite an existing update bundle")
    try:
        configuration = json.loads((ROOT / "surfer.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise MarError("Cannot read the source version from surfer.json") from error
    source_version = configuration["version"]["version"]
    artifacts = artifacts.resolve(strict=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".bonsai-updates-", dir=output.parent
    ) as name:
        staged = Path(name)
        index = {
            "schema": BUNDLE_SCHEMA,
            "version": version,
            "channel": channel,
            "mar_files": [],
            "xml_files": [],
        }
        for platform, aliases in TARGETS.items():
            inputs = {}
            for suffix in ("mar", "application.ini", "platform.ini"):
                path = artifacts / f"{platform}.{suffix}"
                if path.is_symlink() or not path.resolve(strict=True).is_relative_to(
                    artifacts
                ):
                    raise MarError(
                        "Update inputs must not be symlinks outside the artifact directory"
                    )
                inputs[suffix] = path
            application = configparser.ConfigParser(interpolation=None)
            application.read(inputs["application.ini"])
            validate_update_endpoint(application)
            build = configparser.ConfigParser(interpolation=None)
            build.read(inputs["platform.ini"])
            if application.get("App", "Version", fallback="") != version:
                raise MarError(
                    f"{platform} application version does not match the release"
                )
            build_id = build.get("Build", "BuildID", fallback="")
            if (
                not re.fullmatch(r"[0-9]{14}", build_id)
                or application.get("App", "BuildID", fallback="") != build_id
            ):
                raise MarError(f"{platform} build ID is missing or inconsistent")
            milestone = build.get("Build", "Milestone", fallback="")
            if milestone != source_version:
                raise MarError(
                    f"{platform} Firefox milestone does not match the source pin"
                )
            # Verify a snapshot, then hash and publish those same bytes, not a
            # source file that another process could change after verification.
            snapshot = staged / f"{platform}.mar"
            shutil.copyfile(inputs["mar"], snapshot)
            verify(signmar, snapshot, certificate, channel, version)
            with snapshot.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha512").hexdigest()
            relative_mar = (
                Path("releases") / version / f"{platform}-x86_64" / f"{digest}.mar"
            )
            destination = staged / relative_mar
            destination.parent.mkdir(parents=True, exist_ok=True)
            snapshot.rename(destination)
            index["mar_files"].append(relative_mar.as_posix())
            for alias in aliases:
                xml = ET.Element("updates")
                update = ET.SubElement(
                    xml,
                    "update",
                    {
                        "type": "minor",
                        "displayVersion": version,
                        "appVersion": version,
                        "platformVersion": milestone,
                        "buildID": build_id,
                    },
                )
                ET.SubElement(
                    update,
                    "patch",
                    {
                        "type": "complete",
                        "URL": f"https://updates.zen-bonsai.dev/{relative_mar.as_posix()}",
                        "hashFunction": "sha512",
                        "hashValue": digest,
                        "size": str(destination.stat().st_size),
                    },
                )
                relative_xml = Path("updates/browser") / alias / channel / "update.xml"
                xml_path = staged / relative_xml
                xml_path.parent.mkdir(parents=True, exist_ok=True)
                ET.indent(xml)
                ET.ElementTree(xml).write(
                    xml_path, encoding="utf-8", xml_declaration=True
                )
                index["xml_files"].append(relative_xml.as_posix())
        index["sha512"] = {}
        for relative in index["mar_files"] + index["xml_files"]:
            with (staged / relative).open("rb") as stream:
                index["sha512"][relative] = hashlib.file_digest(
                    stream, "sha512"
                ).hexdigest()
        (staged / "release.json").write_text(json.dumps(index, indent=2) + "\n")
        # No platform's metadata becomes available until both signatures and
        # both sets of build metadata have passed their checks.
        staged.rename(output)


def bundle_contents(bundle, channel, version):
    try:
        index = json.loads((bundle / "release.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise MarError("Cannot read the update bundle index") from error
    if not isinstance(index, dict) or index.get("schema") != BUNDLE_SCHEMA:
        raise MarError("Unknown update bundle schema")
    if index.get("version") != version or index.get("channel") != channel:
        raise MarError("Update bundle version/channel mismatch")
    archives = index.get("mar_files")
    manifests = index.get("xml_files")
    hashes = index.get("sha512")
    if (
        not isinstance(archives, list)
        or not isinstance(manifests, list)
        or not isinstance(hashes, dict)
    ):
        raise MarError("Invalid update bundle file lists")
    expected_xml = {
        f"updates/browser/{alias}/{channel}/update.xml"
        for aliases in TARGETS.values()
        for alias in aliases
    }
    if (
        len(archives) != 2
        or len(manifests) != 3
        or not all(isinstance(path, str) for path in archives + manifests)
    ):
        raise MarError(
            "The update bundle must contain both platforms and all three manifests"
        )
    if set(manifests) != expected_xml or set(hashes) != set(archives + manifests):
        raise MarError("Unexpected update bundle paths")
    for platform in TARGETS:
        pattern = (
            rf"releases/{re.escape(version)}/{platform}-x86_64/[0-9a-f]{{128}}\.mar"
        )
        if sum(bool(re.fullmatch(pattern, path)) for path in archives) != 1:
            raise MarError("Unexpected update archive path")
    for relative in archives + manifests:
        path = bundle / relative
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(
            bundle.resolve()
        ):
            raise MarError("Update bundle contains an unsafe symlink")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha512").hexdigest()
        if actual != hashes[relative]:
            raise MarError("Update bundle file hash mismatch")
        if relative in archives and path.stem != actual:
            raise MarError("Immutable MAR filename does not match its hash")
    for platform, aliases in TARGETS.items():
        archive = next(path for path in archives if f"/{platform}-x86_64/" in path)
        for alias in aliases:
            try:
                root = ET.parse(
                    bundle / f"updates/browser/{alias}/{channel}/update.xml"
                ).getroot()
            except (ET.ParseError, OSError) as error:
                raise MarError("Cannot parse update XML") from error
            update = root.find("update")
            patch = update.find("patch") if update is not None else None
            if (
                root.tag != "updates"
                or len(root) != 1
                or update is None
                or patch is None
                or len(update) != 1
            ):
                raise MarError("Unexpected update XML structure")
            if (
                update.get("appVersion") != version
                or update.get("displayVersion") != version
                or not re.fullmatch(r"[0-9]{14}", update.get("buildID", ""))
            ):
                raise MarError("Unexpected update XML version/build ID")
            if patch.attrib != {
                "type": "complete",
                "URL": f"https://updates.zen-bonsai.dev/{archive}",
                "hashFunction": "sha512",
                "hashValue": hashes[archive],
                "size": str((bundle / archive).stat().st_size),
            }:
                raise MarError("Update XML does not describe the signed archive")
    return index


def verify_attestation(bundle, certificate, signature):
    with private_workspace() as workspace:
        public_key = workspace / "public.pem"
        public_key.write_bytes(
            run(
                "openssl",
                "x509",
                "-inform",
                "DER",
                "-in",
                str(certificate),
                "-pubkey",
                "-noout",
            )
        )
        run(
            "openssl",
            "dgst",
            "-sha384",
            "-verify",
            str(public_key),
            "-signature",
            str(signature),
            str(bundle / "release.json"),
        )


def verify_bundle(bundle, certificate, channel, version):
    # Authenticate the index before interpreting any file paths from it.
    verify_attestation(bundle, certificate, bundle / "release.sig")
    return bundle_contents(bundle, channel, version)


def attest_bundle(signmar, bundle, certificate, key, channel, version):
    key = private_key(key)
    if (bundle / "release.sig").exists():
        raise MarError("Refusing to overwrite a bundle attestation")
    index = bundle_contents(bundle, channel, version)
    for relative in index["mar_files"]:
        verify(signmar, bundle / relative, certificate, channel, version)
    with private_workspace() as workspace:
        signature = workspace / "release.sig"
        run(
            "openssl",
            "dgst",
            "-sha384",
            "-sign",
            str(key),
            "-out",
            str(signature),
            str(bundle / "release.json"),
        )
        # A mismatched private key must not produce a publishable attestation.
        verify_attestation(bundle, certificate, signature)
        descriptor, name = tempfile.mkstemp(prefix=".bonsai-attestation-", dir=bundle)
        staged = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(signature.read_bytes())
            os.link(staged, bundle / "release.sig")
        finally:
            staged.unlink(missing_ok=True)


def pack_bundle(bundle, output, certificate, channel, version):
    index = verify_bundle(bundle, certificate, channel, version)
    # Include only authenticated public files, never unrelated files someone
    # may have placed in the staging directory (including private keys).
    try:
        with tarfile.open(output, "x") as archive:
            for relative in (
                ["release.json", "release.sig"]
                + index["mar_files"]
                + index["xml_files"]
            ):
                archive.add(bundle / relative, arcname=relative, recursive=False)
    except FileExistsError as error:
        raise MarError("Refusing to overwrite an existing bundle archive") from error
    except (OSError, tarfile.TarError):
        output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("sign", "verify", "bundle", "attest", "verify-bundle", "pack"),
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--signmar", type=Path)
    parser.add_argument("--certificate", type=Path, default=CERTIFICATE)
    parser.add_argument("--channel", choices=("release", "twilight"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9][0-9A-Za-z.]*-bonsai\.[0-9]+", args.version):
        parser.error("Expected a Bonsai version such as 1.25t-bonsai.1")
    if args.command not in ("verify-bundle", "pack") and not args.signmar:
        parser.error("This operation requires --signmar")
    if args.command == "attest" and (not args.key or args.output):
        parser.error("Attestation requires --key and no output path")
    if args.command == "verify-bundle" and (
        args.key or args.output or args.certificate != CERTIFICATE
    ):
        parser.error("Bundle verification uses only the repository public root")
    if args.command == "sign" and (not args.key or not args.output):
        parser.error("Signing requires --key and --output")
    if args.command == "bundle" and (
        not args.output or args.key or args.certificate != CERTIFICATE
    ):
        parser.error(
            "Bundling requires --output and the repository public root, never a key"
        )
    if args.command == "pack" and (
        not args.output or args.key or args.certificate != CERTIFICATE
    ):
        parser.error("Packing requires --output and only the repository public root")
    previous_mask = os.umask(0o077)
    try:
        if args.command == "pack":
            pack_bundle(
                args.archive, args.output, CERTIFICATE, args.channel, args.version
            )
        elif args.command == "verify-bundle":
            verify_bundle(args.archive, CERTIFICATE, args.channel, args.version)
        elif args.command == "attest":
            attest_bundle(
                args.signmar,
                args.archive,
                args.certificate,
                args.key,
                args.channel,
                args.version,
            )
        elif args.command == "bundle":
            build_bundle(
                args.signmar, args.archive, args.output, args.channel, args.version
            )
        elif args.command == "sign":
            sign(
                args.signmar,
                args.archive,
                args.output,
                args.certificate,
                args.key,
                args.channel,
                args.version,
            )
        else:
            if args.key or args.output:
                parser.error("Verification needs neither a key nor an output")
            verify(
                args.signmar, args.archive, args.certificate, args.channel, args.version
            )
    except (MarError, OSError, configparser.Error, tarfile.TarError) as error:
        parser.exit(1, f"MAR {args.command} failed: {error}\n")
    finally:
        os.umask(previous_mask)
    print(f"MAR {args.command} succeeded: {args.archive.name}")


if __name__ == "__main__":
    main()
