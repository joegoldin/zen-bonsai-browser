// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";
import { test } from "node:test";
import ts from "typescript";
import { patchSurferPackaging } from "../patch-surfer-package.mjs";

const require = createRequire(import.meta.url);
const packagePath =
  require.resolve("@zen-browser/surfer/dist/commands/package.js");
const source = readFileSync(packagePath, "utf8");
const parsed = ts.createSourceFile(
  packagePath,
  source,
  ts.ScriptTarget.Latest,
  true,
);
const declaration = parsed.statements.find(
  (node) =>
    ts.isFunctionDeclaration(node) && node.name?.text === "createMarFile",
);
assert.ok(
  declaration,
  "Surfer must expose its MAR packaging function for the contract check",
);

test("the compatibility patch is idempotent on the installed dependency", () => {
  assert.equal(patchSurferPackaging(source), source);
});

test("an unfamiliar packaging caller fails closed", () => {
  assert.throws(
    () =>
      patchSurferPackaging(
        source.replace("make_full_update.sh", "different-update-tool.sh"),
      ),
    /Expected one Surfer full-MAR invocation/,
  );
});

test("the shim changes only the archive and application arguments", () => {
  const legacy = `// keep before\nasync function createMarFile() {
    await (0, utils_1.configDispatch)("./tools/update-packaging/make_full_update.sh", {
      args: [(0, utils_1.windowsPathToUnix)(constants_1.DIST_DIR), (0, utils_1.windowsPathToUnix)(binary),],
      env: { KEEP: true }
    });
  }\n// keep after\n`;
  const patched = patchSurferPackaging(legacy);
  assert.equal(
    patched,
    legacy
      .replace(
        "(0, utils_1.windowsPathToUnix)(constants_1.DIST_DIR)",
        "(0,utils_1.windowsPathToUnix)(marPath)",
      )
      .replace("(binary),]", "(binary), __1.config.binaryName,]"),
  );
  assert.equal(patchSurferPackaging(patched), patched);
});

for (const platform of ["linux", "win32"]) {
  test(`${platform} packaging passes the Firefox 160 archive/directory/appname contract`, async () => {
    let dispatched;
    const dist = path.resolve("artifacts/packaging-contract/dist");
    const objects = path.resolve("artifacts/packaging-contract/objects");
    const context = vm.createContext({
      process: { platform, surferPlatform: platform, env: {} },
      node_path_1: path,
      constants_1: { DIST_DIR: dist, OBJ_DIR: objects, ENGINE_DIR: "engine" },
      __1: { config: { binaryName: "zen" } },
      log_1: { log: { info() {}, debug() {} } },
      utils_1: {
        windowsPathToUnix: (value) => value,
        configDispatch: async (script, options) => {
          dispatched = { script, options };
        },
      },
    });
    vm.runInContext(
      `${declaration.getText(parsed)}; globalThis.createMarFile = createMarFile;`,
      context,
    );
    const result = await context.createMarFile("1.25t-bonsai.1", "release", {});
    const archive = path.join(dist, "output.mar");
    assert.equal(result, archive);
    assert.equal(
      dispatched.script,
      "./tools/update-packaging/make_full_update.sh",
    );
    assert.deepEqual(Array.from(dispatched.options.args), [
      archive,
      path.join(objects, "dist", "zen"),
      "zen",
    ]);
    assert.equal(dispatched.options.env.MAR_CHANNEL_ID, "release");
    assert.equal(dispatched.options.env.MOZ_PRODUCT_VERSION, "1.25t-bonsai.1");
  });
}
