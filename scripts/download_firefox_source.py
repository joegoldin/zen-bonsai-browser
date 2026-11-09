#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage an explicitly pinned candidate archive before Surfer downloads it."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent


def stage_source(config, cache, *, opener=urlopen):
    source = config["version"].get("source")
    if source is None:
        return None
    version = config["version"]["version"]
    filename = f"firefox-{version}.source.tar.xz"
    url = urlparse(source["url"])
    if (
        url.scheme != "https"
        or url.netloc != "archive.mozilla.org"
        or not url.path.endswith(f"/source/{filename}")
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Pinned source must name this Firefox version on archive.mozilla.org"
        )
    digest = source["hash"]
    if not digest.startswith("sha512-"):
        raise ValueError("Pinned source requires a SHA-512 SRI checksum")
    expected = base64.b64decode(digest.removeprefix("sha512-"), validate=True)
    if len(expected) != 64:
        raise ValueError("Invalid SHA-512 checksum length")

    def verify(path):
        with path.open("rb") as archive:
            actual = hashlib.file_digest(archive, "sha512").digest()
        if actual != expected:
            raise ValueError(f"Source checksum mismatch: {path}")

    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / filename
    if archive.exists():
        verify(archive)
        return archive
    # Keep partial downloads out of Surfer's cache until verification succeeds.
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        downloaded = Path(temporary) / filename
        with (
            opener(source["url"], timeout=60) as response,
            downloaded.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        verify(downloaded)
        downloaded.replace(archive)
    return archive


def main():
    try:
        config = json.loads((ROOT / "surfer.json").read_text())
        stage_source(config, ROOT / ".surfer" / "engine")
        return subprocess.run(
            [
                "node",
                str(ROOT / "node_modules/@zen-browser/surfer/dist/index.js"),
                "download",
                *sys.argv[1:],
            ],
            cwd=ROOT,
            check=False,
        ).returncode
    except (OSError, ValueError, KeyError, TypeError, URLError) as error:
        print(f"Firefox source setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
