import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";
import type { ProviderInfo } from "@/api/types";

import { providerApi } from "@/api/modules/provider";
import {
  buildEligibleProviders,
  type EligibleProvider,
} from "./modelSelectorModels";

/** A picker and its label share the same catalog, including refreshes. */
export function useProviderCatalog(enabled: boolean) {
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const cached = useRef<ProviderInfo[] | null>(null);
  const pending = useRef<Promise<ProviderInfo[]> | null>(null);
  const update = useCallback((value: SetStateAction<ProviderInfo[]>) => {
    const list =
      typeof value === "function" ? value(cached.current ?? []) : value;
    cached.current = list;
    setProviders(list);
  }, []);
  const load = useCallback(
    (refresh = false): Promise<ProviderInfo[]> => {
      if (!refresh && cached.current !== null)
        return Promise.resolve(cached.current);
      if (pending.current) return pending.current;
      pending.current = providerApi
        .listProviders()
        .then((list) => {
          update(list);
          return list;
        })
        .finally(() => {
          pending.current = null;
        });
      return pending.current;
    },
    [update],
  );
  useEffect(() => {
    if (enabled) void load().catch(() => setProviders([]));
  }, [enabled, load]);
  return { providers, load, setProviders: update };
}

export type ProviderCatalog = ReturnType<typeof useProviderCatalog>;

/** The providers and models a slot can be set to. */
export function useEligibleProviders(
  enabled: boolean,
): EligibleProvider[] | null {
  const { providers } = useProviderCatalog(enabled);
  return providers === null ? null : buildEligibleProviders(providers);
}
