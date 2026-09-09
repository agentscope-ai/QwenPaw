import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/layouts/index.module.less"),
  "utf8",
);
const sidebarSource = readFileSync(
  join(process.cwd(), "src/layouts/Sidebar.tsx"),
  "utf8",
);
const headerSource = readFileSync(
  join(process.cwd(), "src/layouts/Header.tsx"),
  "utf8",
);
const appBrandSource = readFileSync(
  join(process.cwd(), "src/layouts/AppBrand.tsx"),
  "utf8",
);
const mainLayoutSource = readFileSync(
  join(process.cwd(), "src/layouts/MainLayout/index.tsx"),
  "utf8",
);
const sessionListSource = readFileSync(
  join(process.cwd(), "src/layouts/SidebarSessionList.tsx"),
  "utf8",
);
const sessionListStylesSource = readFileSync(
  join(process.cwd(), "src/layouts/sidebarSessionList.module.less"),
  "utf8",
);

describe("Sidebar overflow layout", () => {
  it("owns the application brand while preserving plugin header slots", () => {
    expect(sidebarSource).toContain("<AppBrand");
    expect(sidebarSource).toContain("className={styles.brandCollapseToggle}");
    expect(stylesSource).toMatch(
      /\.appBrand\s*\{[\s\S]*?&\[hidden\]\s*\{\s*display:\s*none;/,
    );
    expect(appBrandSource).toContain(
      '<Slot name="header.logo" kind="replace">',
    );
    expect(headerSource).toContain('<Slot name="header.left" kind="fill" />');
    expect(headerSource).toContain('<Slot name="header.right" kind="fill" />');
    expect(headerSource).toContain("showBrand && <AppBrand />");
    expect(mainLayoutSource).toContain(
      "<Header showBrand={settingsCenterActive} />",
    );
  });

  it("places the sidebar beside the header and content column", () => {
    const sidebarIndex = mainLayoutSource.indexOf("<Sidebar");
    const contentLayoutIndex = mainLayoutSource.indexOf(
      "className={styles.mainContentLayout}",
    );
    const headerIndex = mainLayoutSource.indexOf("<Header");

    expect(sidebarIndex).toBeGreaterThanOrEqual(0);
    expect(contentLayoutIndex).toBeGreaterThan(sidebarIndex);
    expect(headerIndex).toBeGreaterThan(contentLayoutIndex);
    expect(stylesSource).toContain(".mainContentLayout {");
    expect(stylesSource).toContain("height: 100vh !important;");
  });

  it("bounds non-chat shortcuts to roughly five rows", () => {
    const ruleStart = stylesSource.indexOf(".navigationScroll {");
    const rule = stylesSource.slice(
      ruleStart,
      stylesSource.indexOf("\n}", ruleStart) + 2,
    );

    expect(ruleStart).toBeGreaterThanOrEqual(0);
    expect(rule).toContain("max-height: min(198px, 30vh);");
    expect(rule).toContain("overflow-y: auto;");
    expect(rule).toContain("overscroll-behavior: contain;");
    expect(rule).toContain("> .navigationItem {");
    expect(rule).toContain("flex: 0 0 36px;");
  });

  it("keeps a visible thin scrollbar as an overflow affordance", () => {
    const ruleStart = stylesSource.indexOf(".navigationScroll {");
    const rule = stylesSource.slice(
      ruleStart,
      stylesSource.indexOf(".inboxItem {", ruleStart),
    );

    expect(rule).toContain("scrollbar-width: thin;");
    expect(rule).toContain("&::-webkit-scrollbar");
    expect(rule).toContain("width: 4px;");
    expect(rule).not.toContain("display: none;");
  });

  it("does not retain the old disclosure control", () => {
    expect(sidebarSource).not.toContain("sidebar.expandShortcuts");
    expect(sidebarSource).not.toContain("sidebar.collapseShortcuts");
  });

  it("renders inbox and all other shortcuts in one scroll region", () => {
    const scrollStart = sidebarSource.indexOf("ref={navScrollRef}");
    const scrollRegion = sidebarSource.slice(
      scrollStart,
      sidebarSource.indexOf("{/* Session list", scrollStart),
    );

    expect(scrollStart).toBeGreaterThanOrEqual(0);
    expect(scrollRegion).toContain("inboxEntry &&");
    expect(scrollRegion).toContain("visibleSidebarNav.map(renderNavItem)");
  });

  it("pins the expanded new-task button directly above inbox shortcuts", () => {
    const taskStart = sidebarSource.indexOf("className={styles.newTask}");
    const scrollStart = sidebarSource.indexOf("ref={navScrollRef}");
    const inboxStart = sidebarSource.indexOf("inboxEntry &&", scrollStart);

    expect(taskStart).toBeGreaterThanOrEqual(0);
    expect(taskStart).toBeLessThan(scrollStart);
    expect(scrollStart).toBeLessThan(inboxStart);
    expect(sidebarSource.slice(taskStart, scrollStart)).toContain(
      't("chat.newTask", "New task")',
    );
    expect(stylesSource).toContain(".newTask");
  });

  it("pins more settings below shortcuts and preserves the return path", () => {
    const scrollStart = sidebarSource.indexOf("ref={navScrollRef}");
    const moreSettingsStart = sidebarSource.indexOf(
      "className={styles.moreSettings}",
    );
    const sessionsStart = sidebarSource.indexOf("{/* Session list");

    expect(scrollStart).toBeGreaterThanOrEqual(0);
    expect(moreSettingsStart).toBeGreaterThan(scrollStart);
    expect(moreSettingsStart).toBeLessThan(sessionsStart);
    expect(sidebarSource).toContain('t("nav.moreSettings", "More settings")');
    expect(sidebarSource).toContain('navigate("/settings/general"');
    expect(sidebarSource).toContain("settingsReturnTo:");
    expect(stylesSource).toContain(".moreSettings");
  });

  it("separates conversation history from the shortcut panel", () => {
    const historyAreaStart = stylesSource.indexOf(".sessionArea {");
    const historyAreaRule = stylesSource.slice(
      historyAreaStart,
      stylesSource.indexOf("\n}", historyAreaStart) + 2,
    );

    expect(historyAreaStart).toBeGreaterThanOrEqual(0);
    expect(historyAreaRule).toContain("margin-top: 10px;");
    expect(sidebarSource).toContain("className={styles.sessionArea}");
  });

  it("retains the bottom settings icon in expanded and collapsed modes", () => {
    const bottomControlsStart = sidebarSource.indexOf(
      "className={styles.collapseToggleContainer}",
    );
    const bottomControls = sidebarSource.slice(
      bottomControlsStart,
      sidebarSource.indexOf("<Modal", bottomControlsStart),
    );

    expect(bottomControlsStart).toBeGreaterThanOrEqual(0);
    expect(bottomControls).toContain("<Settings size={18} />");
    expect(bottomControls).toContain("<SidebarSettingsPanel");
    expect(bottomControls).toContain("onOpenSettings={handleOpenSettings}");
    expect(bottomControls).toContain("className={styles.sidebarUser}");
    expect(bottomControls).toContain("authEnabled={authEnabled}");
    expect(bottomControls).toContain("onOpenAccount={handleOpenAccount}");
    expect(bottomControls).toContain("onLogout={handleLogout}");
    expect(bottomControls).toContain("open={settingsOpen}");
    expect(bottomControls).toContain("destroyOnHidden");
    expect(bottomControls).not.toContain("{collapsed && (");
  });

  it("removes the prefixed popover shell around quick settings", () => {
    const popoverStart = stylesSource.indexOf(".quickSettingsPopover {");
    const popoverRule = stylesSource.slice(
      popoverStart,
      stylesSource.indexOf(".collapsedHistoryPopover", popoverStart),
    );

    expect(popoverRule).toContain(":global(.qwenpaw-popover-inner)");
    expect(popoverRule).toContain("padding: 0 !important;");
    expect(popoverRule).toContain("background: transparent !important;");
    expect(popoverRule).toContain("box-shadow: none;");
  });

  it("pins new task and history outside the shortcut scroller", () => {
    const pinnedStart = sidebarSource.indexOf(
      "className={styles.collapsedNavPinned}",
    );
    const scrollStart = sidebarSource.indexOf(
      "className={styles.collapsedNavScroll}",
    );
    const pinnedRegion = sidebarSource.slice(pinnedStart, scrollStart);

    expect(pinnedStart).toBeGreaterThanOrEqual(0);
    expect(pinnedRegion).toContain('chat.newTask", "New task');
    expect(pinnedRegion).toContain("onClick={handleNewChat}");
    expect(pinnedRegion).toContain("<SparkNewChatLine size={18} />");
    expect(pinnedRegion).toContain("chat.chatHistoryTooltip");
    expect(pinnedRegion).toContain("open={historyPopoverOpen}");
    expect(pinnedRegion).toContain("<SidebarSessionList");
    expect(pinnedRegion).toContain("<History size={18} />");
    expect(pinnedRegion).toContain("open={agentPopoverOpen}");
    expect(pinnedRegion).toContain("<SparkAgentLine size={18} />");
  });

  it("removes the standalone chat navigation entry", () => {
    expect(sidebarSource).not.toContain('t("nav.chat")');
  });

  it("uses a recent-style history header with compact actions", () => {
    expect(sessionListSource).toContain("<SparkNewChatLine size={18} />");
    expect(sessionListSource).toContain("<Ellipsis size={16} />");
    expect(sessionListSource).toContain('key: "search"');
    expect(sessionListSource).toContain('key: "create-group"');
    expect(sessionListSource).toContain("setHistoryCollapsed(false)");
    expect(sessionListSource).toContain("searchInputRef.current?.focus()");
    expect(sessionListSource).toContain("groupInputRef.current?.focus()");
    expect(sessionListSource).not.toContain("styles.newChatBtn");
    expect(sessionListSource).not.toContain("styles.createGroupBtn");
    expect(sessionListStylesSource).toContain(".historyActions");
    expect(sessionListStylesSource).toContain(".historyAction");
    expect(sessionListStylesSource).not.toContain(".newChatBtn");
    expect(sessionListStylesSource).not.toContain(".createGroupBtn");
  });

  it("keeps history actions visible in dark mode", () => {
    const darkStart = sessionListStylesSource.indexOf(":global(.dark-mode)");
    const darkRule = sessionListStylesSource.slice(
      darkStart,
      sessionListStylesSource.indexOf(
        "/* ── Collapsible history header",
        darkStart,
      ),
    );

    expect(darkRule).toContain(".historyAction");
    expect(darkRule).toContain("color: rgba(255, 255, 255, 0.68);");
    expect(darkRule).toContain("background: rgba(255, 255, 255, 0.08);");
  });
});
