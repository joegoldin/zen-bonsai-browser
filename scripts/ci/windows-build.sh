#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
set -euo pipefail

if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_ENVIRONMENT:-} != github-hosted ]]; then
  echo 'This script builds on an ephemeral GitHub-hosted Windows runner only.' >&2
  exit 1
fi
if [[ -z ${MOZILLABUILD:-} || $(uname -s) != *NT* ]]; then
  echo 'Run this script through the MozillaBuild Windows shell.' >&2
  exit 1
fi
if [[ ! ${BONSAI_VERSION:-} =~ ^[0-9][0-9A-Za-z.]*-bonsai\.[0-9]+$ ]]; then
  echo 'BONSAI_VERSION must be a fork version, such as 1.25t-bonsai.1.' >&2
  exit 1
fi

export SURFER_PLATFORM=win32
export SURFER_COMPAT=x86_64
export ZEN_RELEASE=1
export ZEN_RELEASE_BRANCH=release
export ZEN_GA_DISABLE_PGO=1
export CARGO_INCREMENTAL=0
export CARGO_BUILD_JOBS=4
# Keep toolchains and caches beside the source/object tree on the large volume.
MOZBUILD_STATE_PATH="$(cygpath -w /d/mozbuild)"
CARGO_HOME="$(cygpath -w /d/cargo-home)"
RUSTUP_HOME="$(cygpath -w /d/rustup-home)"
export MOZBUILD_STATE_PATH CARGO_HOME RUSTUP_HOME

git config --global user.name 'github-actions[bot]'
git config --global user.email 'github-actions[bot]@users.noreply.github.com'
npm ci
node --test scripts/tests/*.test.mjs
python3 -m unittest discover -s scripts/tests -p 'test_firefox_source.py'
npm run surfer -- ci --brand release --display-version "$BONSAI_VERSION"

toolchain=$(python3 -c 'import tomllib; print(tomllib.load(open("rust-toolchain.toml", "rb"))["toolchain"]["channel"])')
rustup toolchain install "$toolchain" --profile minimal
rustup target add --toolchain "$toolchain" x86_64-pc-windows-msvc
npm run download
npm run import
# All updater certificate slots must contain the fork root, never Mozilla/Zen's.
bash scripts/mar_sign.sh -i
sh scripts/download-language-packs.sh
(cd engine && ./mach --no-interactive bootstrap --application-choice browser --no-system-changes)

# Generate the normal release configuration before checking its security flags.
SURFER_MOZCONFIG_ONLY=1 npm run build
(cd engine && ./mach configure)
mapfile -t objects < <(find engine -maxdepth 1 -type d -name 'obj-*')
if [[ ${#objects[@]} != 1 ]]; then
  echo 'Expected exactly one Windows object directory.' >&2
  exit 1
fi
objdir=${objects[0]}
python3 - "$objdir/config.status.json" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text())["substs"]
for flag in ("MOZ_UPDATER", "MOZ_VERIFY_MAR_SIGNATURE"):
    if config.get(flag) not in (True, 1, "1"):
        raise SystemExit(f"Windows release requires {flag}")
PY
(cd engine && ./mach build -j4)
npm run package
(cd engine && ./mach build installer)

mkdir -p artifacts/windows-release
mapfile -t archives < <(find dist -maxdepth 1 -type f -name '*.win64.zip')
mapfile -t installers < <(find "$objdir/dist" -maxdepth 1 -type f -name '*.installer.exe')
if [[ ${#archives[@]} != 1 || ${#installers[@]} != 1 ]]; then
  echo 'Expected one win64 archive and one full NSIS installer; stub installers are not shipped.' >&2
  exit 1
fi
cp "${archives[0]}" artifacts/windows-release/zen.windows-x86_64.zip
cp "${installers[0]}" artifacts/windows-release/zen.windows-x86_64.installer.exe
# Signing is a separate trusted release step. Never publish this unsigned MAR.
cp dist/output.mar artifacts/windows-release/windows.unsigned.mar
cp "$objdir/dist/bin/application.ini" artifacts/windows-release/application.ini
cp "$objdir/dist/bin/platform.ini" artifacts/windows-release/platform.ini

(cd artifacts/windows-release && sha256sum zen.windows-x86_64.zip zen.windows-x86_64.installer.exe windows.unsigned.mar > SHA256SUMS)
