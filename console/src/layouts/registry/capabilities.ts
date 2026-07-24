import type { MenuItem } from "../../plugins/registry/types";

interface AgentMenuCapabilities {
  workspace_ui?: boolean;
  native_skills_ui?: boolean;
  native_tools_ui?: boolean;
  native_mcp_ui?: boolean;
  qwenpaw_skills_projection?: boolean;
  qwenpaw_mcp_projection?: boolean;
  provider_skills_discovery?: boolean;
  provider_mcp_discovery?: boolean;
}

type MenuTreeItem = MenuItem & { __children?: MenuItem[] };

const NATIVE_WORKSPACE_MENU_IDS = new Set([
  "core.workspace",
  "core.acp",
  "core.agent-config",
  "core.agent-stats",
]);

export function filterMenuForAgentCapabilities(
  items: MenuItem[],
  capabilities: AgentMenuCapabilities | undefined,
): MenuItem[] {
  if (capabilities?.workspace_ui !== false) return items;
  const showSkills = Boolean(
    capabilities.native_skills_ui ||
      capabilities.qwenpaw_skills_projection ||
      capabilities.provider_skills_discovery,
  );
  const showTools = Boolean(capabilities.native_tools_ui);
  const showMcp = Boolean(
    capabilities.native_mcp_ui ||
      capabilities.qwenpaw_mcp_projection ||
      capabilities.provider_mcp_discovery,
  );
  const showAgentGroup = showSkills || showTools || showMcp;

  return items.flatMap((item) => {
    if (NATIVE_WORKSPACE_MENU_IDS.has(item.id)) return [];
    if (item.id === "core.agent-group" && !showAgentGroup) return [];
    if (item.id === "core.skills" && !showSkills) return [];
    if (item.id === "core.tools" && !showTools) return [];
    if (item.id === "core.mcp" && !showMcp) return [];

    const treeItem = item as MenuTreeItem;
    if (!treeItem.__children) return [item];
    return [
      {
        ...treeItem,
        __children: filterMenuForAgentCapabilities(
          treeItem.__children,
          capabilities,
        ),
      },
    ];
  });
}
