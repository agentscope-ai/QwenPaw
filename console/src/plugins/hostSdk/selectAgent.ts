import { agentsApi } from "../../api/modules/agents";
import { useAgentStore } from "../../stores/agentStore";

let selection = 0;

/** Verify the authenticated host list before using the normal Agent switch. */
export async function selectAgent(agentId: string): Promise<void> {
  if (!agentId) throw new Error("An Agent is required");
  const request = ++selection;
  const previous = useAgentStore.getState().selectedAgent;
  let changed = false;
  const unsubscribe = useAgentStore.subscribe((state, before) => {
    if (state.selectedAgent !== before.selectedAgent) changed = true;
  });
  try {
    const { agents } = await agentsApi.listAgents();
    if (
      !agents.some(
        (agent) =>
          agent.id === agentId &&
          agent.enabled &&
          agent.available_in_chat !== false,
      )
    ) {
      throw new Error("Agent is unavailable for selection");
    }
    const store = useAgentStore.getState();
    if (request !== selection || changed || store.selectedAgent !== previous) {
      throw new Error("Agent selection changed while checking access");
    }
    store.setAgents(agents);
    store.setSelectedAgent(agentId);
  } finally {
    unsubscribe();
  }
}
