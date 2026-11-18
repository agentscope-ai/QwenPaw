import { useMemo } from "react";

import { flattenMenu } from "@/layouts/registry/adapter";
import {
  filterMenuForAgentCapabilities,
  getAgentMenuCapabilities,
} from "@/layouts/registry/capabilities";
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
    const capabilities = getAgentMenuCapabilities(currentAgent);
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
