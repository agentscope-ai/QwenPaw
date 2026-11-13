import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { marketApi } from "../../../api/modules/market";
import { subscribeToPluginChanges } from "../../../utils/pluginChangeEvents";
import type {
  MarketCategory,
  MarketProviderInfo,
  MarketResult,
  MarketSearchError,
  MarketSearchResponse,
} from "../../../api/modules/market";

const DEBOUNCE_MS = 350;
const PER_PROVIDER_LIMIT = 10;
const PROVIDERS_STORAGE_KEY = "qwenpaw-market-providers";

/** Restore the persisted provider selection */
const resolveInitialProviders = (): Set<string> => {
  try {
    const raw = localStorage.getItem(PROVIDERS_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? new Set(parsed.filter((x): x is string => typeof x === "string"))
      : new Set();
  } catch {
    return new Set();
  }
};

export interface MarketSearchState {
  providers: MarketProviderInfo[];
  providersLoaded: boolean;
  selectedProviderKeys: Set<string>;
  setSelectedProviders: (keys: string[]) => void;
  categories: MarketCategory[];
  category: string;
  setCategory: (id: string) => void;
  query: string;
  setQuery: (q: string) => void;
  results: MarketResult[];
  errors: MarketSearchError[];
  globalError: string | null;
  loading: boolean;
  /** Sum of provider-reported totals for the current query. */
  totalCount: number;
  hasMore: boolean;
  loadMore: () => void;
  /** Sentinel-driven load; no-op while loading or blocked. */
  autoLoadMore: () => void;
  /** Set when a batch errored, so the sentinel stops auto-retrying. */
  autoLoadBlocked: boolean;
  refresh: () => void;
  retry: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useMarketSearch(): MarketSearchState {
  const { i18n } = useTranslation();
  const lang = i18n.language || "en";
  const [providers, setProviders] = useState<MarketProviderInfo[]>([]);
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [providersLoading, setProvidersLoading] = useState(true);
  const providersRef = useRef<MarketProviderInfo[] | null>(null);
  const [catalogVersion, setCatalogVersion] = useState(0);
  const [selectedProviderKeys, setSelectedProviderKeys] = useState<Set<string>>(
    resolveInitialProviders,
  );
  const [categories, setCategories] = useState<MarketCategory[]>([]);
  const [category, setCategoryState] = useState("");
  const [query, setQueryState] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [results, setResults] = useState<MarketResult[]>([]);
  const [errors, setErrors] = useState<MarketSearchError[]>([]);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Mirrors `loading` so sentinel callbacks read the latest value.
  const loadingRef = useRef(false);
  const [autoLoadBlocked, setAutoLoadBlockedState] = useState(false);
  const autoLoadBlockedRef = useRef(false);
  // null = exhausted; number = next page to request.
  const cursorsRef = useRef<Record<string, number | null>>({});
  const totalsRef = useRef<Record<string, number>>({});
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const requestSeqRef = useRef(0);

  const setAutoLoadBlocked = useCallback((blocked: boolean) => {
    autoLoadBlockedRef.current = blocked;
    setAutoLoadBlockedState(blocked);
  }, []);

  // Keep server-provided provider order (QwenPaw first) for ranking.
  const providerKeyList = useMemo(() => {
    if (!providersLoaded) return [];
    return providers
      .filter((p) => p.available && selectedProviderKeys.has(p.key))
      .map((p) => p.key);
  }, [providers, providersLoaded, selectedProviderKeys]);

  const hadAvailableProviders = useRef(false);

  // Reconcile plugin changes without overriding explicit deselection.
  useEffect(() => {
    if (!providersLoaded) return;
    const enabled = providers.filter((p) => p.available).map((p) => p.key);
    const keepEmptySelection = hadAvailableProviders.current;
    hadAvailableProviders.current = enabled.length > 0;
    setSelectedProviderKeys((prev) => {
      if (prev.size === 0 && keepEmptySelection) return prev;
      const valid = [...prev].filter((key) => enabled.includes(key));
      if (valid.length === prev.size && valid.length > 0) return prev;
      if (valid.length > 0) return new Set(valid);
      const fallback = enabled.includes("qwenpaw")
        ? ["qwenpaw"]
        : enabled.slice(0, 1);
      return new Set(fallback);
    });
  }, [providers, providersLoaded]);

  const providersSeqRef = useRef(0);
  const providersRequestRef = useRef(false);
  const fetchProviders = useCallback((forceRefresh = false) => {
    if (!forceRefresh && providersRequestRef.current) return;
    providersRequestRef.current = true;
    const seq = ++providersSeqRef.current;
    const foreground = forceRefresh || providersRef.current === null;
    if (foreground) {
      ++requestSeqRef.current;
      setGlobalError(null);
      setProvidersLoading(true);
    }
    marketApi
      .listMarketProviders()
      .then((list) => {
        if (seq !== providersSeqRef.current) return;
        const changed =
          JSON.stringify(list) !== JSON.stringify(providersRef.current);
        if (changed || forceRefresh) {
          ++requestSeqRef.current;
          setCatalogVersion((version) => version + 1);
        }
        if (changed) {
          providersRef.current = list;
          setProviders(list);
        }
        setProvidersLoaded(true);
      })
      .catch((err: unknown) => {
        if (seq !== providersSeqRef.current) return;
        // A background catalog check must not discard the current search.
        if (!foreground) return;
        ++requestSeqRef.current;
        providersRef.current = null;
        setProvidersLoaded(false);
        setProviders([]);
        setResults([]);
        setErrors([]);
        setHasMore(false);
        setTotalCount(0);
        setGlobalError(errorMessage(err));
        loadingRef.current = false;
        setLoading(false);
      })
      .finally(() => {
        if (seq === providersSeqRef.current) {
          providersRequestRef.current = false;
          setProvidersLoading(false);
        }
      });
  }, []);

  const refresh = useCallback(() => fetchProviders(true), [fetchProviders]);

  const invalidateRequests = useCallback(() => {
    providersRequestRef.current = false;
    ++providersSeqRef.current;
    ++requestSeqRef.current;
  }, []);

  useEffect(() => {
    fetchProviders();
    const unsubscribe = subscribeToPluginChanges(refresh);
    const onFocus = () => fetchProviders();
    const onVisible = () => {
      if (document.visibilityState === "visible") fetchProviders();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      unsubscribe();
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
      invalidateRequests();
    };
  }, [fetchProviders, refresh, invalidateRequests]);

  useEffect(() => {
    let alive = true;
    marketApi
      .listMarketCategories(lang)
      .then((list) => {
        if (alive) setCategories(list);
      })
      .catch(() => {
        if (alive) setCategories([]);
      });
    return () => {
      alive = false;
    };
  }, [lang]);

  const setCategory = useCallback((id: string) => {
    setCategoryState(id);
  }, []);

  const setSelectedProviders = useCallback((keys: string[]) => {
    setSelectedProviderKeys(new Set(keys));
  }, []);

  // Persist the provider selection so it survives a page refresh.
  useEffect(() => {
    if (!providersLoaded) return;
    try {
      localStorage.setItem(
        PROVIDERS_STORAGE_KEY,
        JSON.stringify([...selectedProviderKeys]),
      );
    } catch {
      // Storage unavailable; keep the current selection in memory.
    }
  }, [selectedProviderKeys, providersLoaded]);

  const applyResponse = useCallback(
    (resp: MarketSearchResponse, append: boolean) => {
      const cursors = cursorsRef.current;
      for (const [key, info] of Object.entries(resp.by_provider)) {
        const current = cursors[key];
        if (typeof current === "number") {
          cursors[key] = info.has_more ? current + 1 : null;
        }
        totalsRef.current[key] = info.total;
      }
      setTotalCount(
        Object.values(totalsRef.current).reduce((sum, n) => sum + n, 0),
      );
      setResults((prev) =>
        append ? [...prev, ...resp.results] : resp.results,
      );
      setErrors(resp.errors);
      setHasMore(Object.values(cursors).some((v) => v !== null));
      // A failing provider never advances its cursor, so hasMore stays
      // true forever — block auto-load to avoid an endless retry loop.
      if (resp.errors.length > 0) setAutoLoadBlocked(true);
    },
    [setAutoLoadBlocked],
  );

  const runFetch = useCallback(
    (
      q: string,
      pages: Record<string, number>,
      append: boolean,
      lng: string,
      cat: string,
    ) => {
      const seq = ++requestSeqRef.current;
      if (!append) {
        setResults([]);
        setErrors([]);
        setHasMore(false);
        setTotalCount(0);
      }
      // An empty query browses the providers' default listing; only
      // bail when there are no providers to query.
      if (Object.keys(pages).length === 0) {
        if (providersLoaded) setGlobalError(null);
        loadingRef.current = false;
        setLoading(false);
        return;
      }
      loadingRef.current = true;
      setLoading(true);
      setGlobalError(null);
      marketApi
        .searchMarket({
          query: q.trim(),
          provider_pages: pages,
          limit: PER_PROVIDER_LIMIT,
          lang: lng,
          category: cat || undefined,
        })
        .then((resp) => {
          if (seq !== requestSeqRef.current) return;
          applyResponse(resp, append);
        })
        .catch((err: unknown) => {
          if (seq !== requestSeqRef.current) return;
          setGlobalError(errorMessage(err));
          setAutoLoadBlocked(true);
          if (!append) {
            setResults([]);
            setHasMore(false);
          }
        })
        .finally(() => {
          if (seq === requestSeqRef.current) {
            loadingRef.current = false;
            setLoading(false);
          }
        });
    },
    [applyResponse, setAutoLoadBlocked, providersLoaded],
  );

  const fetchNextPages = useCallback(() => {
    const pages: Record<string, number> = {};
    for (const [key, cursor] of Object.entries(cursorsRef.current)) {
      if (typeof cursor === "number") pages[key] = cursor;
    }
    if (Object.keys(pages).length === 0) return;
    runFetch(debouncedQuery, pages, true, lang, category);
  }, [debouncedQuery, lang, category, runFetch]);

  // Manual click also re-arms auto-loading after an error.
  const loadMore = useCallback(() => {
    setAutoLoadBlocked(false);
    fetchNextPages();
  }, [fetchNextPages, setAutoLoadBlocked]);

  const autoLoadMore = useCallback(() => {
    if (loadingRef.current || providersLoading || autoLoadBlockedRef.current)
      return;
    fetchNextPages();
  }, [fetchNextPages, providersLoading]);

  const retry = useCallback(() => {
    if (providers.length === 0) {
      refresh();
    } else {
      loadMore();
    }
  }, [providers.length, refresh, loadMore]);

  // Search and category browse are mutually exclusive (same semantics
  // as the plugin market): typing a query clears the active category.
  const setQuery = useCallback((q: string) => {
    setQueryState(q);
    if (q.trim()) setCategoryState("");
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  // Reset cursors + refetch when query/providers/lang/category change.
  const lastKeyRef = useRef("");
  useEffect(() => {
    if (!providersLoaded) return;
    const key = `${catalogVersion}|${debouncedQuery}|${providerKeyList.join(
      ",",
    )}|${lang}|${category}`;
    if (lastKeyRef.current === key) return;
    lastKeyRef.current = key;
    const initialPages: Record<string, number> = {};
    const nextCursors: Record<string, number | null> = {};
    for (const k of providerKeyList) {
      initialPages[k] = 1;
      nextCursors[k] = 1;
    }
    cursorsRef.current = nextCursors;
    totalsRef.current = {};
    setAutoLoadBlocked(false);
    runFetch(debouncedQuery, initialPages, false, lang, category);
  }, [
    providersLoaded,
    catalogVersion,
    debouncedQuery,
    providerKeyList,
    lang,
    category,
    runFetch,
    setAutoLoadBlocked,
  ]);

  return {
    providers,
    providersLoaded,
    selectedProviderKeys,
    setSelectedProviders,
    categories,
    category,
    setCategory,
    query,
    setQuery,
    results,
    errors,
    globalError,
    loading: loading || providersLoading,
    totalCount,
    hasMore,
    loadMore,
    autoLoadMore,
    autoLoadBlocked,
    refresh,
    retry,
  };
}
