# AUR packaging

`zen-bonsai-browser-bin` installs the fork's release tarball to
`/usr/lib/zen-bonsai`, with a `/usr/bin/zen` symlink and a desktop entry that
uses the installed `zen` icon. This keeps the bundled libraries in Arch's
expected location.

## Why `conflicts` and `provides`

The fork deliberately keeps upstream Zen's `appId` and `binaryName`, so it
installs to the same `/usr/bin/zen` path and shares the same profile
directory. `conflicts` makes that a clear message from pacman instead of a
bare file-conflict error, and `provides` lets packages depending on
`zen-browser` be satisfied by this one.

You cannot have both installed at once. That is intended.

`replaces` and the extra `conflicts` entry name `zen-browser-tst-bin`, this
package's name before the fork was renamed to Zen Bonsai, so `pacman -Syu`
moves an existing install over.

## Version mapping

Arch forbids a dash in `pkgver`, so `1.23.2b-bonsai.1` becomes `1.23.2b_bonsai.1`
and `${pkgver//_/-}` converts it back when building the download URL.

## sha256sums

The first entry is the published tarball's digest. The release workflow's
`aur` job refreshes it with `updpkgsums` before pushing the package. The
second is the digest of `zen.desktop`. Both checksums are committed; released
packages must not use `SKIP`. Run `makepkg --verifysource` to check them.

The tarball source is renamed to `$pkgname-$pkgver.tar.xz` because the
release asset carries the same bare filename every version, and makepkg's
source cache keys on the filename: without the rename, an upgrade silently
reuses the previous release's cached tarball.

## Check the package

On a machine with Docker, run:

```fish
bash scripts/tests/check-aur-package.sh
```

This runs `makepkg --verifysource`, generates `.SRCINFO`, builds the package,
and checks it with `namcap`. It fails on reported packaging errors even when
`namcap` exits successfully. It also validates the desktop file and runs the
packaged binary's `--version` command. Dependency warnings remain visible;
this is not a graphical browser test. Build artifacts stay under
`artifacts/aur-package-check/`.
