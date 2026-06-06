import { useCallback, useEffect, useState } from "react";
import { planApi } from "../../../api/modules/plan";

export function usePlanConfig(selectedAgent: string) {
  const [planEnabled, setPlanEnabled] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      const config = await planApi.getPlanConfig();
      setPlanEnabled(config.enabled);
    } catch {
      setPlanEnabled(false);
    }
  }, [selectedAgent]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return { planEnabled };
}
