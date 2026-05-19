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
const PAGE_SIZE = 20;
const CACHE_MAX = 32;

export interface MarketSearchState {
  providers: MarketProviderInfo[];
  selectedProviderKeys: Set<string>;
  toggleProvider: (key: string) => void;
  query: string;
  setQuery: (q: string) => void;
  results: MarketResult[];
  errors: MarketSearchError[];
  loading: boolean;
  page: number;
  setPage: (n: number) => void;
  hasMore: boolean;
  total: number;
  pageSize: number;
}

function cacheKey(q: string, providers: string[], page: number, lang: string) {
  const sorted = [...providers].sort();
  return JSON.stringify({ q: q.trim(), p: sorted, n: page, l: lang });
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
  const [page, setPageState] = useState(1);
  const [results, setResults] = useState<MarketResult[]>([]);
  const [errors, setErrors] = useState<MarketSearchError[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const requestSeqRef = useRef(0);
  const cacheRef = useRef<Map<string, MarketSearchResponse>>(new Map());

  const providerKeyList = useMemo(
    () => Array.from(selectedProviderKeys).sort(),
    [selectedProviderKeys],
  );

  useEffect(() => {
    let cancelled = false;
    marketApi
      .listMarketProviders()
      .then((list) => {
        if (cancelled) return;
        setProviders(list);
        const enabled = list.filter((p) => p.available).map((p) => p.key);
        setSelectedProviderKeys(new Set(enabled));
      })
      .catch(() => {
        if (cancelled) return;
        setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleProvider = useCallback((key: string) => {
    setSelectedProviderKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const applyResponse = useCallback((resp: MarketSearchResponse) => {
    setResults(resp.results);
    setErrors(resp.errors);
    setHasMore(Boolean(resp.has_more));
    setTotal(typeof resp.total === "number" ? resp.total : 0);
  }, []);

  const storeCache = useCallback((key: string, resp: MarketSearchResponse) => {
    const cache = cacheRef.current;
    if (cache.size >= CACHE_MAX) {
      const oldest = cache.keys().next().value;
      if (oldest !== undefined) cache.delete(oldest);
    }
    cache.set(key, resp);
  }, []);

  const prefetch = useCallback(
    (q: string, providerKeys: string[], pageNum: number) => {
      if (!q.trim() || providerKeys.length === 0) return;
      const key = cacheKey(q, providerKeys, pageNum, lang);
      if (cacheRef.current.has(key)) return;
      marketApi
        .searchMarket({
          query: q.trim(),
          providers: providerKeys,
          limit: PAGE_SIZE,
          page: pageNum,
          lang,
        })
        .then((resp) => storeCache(key, resp))
        .catch(() => {});
    },
    [storeCache, lang],
  );

  const fetchPage = useCallback(
    (q: string, providerKeys: string[], pageNum: number) => {
      const seq = ++requestSeqRef.current;
      if (!q.trim() || providerKeys.length === 0) {
        setResults([]);
        setErrors([]);
        setHasMore(false);
        setTotal(0);
        setLoading(false);
        return;
      }
      const key = cacheKey(q, providerKeys, pageNum, lang);
      const cached = cacheRef.current.get(key);
      if (cached) {
        applyResponse(cached);
        setLoading(false);
        if (cached.has_more) prefetch(q, providerKeys, pageNum + 1);
        return;
      }
      // Clear results so a page change is visible during the request.
      setResults([]);
      setErrors([]);
      setLoading(true);
      marketApi
        .searchMarket({
          query: q.trim(),
          providers: providerKeys,
          limit: PAGE_SIZE,
          page: pageNum,
          lang,
        })
        .then((resp) => {
          if (seq !== requestSeqRef.current) return;
          storeCache(key, resp);
          applyResponse(resp);
          if (resp.has_more) prefetch(q, providerKeys, pageNum + 1);
        })
        .catch((err: unknown) => {
          if (seq !== requestSeqRef.current) return;
          setResults([]);
          setHasMore(false);
          setTotal(0);
          setErrors([
            {
              provider: "*",
              message: err instanceof Error ? err.message : String(err),
            },
          ]);
        })
        .finally(() => {
          if (seq === requestSeqRef.current) setLoading(false);
        });
    },
    [applyResponse, prefetch, storeCache, lang],
  );

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
  }, []);

  const setPage = useCallback((n: number) => {
    setPageState(Math.max(1, n));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    setPageState(1);
    cacheRef.current.clear();
  }, [debouncedQuery, providerKeyList.join(","), lang]);

  useEffect(() => {
    fetchPage(debouncedQuery, providerKeyList, page);
  }, [debouncedQuery, providerKeyList, page, fetchPage]);

  return {
    providers,
    selectedProviderKeys,
    toggleProvider,
    query,
    setQuery,
    results,
    errors,
    loading,
    page,
    setPage,
    hasMore,
    total,
    pageSize: PAGE_SIZE,
  };
}
