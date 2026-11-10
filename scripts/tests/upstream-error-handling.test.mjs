// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parsers } from "@zen-browser/prettier/plugins/babel.mjs";

function methodExpression(path, name) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const ast = parsers.babel.parse(source);
  const method = ast.program.body
    .map((node) => node.declaration ?? node)
    .filter((node) => node.type === "ClassDeclaration")
    .flatMap((node) => node.body.body)
    .find((node) => (node.key?.name ?? node.key?.id?.name) === name);
  assert.ok(method, `Actual source must contain ${name}`);
  const parameters = method.params
    .map((parameter) => source.slice(parameter.start, parameter.end))
    .join(", ");
  // Isolate the real orchestration from chrome-only DOM hooks. Private access
  // becomes ordinary context properties; the method body otherwise stays live.
  const body = source
    .slice(method.body.start, method.body.end)
    .replace(/this\.#([a-zA-Z]\w*)/g, "this._$1");
  return `${method.async ? "async " : ""}function (${parameters}) ${body}`;
}

const updateWorkspace = methodExpression(
  "../../src/zen/spaces/ZenGradientGenerator.mjs",
  "updateCurrentWorkspace",
);

for (const [description, stored, expected] of [
  ["valid", '{"x":0.25,"y":0.75}', { x: 0.25, y: 0.75 }],
  ["absent", null, null],
  ["malformed", "{broken position", null],
]) {
  test(`${description} dot position does not prevent saving the workspace`, () => {
    const workspace = { uuid: "space" };
    let captured;
    let saved;
    const dot = {
      style: { getPropertyValue: () => "#123456" },
      classList: { contains: (name) => name === "custom" },
      getAttribute: (name) =>
        ({
          "data-index": "0",
          "data-position": stored,
          "data-type": "explicit",
        })[name],
    };
    const context = {
      panel: { querySelectorAll: () => [dot] },
      _currentLightness: 50,
      currentOpacity: 1,
      currentTexture: 0,
      currentTextureType: "grain",
      useAlgo: "analogous",
      workspaceBeingEdited: workspace,
      onWorkspaceChange: (updated) => assert.equal(updated, workspace),
    };
    const update = new Function(
      "nsZenThemePicker",
      "gZenWorkspaces",
      `return (${updateWorkspace})`,
    )(
      { getTheme: (colors) => ((captured = colors), { colors }) },
      { activeWorkspace: "space", saveWorkspace: (value) => (saved = value) },
    );
    assert.doesNotThrow(() => update.call(context, false));
    assert.equal(saved, workspace);
    assert.equal(workspace.theme.colors, captured);
    assert.equal(captured[0].c, "#123456");
    assert.deepEqual(captured[0].position, expected);
  });
}

const openGlance = methodExpression(
  "../../src/zen/glance/ZenGlanceManager.mjs",
  "animateGlanceOpening",
);

test("Glance waits for preview data and resolves after animation", async () => {
  const events = [];
  const preview = { image: "preview fixture" };
  const context = {
    _prepareGlanceAnimation: () => events.push("prepare"),
    _getElementPreviewData: async () => {
      events.push("preview");
      return preview;
    },
    contentWrapper: { style: {} },
    _glances: new Map([["glance", {}]]),
    _currentGlanceID: "glance",
    _executeGlanceAnimation: (data, browser, resolve) => {
      events.push("animate");
      assert.equal(data.elementData, preview);
      queueMicrotask(() => resolve("glance tab"));
    },
  };
  const open = new Function("gZenViewSplitter", `return (${openGlance})`)({
    onLocationChange: () => events.push("location"),
  });
  assert.equal(
    await open.call(context, { width: 20, height: 20 }, {}),
    "glance tab",
  );
  assert.equal(context._glances.get("glance").elementData, preview);
  assert.deepEqual(events, ["prepare", "location", "preview", "animate"]);
});

test("a failed Glance preview rejects its caller instead of staying pending", () => {
  // Isolate the old executor's unhandled rejection so the regression can also
  // distinguish its orphaned outer promise from the required caller rejection.
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
      let unhandled = "";
      process.on("unhandledRejection", error => { unhandled = error.message; });
      const gZenViewSplitter = { onLocationChange() {} };
      const context = {
        _prepareGlanceAnimation() {},
        _getElementPreviewData() { return Promise.reject(new Error("preview failed")); },
        contentWrapper: { style: {} },
        _glances: new Map([["glance", {}]]),
        _currentGlanceID: "glance",
        _executeGlanceAnimation() { throw new Error("animation must not start"); },
      };
      const open = (${openGlance});
      const outcome = await Promise.race([
        open.call(context, { width: 20, height: 20 }, {}).then(
          () => "resolved", error => "rejected:" + error.message
        ),
        new Promise(resolve => setTimeout(() => resolve("pending"), 100)),
      ]);
      console.log(outcome);
      console.log("unhandled:" + (unhandled || "none"));
      `,
    ],
    { encoding: "utf8", timeout: 3000 },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), "rejected:preview failed\nunhandled:none");
});
