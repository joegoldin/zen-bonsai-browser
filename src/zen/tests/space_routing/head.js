/* Any copyright is dedicated to the Public Domain.
   https://creativecommons.org/publicdomain/zero/1.0/ */

"use strict";

const { gZenSpaceRoutingManager } = ChromeUtils.importESModule(
  "resource:///modules/zen/spacerouting/ZenSpaceRoutingManager.sys.mjs",
);

const { gZenManagedSpaces } = ChromeUtils.importESModule(
  "resource:///modules/zen/spacerouting/ZenManagedSpaces.sys.mjs",
);

const { ContextualIdentityService } = ChromeUtils.importESModule(
  "moz-src:///toolkit/components/contextualidentity/ContextualIdentityService.sys.mjs",
);

async function withManagedSpaces(json, fn) {
  const before = new Set(gZenWorkspaces.getWorkspaces().map(w => w.uuid));
  const activeBefore = gZenWorkspaces.activeWorkspace;
  await SpecialPowers.pushPrefEnv({
    set: [["zen.space-routing.managed-spaces", JSON.stringify(json)]],
  });
  try {
    await fn();
  } finally {
    // Pop the pref first: while it is set the Spaces it describes are managed,
    // and removeWorkspace refuses to delete those.
    await SpecialPowers.popPrefEnv();
    // The reconcile pass creates Spaces as a side effect. Leaving them behind
    // leaks into later tests in this directory, whose real addTab() calls then
    // trip over a workspace whose tab has no linked browser yet.
    for (const ws of gZenWorkspaces.getWorkspaces()) {
      if (!before.has(ws.uuid)) {
        await gZenWorkspaces.removeWorkspace(ws.uuid);
      }
    }
    if (activeBefore && gZenWorkspaces.activeWorkspace !== activeBefore) {
      const restore = gZenWorkspaces
        .getWorkspaces()
        .find(w => w.uuid === activeBefore);
      if (restore) {
        await gZenWorkspaces.changeWorkspace(restore);
      }
    }
  }
}

function clearAllRoutes() {
  for (const route of gZenSpaceRoutingManager.getAllRoutes()) {
    gZenSpaceRoutingManager.removeRoute(route.id);
  }
}

function addRoute({
  reference = "",
  openIn = "most-recent-space",
  matchType = "contains",
} = {}) {
  const route = gZenSpaceRoutingManager.createNewRoute();
  route.reference = reference;
  route.openIn = openIn;
  route.matchType = matchType;
  gZenSpaceRoutingManager.updateRoute(route);
  return route;
}

function makeFakeWindow({
  ready = true,
  workspaces = [],
  workspaceEnabled = true,
} = {}) {
  return {
    gZenStartup: { isReady: ready },
    gZenWorkspaces: {
      workspaceEnabled,
      moveCalls: [],
      changeCalls: [],
      lastSelectedWorkspaceTabs: {},
      getWorkspaces() {
        return workspaces;
      },
      getWorkspaceFromId(id) {
        return workspaces.find(w => w.uuid === id) || null;
      },
      moveTabToWorkspace(tab, uuid) {
        this.moveCalls.push({ tab, uuid });
      },
      changeWorkspace(workspace) {
        this.changeCalls.push(workspace);
        return Promise.resolve();
      },
    },
  };
}

async function flushEventLoop() {
  for (let i = 0; i < 5; i++) {
    await new Promise(resolve => Services.tm.dispatchToMainThread(resolve));
  }
}
