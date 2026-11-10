// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";

const source = readFileSync(
  new URL("../../src/zen/tab-tree/ZenTabTree.mjs", import.meta.url),
  "utf8",
);
// The chrome-only base class handles startup. Exercise the real feature's
// initialization with that one import supplied by the test environment.
const importLine = /^import \{ nsZenDOMOperatedFeature \} from "[^"]+";\n/m;
assert.match(source, importLine);

for (const kind of ["normal", "private", "unsynced"]) {
  for (const preference of [true, false]) {
    test(`${kind} window honors tree preference ${preference}`, () => {
      const listeners = [];
      const window = {
        addEventListener: (event) => listeners.push(event),
      };
      runInNewContext(source.replace(importLine, ""), {
        nsZenDOMOperatedFeature: class {},
        Services: {
          prefs: {
            getBoolPref: (name) => {
              assert.equal(name, "zen.tab-tree.enabled");
              return preference;
            },
          },
        },
        gZenWorkspaces: { privateWindowOrDisabled: kind !== "normal" },
        window,
      });
      window.gZenTabTree.init();
      assert.equal(window.gZenTabTree.enabled, preference);
      if (preference) {
        assert.ok(listeners.includes("TabOpen"));
        assert.ok(listeners.includes("TabClose"));
        assert.ok(listeners.includes("SSTabRestored"));
      } else {
        assert.deepEqual(listeners, []);
      }
    });
  }
}

for (const kind of ["tab", "split"]) {
  test(`${kind} nodes from another window cannot join this tree`, () => {
    const window = {};
    const document = {};
    runInNewContext(source.replace(importLine, ""), {
      nsZenDOMOperatedFeature: class {},
      window,
      document,
      gBrowser: {
        isTab: (node) => node?.kind === "tab",
        isTabGroup: (node) => node?.kind === "split",
      },
    });
    const node = {
      kind,
      ownerDocument: document,
      pinned: false,
      group: null,
      hasAttribute: (name) => kind === "split" && name === "split-view-group",
    };
    assert.equal(window.gZenTabTree.isTreeEligible(node), true);
    node.ownerDocument = {};
    assert.equal(window.gZenTabTree.isTreeEligible(node), false);
  });
}
