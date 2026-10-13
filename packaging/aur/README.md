# AUR packaging

`zen-bonsai-browser-bin` installs the fork's release tarball to `/opt/zen-bonsai`
with a `/usr/bin/zen` symlink.

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

The first entry is the published tarball's digest and changes with every
release. The release workflow's `aur` job refreshes it with `updpkgsums`
before pushing, so the copy here reads `SKIP` until the release it names
exists; set it by hand (`updpkgsums`, or `sha256sum` on the downloaded asset)
only when publishing outside that job. The second is `zen.desktop`, which only
changes if that file does.

The tarball source is renamed to `$pkgname-$pkgver.tar.xz` because the
release asset carries the same bare filename every version, and makepkg's
source cache keys on the filename: without the rename, an upgrade silently
reuses the previous release's cached tarball.
