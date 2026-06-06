import { useCallback, useEffect, useState } from "react";
import { providerApi } from "../../../api/modules/provider";

export function useModelCheck(selectedAgent: string) {
  const [showPrompt, setShowPrompt] = useState(false);

  const checkModel = useCallback(async () => {
    try {
      const activeModels = await providerApi.getActiveModels({
        scope: "effective",
        agent_id: selectedAgent,
      });
      if (
        !activeModels?.active_llm?.provider_id ||
        !activeModels?.active_llm?.model
      ) {
        setShowPrompt(true);
      }
    } catch {
      setShowPrompt(true);
    }
  }, [selectedAgent]);

  useEffect(() => {
    checkModel();
  }, [checkModel]);

  return { showPrompt, setShowPrompt };
}
