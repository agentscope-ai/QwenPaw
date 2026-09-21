import { useEffect, useState } from "react";

import { providerApi } from "@/api/modules/provider";
import {
  buildEligibleProviders,
  type EligibleProvider,
} from "./modelSelectorModels";

/** The providers and models a slot can be set to, fetched once. */
export function useEligibleProviders(
  enabled: boolean,
): EligibleProvider[] | null {
  const [providers, setProviders] = useState<EligibleProvider[] | null>(null);
  useEffect(() => {
    if (!enabled || providers !== null) return;
    let cancelled = false;
    providerApi
      .listProviders()
      .then((list) => {
        if (!cancelled) setProviders(buildEligibleProviders(list));
      })
      .catch(() => {
        if (!cancelled) setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, providers]);
  return providers;
}
