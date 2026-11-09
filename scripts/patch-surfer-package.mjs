// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/.

import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

export function patchSurferPackaging(source) {
  const parsed = ts.createSourceFile(
    "package.js",
    source,
    ts.ScriptTarget.Latest,
    true,
  );
  const declaration = parsed.statements.find(
    (node) =>
      ts.isFunctionDeclaration(node) && node.name?.text === "createMarFile",
  );
  if (!declaration) {
    throw new Error(
      "Surfer MAR packaging changed; review the Firefox 160 compatibility patch",
    );
  }
  const arrays = [];
  function visit(node) {
    if (
      ts.isCallExpression(node) &&
      node.arguments[0]?.text === "./tools/update-packaging/make_full_update.sh"
    ) {
      const options = node.arguments[1];
      if (options && ts.isObjectLiteralExpression(options)) {
        const property = options.properties.find(
          (value) =>
            ts.isPropertyAssignment(value) &&
            value.name.getText(parsed) === "args",
        );
        if (property && ts.isArrayLiteralExpression(property.initializer)) {
          arrays.push(property.initializer);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(declaration);
  if (arrays.length !== 1) {
    throw new Error(
      "Expected one Surfer full-MAR invocation; refusing an ambiguous patch",
    );
  }
  const args = arrays[0].elements;
  const normalized = Array.from(args, (node) =>
    node.getText(parsed).replace(/\s/g, ""),
  );
  const oldArchive = "(0,utils_1.windowsPathToUnix)(constants_1.DIST_DIR)";
  const newArchive = "(0,utils_1.windowsPathToUnix)(marPath)";
  const directory = "(0,utils_1.windowsPathToUnix)(binary)";
  const appname = "__1.config.binaryName";
  if (
    normalized.length === 3 &&
    (normalized[0] === newArchive ||
      normalized[0] === "bonsaiMarPath(marPath)") &&
    (normalized[1] === directory ||
      normalized[1] === "bonsaiMarPath(binary)") &&
    normalized[2] === appname
  ) {
    return source;
  }
  if (
    normalized.length !== 2 ||
    normalized[0] !== oldArchive ||
    normalized[1] !== directory
  ) {
    throw new Error(
      "Unrecognized Surfer MAR arguments; refusing to change packaging blindly",
    );
  }
  // Firefox 160 takes an archive filename (not its directory) and requires
  // the lowercase appname to order executable updates correctly.
  return (
    source.slice(0, args[0].getStart(parsed)) +
    newArchive +
    source.slice(args[0].end, args[1].end) +
    ", " +
    appname +
    source.slice(args[1].end)
  );
}

export function patchSurferWindowsPaths(source) {
  const parsed = ts.createSourceFile(
    "package.js",
    source,
    ts.ScriptTarget.Latest,
    true,
  );
  const declaration = parsed.statements.find(
    (node) =>
      ts.isFunctionDeclaration(node) && node.name?.text === "createMarFile",
  );
  if (!declaration?.body)
    throw new Error(
      "Surfer MAR packaging changed; review the Windows path patch",
    );
  const replacement = String.raw`(path) => process.platform === 'win32'
    ? path.replace(/[\\]+/g, '/').replace(/^([a-zA-Z]):\//, (_, drive) => '/' + drive.toLowerCase() + '/').replace(/^\.\//, '')
    : path`;
  const normalize = (value) => value.replace(/\s/g, "").replace(/"/g, "'");
  const calls = [];
  const patchedCalls = [];
  let helper;
  function visit(node) {
    if (ts.isCallExpression(node)) {
      if (
        normalize(node.expression.getText(parsed)) ===
        "(0,utils_1.windowsPathToUnix)"
      )
        calls.push(node.expression);
      if (node.expression.getText(parsed) === "bonsaiMarPath")
        patchedCalls.push(node);
    }
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(parsed) === "bonsaiMarPath"
    )
      helper = node;
    ts.forEachChild(node, visit);
  }
  visit(declaration);
  if (
    helper &&
    calls.length === 0 &&
    patchedCalls.length === 4 &&
    normalize(helper.initializer?.getText(parsed) ?? "") ===
      normalize(replacement)
  )
    return source;
  if (helper || calls.length !== 4 || patchedCalls.length)
    throw new Error(
      "Unrecognized Surfer MAR path calls; refusing to patch blindly",
    );
  // Scope conversion to shell-bound MAR paths; native callers need their own conventions.
  let patched = source;
  for (const call of calls.reverse())
    patched =
      patched.slice(0, call.getStart(parsed)) +
      "bonsaiMarPath" +
      patched.slice(call.end);
  const insertion = declaration.body.getStart(parsed) + 1;
  return (
    patched.slice(0, insertion) +
    "\n  const bonsaiMarPath = " +
    replacement +
    ";\n" +
    patched.slice(insertion)
  );
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const require = createRequire(import.meta.url);
  const target =
    require.resolve("@zen-browser/surfer/dist/commands/package.js");
  const source = readFileSync(target, "utf8");
  const patched = patchSurferPackaging(source);
  if (patched !== source) {
    writeFileSync(target, patched);
    console.log("Patched Surfer for the Firefox 160 full-MAR interface");
  }
  const packaged = readFileSync(target, "utf8");
  const patchedPaths = patchSurferWindowsPaths(packaged);
  if (patchedPaths !== packaged) {
    writeFileSync(target, patchedPaths);
    console.log("Patched Surfer to preserve Windows drives in MAR shell paths");
  }
}
