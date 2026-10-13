#!/usr/bin/env nix-shell
#!nix-shell -i bash -p librsvg imagemagick libicns
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# Renders every Zen Bonsai release branding raster from
# configs/branding/release/bonsai.svg. The outputs are committed, so builds stay
# offline; rerun this only when the SVG changes. Sizes match the Zen assets they
# replace. The wordmarks in content/ are hand-made SVGs, not generated here.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
brand="$root/configs/branding/release"
svg="$brand/bonsai.svg"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

png() { rsvg-convert -w "$1" -h "$1" "$svg" -o "$2"; }

# A square icon centred on a transparent canvas of the given size.
padded() {
  local icon="$1" w="$2" h="$3" out="$4"
  png "$icon" "$tmp/padded.png"
  magick "$tmp/padded.png" -background none -gravity center -extent "${w}x${h}" "$out"
}

ico() {
  local out="$1"
  shift
  local frames=()
  for size in "$@"; do
    png "$size" "$tmp/ico-$size.png"
    frames+=("$tmp/ico-$size.png")
  done
  magick "${frames[@]}" "$out"
}

for size in 16 22 24 32 48 64 128 256 512 1024; do
  png "$size" "$brand/logo$size.png"
done
png 1024 "$brand/logo.png"
png 1024 "$brand/logo-mac.png"

ico "$brand/firefox.ico" 256 64 48 32 16
ico "$brand/firefox64.ico" 256 64 48 32 16
for name in document document_pdf pbmode; do
  ico "$brand/$name.ico" 16 32 48 64 128 256
done

# png2icns picks each icon's slot from its pixel size.
for size in 16 32 128 256 512 1024; do
  png "$size" "$tmp/icns-$size.png"
done
png2icns "$brand/firefox.icns" "$tmp"/icns-{16,32,128,256,512,1024}.png >/dev/null

padded 860 1042 1046 "$brand/VisualElements_150.png"
padded 860 1042 1046 "$brand/VisualElements_70.png"
png 126 "$brand/PrivateBrowsing_70.png"
png 270 "$brand/PrivateBrowsing_150.png"

# About dialog and about:privatebrowsing.
cp "$svg" "$brand/content/about-logo.svg"
cp "$svg" "$brand/content/about-logo-private.svg"
png 512 "$brand/content/about-logo.png"
png 1024 "$brand/content/about-logo@2x.png"
png 192 "$brand/content/about-logo-private.png"
png 384 "$brand/content/about-logo-private@2x.png"

# The README's logo.
cp "$svg" "$root/docs/assets/zen-bonsai.svg"
