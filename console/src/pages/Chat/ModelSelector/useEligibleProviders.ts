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
  const publish = useCallback((list: ProviderInfo[]) => {
    cached.current = list;
    setProviders(list);
  }, []);
  const update = useCallback(
    (value: SetStateAction<ProviderInfo[]>) => {
      pending.current = null;
      publish(
        typeof value === "function" ? value(cached.current ?? []) : value,
      );
    },
    [publish],
  );
  const load = useCallback(
    (refresh = false): Promise<ProviderInfo[]> => {
      if (!refresh && pending.current) return pending.current;
      if (!refresh && cached.current !== null)
        return Promise.resolve(cached.current);
      const request = providerApi
        .listProviders()
        .then((list) => {
          if (pending.current === request) publish(list);
          return list;
        })
        .catch((error) => {
          if (pending.current === request && cached.current === null)
            setProviders([]);
          throw error;
        })
        .finally(() => {
          if (pending.current === request) pending.current = null;
        });
      pending.current = request;
      return request;
    },
    [publish],
  );
  useEffect(() => {
    if (enabled) void load().catch(() => {});
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
