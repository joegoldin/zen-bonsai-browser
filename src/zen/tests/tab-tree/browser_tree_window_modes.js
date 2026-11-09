/* Any copyright is dedicated to the Public Domain.
   https://creativecommons.org/publicdomain/zero/1.0/ */

"use strict";

async function checkLocalWindowTree({ private: isPrivate, unsynced, enabled }) {
  await SpecialPowers.pushPrefEnv({
    set: [
      ["zen.window-sync.prefer-unsynced-windows", unsynced],
      ["zen.tab-tree.enabled", enabled],
    ],
  });
  let win;
  let foreignTab;
  try {
    win = await BrowserTestUtils.openNewBrowserWindow({ private: isPrivate });
    await win.gZenWorkspaces.promiseInitialized;
    Assert.ok(
      win.gZenWorkspaces.privateWindowOrDisabled,
      "this window does not sync its workspace"
    );
    const tree = win.gZenTabTree;
    Assert.equal(tree.enabled, enabled, "the tree honors its own preference");
    if (!enabled) {
      return;
    }

    const parent = BrowserTestUtils.addTab(win.gBrowser, "about:blank", {
      skipAnimation: true,
    });
    const child = BrowserTestUtils.addTab(win.gBrowser, "about:blank", {
      skipAnimation: true,
    });
    for (const tab of [parent, child]) {
      Assert.equal(
        tab.ownerDocument,
        win.document,
        "the local tab belongs to this window's document"
      );
      Assert.ok(tree.isTreeEligible(tab), "the local tab is tree-eligible");
    }
    Assert.ok(tree.nestTab(child, parent), "local tabs can be nested");
    Assert.equal(tree.getParent(child), parent, "the child keeps its parent");
    tree.setCollapsed(parent, true);
    Assert.ok(
      child.hasAttribute("zen-tree-hidden"),
      "collapse hides the child"
    );
    tree.setCollapsed(parent, false);
    Assert.ok(!child.hasAttribute("zen-tree-hidden"), "expand shows the child");

    foreignTab = await addNormalTab();
    Assert.ok(
      !tree.isTreeEligible(foreignTab),
      "a normal-window tab cannot participate in this window's tree"
    );
    Assert.ok(
      !tree.nestTab(child, foreignTab),
      "cross-window nesting is rejected"
    );
    Assert.equal(tree.getParent(child), parent, "the local tree stays intact");
    Assert.equal(
      gZenTabTree.getParent(foreignTab),
      null,
      "the normal window does not acquire a private or unsynced parent"
    );
  } finally {
    if (foreignTab) {
      await cleanupTabs(foreignTab);
    }
    if (win) {
      await BrowserTestUtils.closeWindow(win);
    }
    await SpecialPowers.popPrefEnv();
  }
}

add_task(async function test_private_window_tree() {
  await checkLocalWindowTree({ private: true, unsynced: false, enabled: true });
});

add_task(async function test_unsynced_window_tree() {
  await checkLocalWindowTree({ private: false, unsynced: true, enabled: true });
});

add_task(async function test_private_window_tree_opt_out() {
  await checkLocalWindowTree({
    private: true,
    unsynced: false,
    enabled: false,
  });
});

add_task(async function test_unsynced_window_tree_opt_out() {
  await checkLocalWindowTree({
    private: false,
    unsynced: true,
    enabled: false,
  });
});
