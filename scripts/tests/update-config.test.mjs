// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import configuration from "../../surfer.json" with { type: "json" };

test("release builds attribute their source to the fork", () => {
  const mozconfig = readFileSync(
    new URL("../../configs/common/mozconfig", import.meta.url),
    "utf8"
  );
  assert.match(
    mozconfig,
    /^export MOZ_SOURCE_REPO=https:\/\/github\.com\/joegoldin\/zen-bonsai-browser$/m
  );
});

test("Bonsai update checks use the fork-owned HTTPS host", () => {
  assert.equal(configuration.updateHostname, "updates.zen-bonsai.dev");
});

for (const [name, brand] of Object.entries(configuration.brands)) {
  test(`${name} update archives belong to the Bonsai repository`, () => {
    assert.equal(brand.release.github.repo, "joegoldin/zen-bonsai-browser");
  });
}
