import { useMemo } from "react";

import { flattenMenu } from "@/layouts/registry/adapter";
import { filterMenuForAgentCapabilities } from "@/layouts/registry/capabilities";
import { partitionSidebarEntries } from "@/layouts/registry/sidebarEntries";
import { useMenuItems, useRoutes } from "@/plugins/registry/hooks";
import { useAgentStore } from "@/stores/agentStore";

export function useSidebarEntryGroups() {
  const routes = useRoutes();
  const rawAgentMenu = useMenuItems("primary.agentScoped");
  const rawSettingsMenu = useMenuItems("primary.settings");
  const { selectedAgent, agents } = useAgentStore();
  const currentAgent = agents.find((agent) => agent.id === selectedAgent);

  return useMemo(() => {
    const capabilities = currentAgent
      ? {
          ...currentAgent.backend_capabilities,
          workspace_ui:
            currentAgent.backend === "qwenpaw"
              ? currentAgent.backend_capabilities?.workspace_ui ?? true
              : false,
        }
      : undefined;
    return partitionSidebarEntries(
      flattenMenu(
        filterMenuForAgentCapabilities(rawAgentMenu, capabilities),
        routes,
        18,
      ),
      flattenMenu(rawSettingsMenu, routes, 18),
    );
  }, [currentAgent, rawAgentMenu, rawSettingsMenu, routes]);
}
