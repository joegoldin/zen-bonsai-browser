# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Publish an offline-attested bundle. Run with python3 -m scripts.bonsai_publish."""

import argparse
import hashlib
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from .bonsai_mar import CERTIFICATE, MarError, run, verify_bundle


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_public_file(path, relative, opener):
    expected_size = path.stat().st_size
    expected_hash = hashlib.sha512()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            expected_hash.update(chunk)
    actual_hash = hashlib.sha512()
    size = 0
    request = urllib.request.Request(
        f"https://updates.zen-bonsai.dev/{relative}",
        headers={"Cache-Control": "no-cache"},
    )
    try:
        with opener.open(request, timeout=60) as response:
            if response.status != 200:
                raise MarError("The public update host did not return HTTP 200")
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                size += len(chunk)
                if size > expected_size:
                    raise MarError("The public update host returned an oversized file")
                actual_hash.update(chunk)
    except (OSError, urllib.error.URLError) as error:
        raise MarError(
            "Cannot verify the uploaded file on the public update host"
        ) from error
    if size != expected_size or actual_hash.digest() != expected_hash.digest():
        raise MarError(
            "Public update file hash/size does not match the authenticated bundle"
        )


def publish(
    bundle, channel, version, account, bucket, *, execute=False, certificate=CERTIFICATE
):
    index = verify_bundle(bundle, certificate, channel, version)
    if not execute:
        print(
            f"Verified {version}: {len(index['mar_files'])} MARs and {len(index['xml_files'])} manifests; nothing uploaded"
        )
        return
    if not account or not re.fullmatch(r"[0-9a-f]{32}", account):
        raise MarError(
            "CLOUDFLARE_ACCOUNT_ID must be a 32-character hexadecimal account ID"
        )
    if not bucket or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise MarError("R2_BUCKET must be a valid bucket name")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise MarError(f"{name} is not configured")
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
    opener = urllib.request.build_opener(NoRedirect())

    def upload(relative, content_type, cache_control):
        run(
            "aws",
            "s3",
            "cp",
            str(bundle / relative),
            f"s3://{bucket}/{relative}",
            "--endpoint-url",
            endpoint,
            "--region",
            "auto",
            "--only-show-errors",
            "--content-type",
            content_type,
            "--cache-control",
            cache_control,
            "--metadata",
            f"sha512={index['sha512'][relative]}",
        )

    # Never advertise either platform until both immutable archives are served
    # intact through the real HTTPS hostname (not just accepted by the S3 API).
    for relative in index["mar_files"]:
        upload(
            relative, "application/octet-stream", "public, max-age=31536000, immutable"
        )
    for relative in index["mar_files"]:
        check_public_file(bundle / relative, relative, opener)
    for relative in index["xml_files"]:
        upload(
            relative,
            "application/xml; charset=utf-8",
            "no-store, max-age=0, must-revalidate",
        )
    for relative in index["xml_files"]:
        check_public_file(bundle / relative, relative, opener)
    print(f"Published and verified {version} on updates.zen-bonsai.dev")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("release", "twilight"), required=True)
    parser.add_argument("--account", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
    parser.add_argument("--bucket", default=os.environ.get("R2_BUCKET"))
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Actually upload; without this flag verification is read-only",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9][0-9A-Za-z.]*-bonsai\.[0-9]+", args.version):
        parser.error("Expected a Bonsai release version")
    try:
        publish(
            args.bundle,
            args.channel,
            args.version,
            args.account,
            args.bucket,
            execute=args.publish,
        )
    except (MarError, OSError) as error:
        parser.exit(1, f"Update publication failed: {error}\n")


if __name__ == "__main__":
    main()
