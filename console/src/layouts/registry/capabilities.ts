import type { MenuItem } from "../../plugins/registry/types";

const NATIVE_WORKSPACE_MENU_IDS = new Set([
  "core.agent-group",
  "core.workspace",
  "core.skills",
  "core.tools",
  "core.mcp",
  "core.acp",
  "core.agent-config",
  "core.agent-stats",
]);

export function filterMenuForAgentCapabilities(
  items: MenuItem[],
  capabilities: Record<string, boolean> | undefined,
): MenuItem[] {
  if (capabilities?.workspace_ui !== false) return items;
  return items.filter((item) => !NATIVE_WORKSPACE_MENU_IDS.has(item.id));
}
