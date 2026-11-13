import type { AgentSummary } from "../../api/types/agents";
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
  "core.import",
  "core.acp",
  "core.agent-config",
  "core.agent-stats",
]);

export function getAgentMenuCapabilities(
  agent: AgentSummary | undefined,
): AgentMenuCapabilities | undefined {
  if (!agent) return undefined;
  return {
    ...agent.backend_capabilities,
    workspace_ui:
      agent.backend === "qwenpaw"
        ? agent.backend_capabilities?.workspace_ui ?? true
        : false,
  };
}

export function isAgentMenuItemAvailable(
  id: string,
  capabilities: AgentMenuCapabilities | undefined,
): boolean {
  if (capabilities?.workspace_ui !== false) return true;
  if (NATIVE_WORKSPACE_MENU_IDS.has(id)) return false;
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
  if (id === "core.agent-group") return showSkills || showTools || showMcp;
  if (id === "core.skills") return showSkills;
  if (id === "core.tools") return showTools;
  if (id === "core.mcp") return showMcp;
  return true;
}

export function filterMenuForAgentCapabilities(
  items: MenuItem[],
  capabilities: AgentMenuCapabilities | undefined,
): MenuItem[] {
  if (capabilities?.workspace_ui !== false) return items;
  return items.flatMap((item) => {
    if (!isAgentMenuItemAvailable(item.id, capabilities)) return [];

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
