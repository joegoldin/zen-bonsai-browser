// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parsers } from "@zen-browser/prettier/plugins/babel.mjs";

const source = readFileSync(
  new URL("../../src/zen/common/modules/ZenUpdates.mjs", import.meta.url),
  "utf8",
);
const ast = parsers.babel.parse(source);
const declaration = ast.program.body.find(
  (node) => node.type === "ExportDefaultDeclaration",
)?.declaration;
assert.equal(declaration?.id?.name, "checkForZenUpdates");
const constants = ast.program.body
  .filter((node) => node.type === "VariableDeclaration")
  .map((node) => source.slice(node.start, node.end))
  .join("\n");

function showUpdate({
  lastVersion = "older",
  testing = false,
  enabled = true,
} = {}) {
  const prefs = new Map([
    ["zen.updates.last-version", lastVersion],
    [
      "app.releaseNotesURL.prompt",
      "https://zen-browser.app/release-notes/%VERSION%/",
    ],
  ]);
  const notifications = [];
  const Services = {
    appinfo: { version: "1.25t-bonsai.2" },
    prefs: {
      getStringPref: (name, fallback) => prefs.get(name) ?? fallback,
      setStringPref: (name, value) => prefs.set(name, value),
      getBoolPref: () => enabled,
    },
    urlFormatter: { formatURL: (url) => url },
  };
  const check = new Function(
    "Services",
    "gZenUIManager",
    "createSidebarNotification",
    `${constants}\nreturn (${source.slice(declaration.start, declaration.end)})`,
  )(Services, { testingEnabled: testing }, (notification) =>
    notifications.push(notification),
  );
  check();
  return { notifications, prefs };
}

test("post-update changelog opens Bonsai releases even with an old upstream preference", () => {
  const { notifications, prefs } = showUpdate();
  assert.equal(notifications.length, 1);
  assert.equal(
    notifications[0].links[0].url,
    "https://github.com/joegoldin/zen-bonsai-browser/releases",
  );
  assert.equal(prefs.get("zen.updates.last-version"), "1.25t-bonsai.2");
});

for (const [name, options] of [
  ["unchanged version", { lastVersion: "1.25t-bonsai.2" }],
  ["test mode", { testing: true }],
  ["disabled notifications", { enabled: false }],
]) {
  test(`post-update popup stays suppressed for ${name}`, () => {
    assert.equal(showUpdate(options).notifications.length, 0);
  });
}
