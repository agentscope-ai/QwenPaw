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
const sessionListSource = readFileSync(
  join(process.cwd(), "src/layouts/SidebarSessionList.tsx"),
  "utf8",
);
const sessionListStylesSource = readFileSync(
  join(process.cwd(), "src/layouts/sidebarSessionList.module.less"),
  "utf8",
);

describe("Sidebar overflow layout", () => {
  it("bounds non-chat shortcuts to roughly five rows", () => {
    const ruleStart = stylesSource.indexOf(".simpleNavScroll {");
    const rule = stylesSource.slice(
      ruleStart,
      stylesSource.indexOf("\n}", ruleStart) + 2,
    );

    expect(ruleStart).toBeGreaterThanOrEqual(0);
    expect(rule).toContain("max-height: min(198px, 30vh);");
    expect(rule).toContain("overflow-y: auto;");
    expect(rule).toContain("overscroll-behavior: contain;");
    expect(rule).toContain("> .simpleNavItem {");
    expect(rule).toContain("flex: 0 0 36px;");
  });

  it("keeps a visible thin scrollbar as an overflow affordance", () => {
    const ruleStart = stylesSource.indexOf(".simpleNavScroll {");
    const rule = stylesSource.slice(
      ruleStart,
      stylesSource.indexOf(".simpleAgentFunctionsMotion {", ruleStart),
    );

    expect(rule).toContain("scrollbar-width: thin;");
    expect(rule).toContain("&::-webkit-scrollbar");
    expect(rule).toContain("width: 4px;");
    expect(rule).not.toContain("display: none;");
  });

  it("does not retain the old disclosure control", () => {
    expect(stylesSource).not.toContain(".simpleAgentDisclosure");
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
    expect(scrollRegion).toContain("simpleInboxEntry &&");
    expect(scrollRegion).toContain(
      "visibleSidebarNav.map(renderSimpleNavItem)",
    );
  });

  it("pins the expanded new-task button directly above inbox shortcuts", () => {
    const taskStart = sidebarSource.indexOf("className={styles.simpleNewTask}");
    const scrollStart = sidebarSource.indexOf("ref={navScrollRef}");
    const inboxStart = sidebarSource.indexOf(
      "simpleInboxEntry &&",
      scrollStart,
    );

    expect(taskStart).toBeGreaterThanOrEqual(0);
    expect(taskStart).toBeLessThan(scrollStart);
    expect(scrollStart).toBeLessThan(inboxStart);
    expect(sidebarSource.slice(taskStart, scrollStart)).toContain(
      't("chat.newTask", "New task")',
    );
    expect(stylesSource).toContain(".simpleNewTask");
  });

  it("pins more settings below shortcuts and preserves the return path", () => {
    const scrollStart = sidebarSource.indexOf("ref={navScrollRef}");
    const moreSettingsStart = sidebarSource.indexOf(
      "className={styles.simpleMoreSettings}",
    );
    const sessionsStart = sidebarSource.indexOf("{/* Session list");

    expect(scrollStart).toBeGreaterThanOrEqual(0);
    expect(moreSettingsStart).toBeGreaterThan(scrollStart);
    expect(moreSettingsStart).toBeLessThan(sessionsStart);
    expect(sidebarSource).toContain('t("nav.moreSettings", "More settings")');
    expect(sidebarSource).toContain('navigate("/settings/general"');
    expect(sidebarSource).toContain("settingsReturnTo:");
    expect(stylesSource).toContain(".simpleMoreSettings");
  });

  it("separates conversation history from the shortcut panel", () => {
    const historyAreaStart = stylesSource.indexOf(".simpleSessionArea {");
    const historyAreaRule = stylesSource.slice(
      historyAreaStart,
      stylesSource.indexOf("\n}", historyAreaStart) + 2,
    );

    expect(historyAreaStart).toBeGreaterThanOrEqual(0);
    expect(historyAreaRule).toContain("margin-top: 10px;");
    expect(sidebarSource).toContain("className={styles.simpleSessionArea}");
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
    expect(bottomControls).toContain("open={settingsOpen}");
    expect(bottomControls).toContain("destroyOnHidden");
    expect(bottomControls).not.toContain("{collapsed && (");
  });

  it("removes the prefixed popover shell around quick settings", () => {
    const popoverStart = stylesSource.indexOf(".quickSettingsPopover {");
    const popoverRule = stylesSource.slice(
      popoverStart,
      stylesSource.indexOf(".modeToggleActive", popoverStart),
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
    expect(pinnedRegion).toContain("<SquarePen size={18} />");
    expect(pinnedRegion).toContain("chat.chatHistoryTooltip");
    expect(pinnedRegion).toContain("onClick={() => setCollapsed(false)}");
    expect(pinnedRegion).not.toContain("requestSessionHistoryDrawerOpen()");
    expect(pinnedRegion).toContain("<History size={18} />");
  });

  it("removes the standalone chat navigation entry", () => {
    expect(sidebarSource).not.toContain('t("nav.chat")');
    expect(stylesSource).not.toContain(".simpleChatItem");
    expect(stylesSource).not.toContain(".simpleNewChat");
  });

  it("uses a recent-style history header with compact actions", () => {
    expect(sessionListSource).toContain("<SquarePen size={15} />");
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
});
