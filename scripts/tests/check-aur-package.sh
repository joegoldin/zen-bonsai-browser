#!/usr/bin/env bash
# Validate the released binary package on Arch, rather than only parsing PKGBUILD.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
mkdir -p "$root/artifacts/aur-package-check"
docker run --rm -i \
  -v "$root/packaging/aur:/input:ro" \
  -v "$root/artifacts/aur-package-check:/check" \
  archlinux:latest /bin/bash -euo pipefail <<'CONTAINER'
pacman -Syu --noconfirm base-devel pacman-contrib namcap desktop-file-utils \
  gtk3 libxt mime-types dbus-glib nss ttf-dejavu libpulse
useradd -m -u 1000 builder
cp /input/PKGBUILD /input/zen.desktop /check/
chown -R builder:builder /check
runuser -u builder -- /bin/bash -euo pipefail <<'BUILD'
cd /check
makepkg --verifysource
makepkg --printsrcinfo > .SRCINFO
makepkg --noconfirm --force
package=$(makepkg --packagelist)
namcap "$package" | tee namcap.log
# namcap can report errors while returning success; preserve its actual verdict.
if grep -q ' E: ' namcap.log; then
  echo 'namcap reported packaging errors' >&2
  exit 1
fi
test "$(readlink pkg/zen-bonsai-browser-bin/usr/bin/zen)" = /usr/lib/zen-bonsai/zen
test -f pkg/zen-bonsai-browser-bin/usr/share/icons/hicolor/128x128/apps/zen.png
desktop-file-validate pkg/zen-bonsai-browser-bin/usr/share/applications/zen.desktop
./pkg/zen-bonsai-browser-bin/usr/lib/zen-bonsai/zen --version
BUILD
CONTAINER
