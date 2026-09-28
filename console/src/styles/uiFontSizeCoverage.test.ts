import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function readSource(path: string): string {
  return readFileSync(join(process.cwd(), path), "utf8");
}

function readRule(source: string, selector: string): string {
  const marker = `${selector} {`;
  const afterNewline = source.indexOf(`\n${marker}`);
  const selectorIndex = source.startsWith(marker)
    ? 0
    : afterNewline >= 0
    ? afterNewline + 1
    : -1;
  if (selectorIndex < 0) return "";

  let depth = 0;
  for (
    let index = source.indexOf("{", selectorIndex);
    index < source.length;
    index += 1
  ) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(selectorIndex, index + 1);
    }
  }
  return "";
}

const previewStyles = readSource("src/pages/Coding/FilePreview.module.less");
const artifactStyles = readSource(
  "src/features/files-workspace/ResponseArtifactList.module.less",
);
const layoutStyles = readSource("src/layouts/index.module.less");
const chatStyles = readSource("src/pages/Chat/index.module.less");
const filesWorkspaceStyles = readSource(
  "src/features/files-workspace/FilesWorkspace.module.less",
);
const sessionItemStyles = readSource(
  "src/components/SessionItem/sessionItem.module.less",
);
const sidebarSessionStyles = readSource(
  "src/layouts/sidebarSessionList.module.less",
);
const sidebarSettingsStyles = readSource(
  "src/layouts/sidebarSettingsPanel.module.less",
);
const loopStyles = readSource("src/components/LoopInput/index.module.less");
const projectDirectoryStyles = readSource(
  "src/features/project-directory/SessionProjectDirectory.module.less",
);
const toolCardStyles = readSource(
  "src/components/Chat/ToolCards/shared/toolCards.module.less",
);
const offloadStyles = readSource(
  "src/components/Chat/ToolCards/shared/offloadBanner.module.less",
);
const loginStyles = readSource("src/pages/Login/index.module.less");
const loginSource = readSource("src/pages/Login/index.tsx");
const tokensSource = readSource("src/styles/tokens.css");
const settingsCenterStyles = readSource(
  "src/pages/SettingsCenter/index.module.less",
);
const generalSettingsSource = readSource(
  "src/pages/SettingsCenter/GeneralSettings.tsx",
);
const hostBubbleStyles = readSource("src/pages/Chat/HostBubbles.module.less");
const approvalStyles = readSource(
  "src/pages/Chat/components/ApprovalToggle.module.less",
);
const harnessModelStyles = readSource(
  "src/pages/Chat/components/HarnessModelSelector.module.less",
);
const agentStatusStyles = readSource(
  "src/components/AgentStatusIndicator/index.module.less",
);
const chatActionStyles = readSource(
  "src/pages/Chat/components/ChatActionGroup/ChatActionGroup.module.less",
);
const modelSelectorStyles = readSource(
  "src/pages/Chat/ModelSelector/index.module.less",
);
const thinkingStyles = readSource("src/features/thinking/thinking.module.less");
const agentConfigStyles = readSource(
  "src/pages/Agent/Config/index.module.less",
);
const modelsStyles = readSource("src/pages/Settings/Models/index.module.less");
const inboxStyles = readSource("src/pages/Inbox/index.module.less");
const pushMessageStyles = readSource(
  "src/pages/Inbox/components/PushMessageCard.module.less",
);
const appCenterStyles = readSource("src/pages/AppCenter/index.module.less");
const channelStyles = readSource(
  "src/pages/Control/Channels/index.module.less",
);
const skillStyles = readSource("src/pages/Agent/Skills/index.module.less");
const toolStyles = readSource("src/pages/Agent/Tools/index.module.less");
const skillPoolStyles = readSource(
  "src/pages/Settings/SkillPool/index.module.less",
);
const mcpStyles = readSource("src/pages/Agent/MCP/index.module.less");
const mcpSource = readSource("src/pages/Agent/MCP/index.tsx");
const tabbedEditorStyles = readSource(
  "src/pages/Coding/TabbedEditor.module.less",
);

describe("console font-size coverage", () => {
  it("uses semantic typography tokens throughout file previews", () => {
    expect(readRule(previewStyles, ".previewStatus")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(previewStyles, ".htmlOpenButton")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(previewStyles, ".markdownWrap")).toContain(
      "font-size: var(--app-font-body)",
    );
    expect(readRule(previewStyles, ".frontmatterKey")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(previewStyles, ".csvNote")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(previewStyles, ".csvTable")).toContain(
      "font-size: var(--app-font-caption)",
    );
  });

  it("scales readable file-card text and lets the card grow", () => {
    const fileRule = readRule(artifactStyles, ".file");
    const detailsRule = readRule(artifactStyles, ".details");

    expect(fileRule).toContain("height: auto");
    expect(fileRule).toContain("var(--app-font-scale)");
    expect(detailsRule).toContain("font-size: var(--app-font-body)");
    expect(detailsRule).toContain("font-size: var(--app-font-caption)");
    expect(readRule(artifactStyles, ".status")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(artifactStyles, ".toggle")).toContain(
      "font-size: var(--app-font-caption)",
    );
  });

  it("scales the more-settings entry and allows its row to grow", () => {
    const rule = readRule(layoutStyles, ".moreSettings");

    expect(rule).toContain("font-size: var(--app-font-secondary)");
    expect(rule).toContain("height: auto");
    expect(rule).toContain("var(--app-font-scale)");
  });

  it("wraps sender actions below the model row when files reduce chat width", () => {
    const marker = ".filesPreviewOpen,";
    const markerIndex = chatStyles.indexOf(marker);
    const rule = chatStyles.slice(
      markerIndex,
      chatStyles.indexOf(".compactSenderAffix", markerIndex),
    );

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toContain('[class$="-sender-content-bottom"]');
    expect(rule).toMatch(/flex-wrap:\s*wrap/);
    expect(rule).toContain('[class$="-sender-prefix"]');
    expect(rule).toContain('[class$="-sender-actions-list"]');
    expect(rule).toMatch(/flex:\s*1 1 100%/);
  });

  it("scales user bubbles and keeps the ordinary sender on one row", () => {
    expect(chatStyles).toContain('[data-role="user"] [class$="-markdown"]');
    expect(chatStyles).toContain("font-size: var(--app-font-body) !important");
    const root = chatStyles.slice(0, chatStyles.indexOf(".filesPreviewOpen"));
    expect(root).toMatch(/-sender-content-bottom[\s\S]*flex-wrap:\s*nowrap/);
    expect(root).toMatch(/-sender-prefix[\s\S]*flex:\s*1 1 auto/);
    expect(root).toContain("> div {\n        flex-wrap: nowrap;");
    expect(root).toMatch(/-sender-actions-list[\s\S]*flex-wrap:\s*nowrap/);
    expect(chatStyles).toContain(".senderProjectControl");
    expect(chatStyles).toContain(".senderApprovalControl");
    expect(chatStyles).toContain("white-space: nowrap !important;");
  });

  it("scales the requested business page typography at its boundaries", () => {
    expect(agentConfigStyles).toContain(
      '@import (reference) "../../../styles/scaledTypography.less"',
    );
    expect(agentConfigStyles).toContain("font-size: var(--app-font-body)");
    expect(modelsStyles).toContain(".scaled-control-typography();");
    expect(inboxStyles).toContain(".scaled-control-typography();");
    expect(pushMessageStyles).toContain(
      "min-height: max(142px, calc(142px * var(--app-font-scale)))",
    );
    expect(appCenterStyles).toContain(".scaled-control-typography();");
  });

  it("scales channel page typography and cards", () => {
    expect(channelStyles).toContain(
      '@import (reference) "../../../styles/scaledTypography.less"',
    );
    const pageRule = readRule(channelStyles, ".channelsPage");
    expect(pageRule).toContain(".scaled-control-typography();");
    expect(pageRule).toContain("font-size: var(--app-font-body)");
    expect(readRule(channelStyles, ".breadcrumbHeader")).toContain(
      "font-size: var(--app-font-subtitle)",
    );
    expect(readRule(channelStyles, ".breadcrumbCurrent")).toContain(
      "font-size: var(--app-font-title)",
    );
    expect(readRule(channelStyles, ".filterTab")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(channelStyles, ".cardTitle")).toContain(
      "font-size: var(--app-font-body)",
    );
    expect(readRule(channelStyles, ".statusText")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(channelStyles, ".channelCard")).toContain(
      "calc(150px * var(--app-font-scale))",
    );
  });

  it("scales skill page typography, controls, and cards", () => {
    expect(skillStyles).toContain(
      '@import (reference) "../../../styles/scaledTypography.less"',
    );
    const pageRule = readRule(skillStyles, ".skillsPage");
    expect(pageRule).toContain(".scaled-control-typography();");
    expect(pageRule).toContain("font-size: var(--app-font-body)");
    expect(readRule(skillStyles, ".skillTitle")).toContain(
      "font-size: var(--app-font-subtitle)",
    );
    expect(readRule(skillStyles, ".descriptionText")).toContain(
      "font-size: var(--app-font-caption)",
    );
    const searchRule = readRule(skillStyles, ".searchInput");
    expect(searchRule).toContain("font-size: var(--app-font-body)");
    expect(searchRule).toContain("height: auto");
    expect(searchRule).toContain("var(--app-font-scale)");
    const actionRule = readRule(skillStyles, ".actionButton");
    expect(actionRule).toContain("font-size: var(--app-font-body)");
    expect(actionRule).toContain("height: auto");
    expect(actionRule).toContain("var(--app-font-scale)");
    expect(readRule(skillStyles, ".viewToggleBtn")).toContain(
      "var(--app-icon-button)",
    );
    expect(readRule(skillStyles, ".skillCard")).toContain(
      "calc(180px * var(--app-font-scale))",
    );
  });

  it("scales tool page typography and controls", () => {
    expect(toolStyles).toContain(
      '@import (reference) "../../../styles/scaledTypography.less"',
    );
    const pageRule = readRule(toolStyles, ".toolsPage");
    expect(pageRule).toContain(".scaled-control-typography();");
    expect(pageRule).toContain("font-size: var(--app-font-body)");
    expect(readRule(toolStyles, ".sectionTitle")).toContain("font-size: 1rem");
    expect(readRule(toolStyles, ".toolName")).toContain("font-size: 0.9375rem");
    expect(readRule(toolStyles, ".description")).toContain(
      "font-size: 0.8125rem",
    );
    expect(readRule(toolStyles, ".toggleButton")).toContain(
      "font-size: 0.8125rem",
    );
  });

  it("scales skill-pool typography, controls, and cards", () => {
    expect(skillPoolStyles).toContain(
      '@import (reference) "../../../styles/scaledTypography.less"',
    );
    const pageRule = readRule(skillPoolStyles, ".skillsPage");
    expect(pageRule).toContain(".scaled-control-typography();");
    expect(pageRule).toContain("font-size: var(--app-font-body)");
    expect(readRule(skillPoolStyles, ".skillTitle")).toContain(
      "font-size: var(--app-font-subtitle)",
    );
    expect(readRule(skillPoolStyles, ".descriptionText")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    const actionRule = readRule(skillPoolStyles, ".actionButton");
    expect(actionRule).toContain("font-size: var(--app-font-body)");
    expect(actionRule).toContain("height: auto");
    expect(actionRule).toContain("var(--app-font-scale)");
    expect(readRule(skillPoolStyles, ".automationButton")).toContain(
      "var(--app-icon-box)",
    );
    expect(readRule(skillPoolStyles, ".skillCard")).toContain(
      "calc(240px * var(--app-font-scale))",
    );
  });

  it("scales MCP page copy, controls, and access dialogs", () => {
    expect(mcpStyles).toContain(
      '@import (reference) "../../../styles/scaledTypography.less"',
    );
    const pageRule = readRule(mcpStyles, ".mcpPage");
    expect(pageRule).toContain(".scaled-control-typography();");
    expect(pageRule).toContain("font-size: var(--app-font-body)");
    expect(readRule(mcpStyles, ".mcpTitle")).toContain(
      "font-size: var(--app-font-body)",
    );
    expect(readRule(mcpStyles, ".mcpDescription")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(mcpStyles, ".typeBadge")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(mcpStyles, ".accessRuleFieldLabel")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(mcpStyles, ".formLabel")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(mcpSource).not.toMatch(/fontSize:\s*\d+/);
    expect(mcpStyles).not.toMatch(/font-size:\s*\d+px/);
  });

  it("scales file navigator tabs, tree rows, and status copy", () => {
    expect(readRule(filesWorkspaceStyles, ".sourceTabs")).toContain(
      "font-size: var(--app-font-caption)",
    );
    const treeRow = readRule(filesWorkspaceStyles, ".treeRow");
    expect(treeRow).toContain("font-size: var(--app-font-body)");
    expect(treeRow).toContain("var(--app-font-scale)");
    expect(readRule(filesWorkspaceStyles, ".loadError")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(filesWorkspaceStyles).not.toMatch(/font-size:\s*\d+px/);
  });

  it("scales coding tabs, file paths, toolbar copy, and text previews", () => {
    expect(readRule(tabbedEditorStyles, ".wrap")).toContain(
      "font-size: var(--app-font-body)",
    );
    expect(readRule(tabbedEditorStyles, ".tab")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(tabbedEditorStyles, ".fileName")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(tabbedEditorStyles, ".textPreview")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(tabbedEditorStyles, ".emptyText")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(tabbedEditorStyles).not.toMatch(/font-size:\s*\d+px/);
    expect(tabbedEditorStyles).not.toMatch(/font:\s*\n\s*\d+px\//);
  });

  it("scales files-workspace labels, actions, and descriptions", () => {
    expect(readRule(filesWorkspaceStyles, ".drawerTitle")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(filesWorkspaceStyles, ".drawerTitle")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(filesWorkspaceStyles).toMatch(
      /\.secondaryButton,\s*\.primaryButton\s*\{[\s\S]*?font-size:\s*var\(--app-font-caption\)/,
    );
    expect(readRule(filesWorkspaceStyles, ".directoryContextLabel")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(
      readRule(filesWorkspaceStyles, ".profilePickerDescription"),
    ).toContain("font-size: var(--app-font-secondary)");
    expect(readRule(filesWorkspaceStyles, ".conflictChoice")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(filesWorkspaceStyles, ".conflictChoice")).toContain(
      "font-size: var(--app-font-caption)",
    );
  });

  it("scales session details and sidebar menus", () => {
    expect(readRule(sessionItemStyles, ".infoTime")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(sessionItemStyles, ".infoRows")).toContain(
      "font-size: var(--app-font-body)",
    );
    expect(readRule(sessionItemStyles, ".renameInput")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(sidebarSessionStyles, ".searchInput")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(sidebarSessionStyles, ".groupInput")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(sidebarSessionStyles, ".groupLabel")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(sidebarSettingsStyles, ".choiceItem")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(sidebarSettingsStyles, ".menuMeta")).toContain(
      "font-size: var(--app-font-caption)",
    );
  });

  it("scales Loop and project-directory popup copy", () => {
    expect(readRule(loopStyles, ".activeState")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(loopStyles, ".menuTitle")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(loopStyles, ".optionDescription")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(projectDirectoryStyles, ".panelHeading")).toContain(
      "font-size: var(--app-font-body)",
    );
    expect(readRule(projectDirectoryStyles, ".inlineHint")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(projectDirectoryStyles, ".headingCount")).toContain(
      "font-size: var(--app-font-caption)",
    );
  });

  it("scales tool-card and offload status copy", () => {
    expect(readRule(toolCardStyles, ".toolCallCompactSummary")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(toolCardStyles, ".defaultBlockTitle")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(toolCardStyles, ".defaultBlockContent")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(offloadStyles, ".offloadInfo")).toContain(
      "font-size: var(--app-font-caption)",
    );
    expect(readRule(offloadStyles, ".offloadNote")).toContain(
      "font-size: var(--app-font-caption)",
    );
  });

  it("keeps login typography in CSS semantic tokens", () => {
    expect(loginSource).not.toMatch(/fontSize:\s*(13|20)/);
    expect(readRule(loginStyles, ".loginTitle")).toContain(
      "font-size: var(--app-font-title)",
    );
    expect(readRule(loginStyles, ".loginHint")).toContain(
      "font-size: var(--app-font-secondary)",
    );
    expect(readRule(loginStyles, ".termsScroll")).toContain(
      "font-size: var(--app-font-secondary)",
    );
  });

  it("defines icon and icon-button tokens from the shared font scale", () => {
    for (const token of [
      "--app-icon-xs",
      "--app-icon-sm",
      "--app-icon-md",
      "--app-icon-lg",
      "--app-icon-box",
      "--app-icon-button",
    ]) {
      expect(tokensSource).toContain(`${token}:`);
    }
    expect(tokensSource).toMatch(
      /--app-icon-lg:\s*calc\(18px \* var\(--app-font-scale\)\)/,
    );
  });

  it("scales sidebar icons and icon-only controls with their labels", () => {
    const newTaskRule = readRule(layoutStyles, ".newTask");
    expect(newTaskRule).toContain("width: var(--app-icon-lg)");
    expect(newTaskRule).toContain("height: var(--app-icon-lg)");
    expect(newTaskRule).toContain("font-size: var(--app-icon-lg)");

    for (const selector of [".navigationItem", ".moreSettings"]) {
      const rule = readRule(layoutStyles, selector);
      expect(rule).toContain("width: var(--app-icon-md)");
      expect(rule).toContain("height: var(--app-icon-md)");
    }
    const collapsedRule = readRule(layoutStyles, ".collapsedNavItem");
    expect(collapsedRule).toContain("var(--app-icon-button)");
    expect(collapsedRule).toContain("width: var(--app-icon-lg)");
    expect(collapsedRule).toContain("font-size: var(--app-icon-lg)");
  });

  it("scales settings icons and omits a font-size reset action", () => {
    const iconRule = readRule(settingsCenterStyles, ".settingIcon");
    expect(iconRule).toContain("width: var(--app-icon-box)");
    expect(iconRule).toContain("height: var(--app-icon-box)");
    expect(iconRule).toContain("width: var(--app-icon-lg)");

    expect(generalSettingsSource).not.toContain("fontSizeReset");
    expect(generalSettingsSource).not.toContain("UI_FONT_SIZE_DEFAULT");
    expect(settingsCenterStyles).not.toContain(".fontSizeReset");
  });

  it("scales sender control icons and their hit areas", () => {
    const approvalTrigger = readRule(approvalStyles, ".trigger");
    expect(approvalTrigger).toContain("var(--app-icon-button)");
    expect(approvalTrigger).toContain("width: var(--app-icon-xs)");
    expect(readRule(approvalStyles, ".optionIcon")).toContain(
      "width: var(--app-icon-box)",
    );

    const harnessTrigger = readRule(harnessModelStyles, ".trigger");
    expect(harnessTrigger).toContain("var(--app-icon-button)");
    expect(harnessTrigger).toContain("width: var(--app-icon-sm)");

    expect(readRule(loopStyles, ".activeMode")).toContain(
      "width: var(--app-icon-sm)",
    );
    expect(readRule(loopStyles, ".settingsButton")).toContain(
      "var(--app-icon-button)",
    );
    expect(readRule(projectDirectoryStyles, ".trigger")).toContain(
      "width: var(--app-icon-sm)",
    );
  });

  it("scales collapsed-step text, status icon, arrow, and header height", () => {
    const rule = readRule(hostBubbleStyles, ".collapsedSteps");

    expect(rule).toContain("font-size: var(--app-font-caption)");
    expect(rule).toContain("min-height: var(--app-icon-button)");
    expect(rule).toContain("width: var(--app-icon-md)");
    expect(rule).toContain("width: 1em");
    expect(rule).toContain("font-size: var(--app-icon-sm)");
    expect(rule).toContain("[data-spark-icon]");
    expect(rule).toContain("transform: none");
  });

  it("keeps the model picker inside its flex anchor without covering counters", () => {
    const anchorRule = readRule(modelSelectorStyles, ".pickerAnchor");
    const triggerRule = readRule(thinkingStyles, ".trigger");

    expect(anchorRule).toContain("flex: 0 1 auto");
    expect(anchorRule).toContain("overflow: hidden");
    expect(anchorRule).toContain("max-width: 100%");
    expect(anchorRule).toContain("> *");
    expect(triggerRule).toContain("max-width: 100%");
    expect(triggerRule).toContain("min-width: 0");
    expect(triggerRule).toContain("flex: 1 1 auto");
    expect(chatStyles).toMatch(
      /\[class\$="-sender-actions-list-length"\][\s\S]*?flex:\s*0 0 auto/,
    );
  });

  it("scales status marks and chat icon buttons", () => {
    const indicatorRule = readRule(agentStatusStyles, ".indicator");
    expect(indicatorRule).toContain("calc(8px * var(--app-font-scale))");

    const workspaceButtonRule = readRule(chatActionStyles, ".workspaceButton");
    expect(workspaceButtonRule).toContain("var(--app-icon-button)");
    expect(workspaceButtonRule).toContain("var(--app-icon-md)");
    expect(workspaceButtonRule).toContain("font-size: var(--app-icon-md)");

    expect(chatStyles).toContain('[class$="-bubble-footer-actions-item"]');
    expect(chatStyles).toContain("min-width: var(--app-icon-button)");
    expect(chatStyles).toContain("width: var(--app-icon-md)");
    expect(chatStyles).toContain("[data-spark-icon]");
  });
});
