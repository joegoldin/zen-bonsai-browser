# Offline MAR signing

Bonsai release builds produce unsigned MARs. They are build artifacts, not
updates: never publish them or generate live update metadata from them.

Keep the release key outside the checkout. The existing key lives at
`~/.local/share/zen-bonsai/signing/mar-private-key.pem`, with mode `0600`, in a
`0700` directory. Back it up separately in 1Password. Do not put it in a GitHub
artifact, repository, container image, or Nix store.

Use `scripts/bonsai_mar.py` for signing. The inherited `mar_sign.sh -g` and `-s`
commands write private material under `build/signing`; do not use those modes.
Its `-i` mode only installs the public certificate into engine sources.

## Build the unsigned archives

`npm ci` runs `scripts/patch-surfer-package.mjs` to adapt Surfer's full-MAR
call to Firefox 160's `ARCHIVE DIRECTORY APPNAME` interface. The patch uses
an archive filename and the configured binary name. It leaves an already-fixed
caller unchanged and fails installation if the caller has an unfamiliar shape.
The Node tests check both Linux and Windows arguments before compilation.

Both CI jobs pin one UTC `MOZ_BUILD_DATE` across compilation and packaging.
Packaging can regenerate INI files without rebuilding the executable;
`scripts/check_build_identity.py` therefore checks `--full-version` against both
INI files before accepting artifacts. Otherwise, update metadata can advertise
a newer build ID than the installed binary and repeatedly offer the same update.

## Sign and verify

Use the compiled engine's `dist/bin/signmar`, not `dist/host/bin/mar`: the
latter can be built without signing and verification support. The devenv
shell supplies OpenSSL and NSS's `certutil`/`pk12util` commands.

These commands work in fish. Adjust the object-directory path to the build
whose release artifacts you are checking:

```fish
set signmar /tmp/zen-bonsai-sync-160/engine/obj-x86_64-pc-linux-gnu/dist/bin/signmar

devenv shell -- python3 scripts/bonsai_mar.py sign artifacts/windows.unsigned.mar \
    --signmar "$signmar" --channel release --version 1.25t-bonsai.1 \
    --key "$HOME/.local/share/zen-bonsai/signing/mar-private-key.pem" \
    --output artifacts/windows.mar

devenv shell -- python3 scripts/bonsai_mar.py verify artifacts/windows.mar \
    --signmar "$signmar" --channel release --version 1.25t-bonsai.1
```

The default trust root is `build/signing/public_key.der`. The certificate
must match the private key. Signing preserves the unsigned input, refuses to
overwrite an output, and verifies the result using a separate public-only NSS
database before making the signed archive available.

Private NSS databases and PKCS#12 bundles are created in a private temporary
directory outside the checkout and removed on normal completion or exceptions.
The PKCS#12 password is random and passed through a file, not command-line
arguments. Signing fails if the key is inside the checkout, readable by other
users, or the temporary directory would be inside the checkout.

The verifier requires exactly one signature, the requested channel and Bonsai
product version, and a signature accepted by the selected public root. It does
not trust certificates carried by an archive or fall back to upstream keys.

## Regression checks

The integration suite creates disposable keys outside the repository; it does
not read the release private key:

```fish
devenv shell -- env SIGNMAR="$signmar" python3 -m unittest discover \
    -s scripts/tests -p test_bonsai_mar.py -v
```

It checks valid signing, unsigned and tampered archives, foreign roots,
truncation, channel/version mismatches, input preservation, output collision,
private-key permissions, and cleanup after failure. These tool-level checks do
not replace an installed-browser update test.

## Prepare the combined update bundle

Collect the **same build's** metadata beside its signed MAR. Do not copy INI
files from a different build or from the local Nightly test engine:

```text
artifacts/signed-updates/
  linux.mar
  linux.application.ini
  linux.platform.ini
  windows.mar
  windows.application.ini
  windows.platform.ini
```

The artifact-only Linux workflow supplies its unsigned MAR and both INI files.
The Windows artifact supplies its unsigned MAR, `application.ini`, and
`platform.ini`; both INI files are also inside the Windows application ZIP.
Sign each MAR separately, then generate the two-platform bundle:

```fish
devenv shell -- python3 scripts/bonsai_mar.py bundle artifacts/signed-updates \
    --signmar "$signmar" --channel release --version 1.25t-bonsai.1 \
    --output artifacts/update-bundle

devenv shell -- python3 scripts/bonsai_mar.py attest artifacts/update-bundle \
    --signmar "$signmar" --channel release --version 1.25t-bonsai.1 \
    --key "$HOME/.local/share/zen-bonsai/signing/mar-private-key.pem"

devenv shell -- python3 scripts/bonsai_mar.py pack artifacts/update-bundle \
    --channel release --version 1.25t-bonsai.1 \
    --output artifacts/bonsai-update-bundle.tar
```

Bundle generation checks both MAR signatures, both application versions, matching
build IDs, and the pinned Firefox milestone before producing any output. It
creates hash-addressed MAR paths and the Linux and two Windows ABI manifests
under `updates/browser/…/<channel>/update.xml`.

Attestation signs a domain-labelled JSON index with OpenSSL SHA-384. The index
binds every MAR and XML file's SHA-512 hash. This lets the publisher verify the
bundle with only the repository's public certificate; CI never needs the release
private key or a compiled `signmar`. The client still verifies each MAR's own
signature. Packing includes only the authenticated files, not other files that
may have been placed in the staging directory.

## Publish only after release verification

Keep Linux CI in its default `artifacts_only: true` mode while verifying the
combined release. It must not publish a Linux-only release or update the AUR.
Finish the Windows VM installation and signed-update/tamper tests before
publishing the combined GitHub release.

Attach `bonsai-update-bundle.tar` alongside the Linux tarball/deb/rpm and Windows
ZIP/full installer. Then dispatch **Publish verified Bonsai updates** for that
published tag and channel. The workflow refuses drafts and releases missing
these artifacts. It checks out the tag's public trust root and verifies the
attestation and file hashes before using R2 credentials.

The publisher uploads both immutable MARs first and downloads them through
`https://updates.zen-bonsai.dev` to check their actual hashes and sizes. Only
then does it upload the update XML with `Cache-Control: no-store`, followed by
public readback checks. Redirects, mismatched files, missing credentials, and
network failures stop publication; they never trigger an upstream fallback.
A mid-publication failure is not success and requires inspecting the public
metadata before retrying.

A local read-only publication check needs no R2 credentials:

```fish
devenv shell -- python3 -m scripts.bonsai_publish artifacts/update-bundle \
    --channel release --version 1.25t-bonsai.1
```

Actual uploads require `--publish`, the configured R2 bucket/account, and scoped
AWS-compatible credentials. The GitHub workflow receives these only in its
upload step. No workflow reads the offline signing key.

Nix builds remain separate: they compile with `--disable-updater` and must not
install these updates.
