import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { marketApi } from "../../../api/modules/market";
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
  selectedProviderKeys: Set<string>;
  toggleProvider: (key: string) => void;
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
    const ordered = providers
      .map((p) => p.key)
      .filter((k) => selectedProviderKeys.has(k));
    for (const k of selectedProviderKeys) {
      if (!ordered.includes(k)) ordered.push(k);
    }
    return ordered;
  }, [providers, selectedProviderKeys]);

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
        setSelectedProviderKeys((prev) => {
          const valid = [...prev].filter((k) => enabled.includes(k));
          if (valid.length > 0) return new Set(valid);
          const fallback = enabled.includes("qwenpaw")
            ? ["qwenpaw"]
            : enabled.slice(0, 1);
          return new Set(fallback);
        });
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

  const toggleProvider = useCallback((key: string) => {
    setSelectedProviderKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Persist the provider selection so it survives a page refresh.
  useEffect(() => {
    localStorage.setItem(
      PROVIDERS_STORAGE_KEY,
      JSON.stringify([...selectedProviderKeys]),
    );
  }, [selectedProviderKeys]);

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
      // An empty query browses the providers' default listing; only
      // bail when there are no providers to query.
      if (Object.keys(pages).length === 0) {
        setResults([]);
        setErrors([]);
        setHasMore(false);
        setTotalCount(0);
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
    [applyResponse, setAutoLoadBlocked],
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
    if (loadingRef.current || autoLoadBlockedRef.current) return;
    fetchNextPages();
  }, [fetchNextPages]);

  const retry = useCallback(() => {
    if (providers.length === 0) {
      fetchProviders();
    } else {
      loadMore();
    }
  }, [providers.length, fetchProviders, loadMore]);

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
    const key = `${debouncedQuery}|${providerKeyList.join(
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
    debouncedQuery,
    providerKeyList,
    lang,
    category,
    runFetch,
    setAutoLoadBlocked,
  ]);

  return {
    providers,
    selectedProviderKeys,
    toggleProvider,
    categories,
    category,
    setCategory,
    query,
    setQuery,
    results,
    errors,
    globalError,
    loading,
    totalCount,
    hasMore,
    loadMore,
    autoLoadMore,
    autoLoadBlocked,
    retry,
  };
}
