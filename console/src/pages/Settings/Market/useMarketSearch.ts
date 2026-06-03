import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { marketApi } from "../../../api/modules/market";
import type {
  MarketProviderInfo,
  MarketResult,
  MarketSearchError,
  MarketSearchResponse,
} from "../../../api/modules/market";

const DEBOUNCE_MS = 350;
const PER_PROVIDER_LIMIT = 10;

export interface MarketSearchState {
  providers: MarketProviderInfo[];
  selectedProviderKeys: Set<string>;
  toggleProvider: (key: string) => void;
  query: string;
  setQuery: (q: string) => void;
  results: MarketResult[];
  errors: MarketSearchError[];
  globalError: string | null;
  loading: boolean;
  hasMore: boolean;
  loadMore: () => void;
  retry: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useMarketSearch(): MarketSearchState {
  const { i18n } = useTranslation();
  const lang = i18n.language || "en";
  const [providers, setProviders] = useState<MarketProviderInfo[]>([]);
  const [selectedProviderKeys, setSelectedProviderKeys] = useState<Set<string>>(
    new Set(),
  );
  const [query, setQueryState] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [results, setResults] = useState<MarketResult[]>([]);
  const [errors, setErrors] = useState<MarketSearchError[]>([]);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // null = exhausted; number = next page to request.
  const cursorsRef = useRef<Record<string, number | null>>({});
  const [hasMore, setHasMore] = useState(false);
  const requestSeqRef = useRef(0);

  const providerKeyList = useMemo(
    () => Array.from(selectedProviderKeys).sort(),
    [selectedProviderKeys],
  );

  const providersSeqRef = useRef(0);
  const fetchProviders = useCallback(() => {
    const seq = ++providersSeqRef.current;
    setGlobalError(null);
    setLoading(true);
    marketApi
      .listMarketProviders()
      .then((list) => {
        if (seq !== providersSeqRef.current) return;
        setProviders(list);
        const enabled = list.filter((p) => p.available).map((p) => p.key);
        setSelectedProviderKeys(new Set(enabled));
      })
      .catch((err: unknown) => {
        if (seq !== providersSeqRef.current) return;
        setProviders([]);
        setGlobalError(errorMessage(err));
      })
      .finally(() => {
        if (seq === providersSeqRef.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const toggleProvider = useCallback((key: string) => {
    setSelectedProviderKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const applyResponse = useCallback(
    (resp: MarketSearchResponse, append: boolean) => {
      const cursors = cursorsRef.current;
      for (const [key, info] of Object.entries(resp.by_provider)) {
        const current = cursors[key];
        if (typeof current === "number") {
          cursors[key] = info.has_more ? current + 1 : null;
        }
      }
      setResults((prev) =>
        append ? [...prev, ...resp.results] : resp.results,
      );
      setErrors(resp.errors);
      setHasMore(Object.values(cursors).some((v) => v !== null));
    },
    [],
  );

  const runFetch = useCallback(
    (
      q: string,
      pages: Record<string, number>,
      append: boolean,
      lng: string,
    ) => {
      const seq = ++requestSeqRef.current;
      // No providers / no query → empty search state, but preserve
      // globalError so a failed provider list keeps surfacing.
      if (!q.trim() || Object.keys(pages).length === 0) {
        setResults([]);
        setErrors([]);
        setHasMore(false);
        setLoading(false);
        return;
      }
      setLoading(true);
      setGlobalError(null);
      marketApi
        .searchMarket({
          query: q.trim(),
          provider_pages: pages,
          limit: PER_PROVIDER_LIMIT,
          lang: lng,
        })
        .then((resp) => {
          if (seq !== requestSeqRef.current) return;
          applyResponse(resp, append);
        })
        .catch((err: unknown) => {
          if (seq !== requestSeqRef.current) return;
          setGlobalError(errorMessage(err));
          if (!append) {
            setResults([]);
            setHasMore(false);
          }
        })
        .finally(() => {
          if (seq === requestSeqRef.current) setLoading(false);
        });
    },
    [applyResponse],
  );

  const loadMore = useCallback(() => {
    const pages: Record<string, number> = {};
    for (const [key, cursor] of Object.entries(cursorsRef.current)) {
      if (typeof cursor === "number") pages[key] = cursor;
    }
    if (Object.keys(pages).length === 0) return;
    runFetch(debouncedQuery, pages, true, lang);
  }, [debouncedQuery, lang, runFetch]);

  const retry = useCallback(() => {
    if (providers.length === 0) {
      fetchProviders();
    } else {
      loadMore();
    }
  }, [providers.length, fetchProviders, loadMore]);

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  // Reset cursors + refetch on (query / providers / lang) change.
  const lastKeyRef = useRef("");
  useEffect(() => {
    const key = `${debouncedQuery}|${providerKeyList.join(",")}|${lang}`;
    if (lastKeyRef.current === key) return;
    lastKeyRef.current = key;
    const initialPages: Record<string, number> = {};
    const nextCursors: Record<string, number | null> = {};
    for (const k of providerKeyList) {
      initialPages[k] = 1;
      nextCursors[k] = 1;
    }
    cursorsRef.current = nextCursors;
    runFetch(debouncedQuery, initialPages, false, lang);
  }, [debouncedQuery, providerKeyList, lang, runFetch]);

  return {
    providers,
    selectedProviderKeys,
    toggleProvider,
    query,
    setQuery,
    results,
    errors,
    globalError,
    loading,
    hasMore,
    loadMore,
    retry,
  };
}
