import { useState, useEffect, useMemo } from "react";
import Fuse from "fuse.js";

export interface IndexHeading {
  text: string;
  id: string;
}

export interface IndexEntry {
  slug: string;
  lang: string;
  title: string;
  headings: IndexHeading[];
  excerpt: string;
}

export interface SearchRow {
  slug: string;
  lang: string;
  title: string;
  excerpt: string;
  searchText: string;
  headingId?: string;
  headingText?: string;
}

function expandIndex(entries: IndexEntry[]): SearchRow[] {
  const rows: SearchRow[] = [];
  for (const e of entries) {
    const headingPart = e.headings.map((h) => h.text).join(" ");
    const searchText = [e.title, headingPart, e.excerpt]
      .filter(Boolean)
      .join(" ");
    rows.push({
      slug: e.slug,
      lang: e.lang,
      title: e.title,
      excerpt: e.excerpt,
      searchText,
    });
    for (const h of e.headings) {
      rows.push({
        slug: e.slug,
        lang: e.lang,
        title: e.title,
        excerpt: e.excerpt,
        searchText: [e.title, h.text, e.excerpt].filter(Boolean).join(" "),
        headingId: h.id,
        headingText: h.text,
      });
    }
  }
  return rows;
}

export function useDocSearch(
  lang: string,
  query: string,
): { results: SearchRow[]; loading: boolean } {
  const [index, setIndex] = useState<IndexEntry[] | null>(null);

  useEffect(() => {
    const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") || "";
    fetch(`${base}/search-index.json`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: IndexEntry[]) => setIndex(data))
      .catch(() => setIndex([]));
  }, []);

  const rowsByLang = useMemo(() => {
    if (!index) return [];
    return expandIndex(index.filter((e) => e.lang === lang));
  }, [index, lang]);

  const fuse = useMemo(
    () =>
      new Fuse(rowsByLang, {
        keys: ["searchText", "title", "headingText", "excerpt"],
        threshold: 0.45,
        ignoreLocation: true,
      }),
    [rowsByLang],
  );

  const results = useMemo(() => {
    const q = query.trim();
    if (!q) return [];
    const raw = fuse.search(q);
    return raw
      .sort((a, b) => (a.score ?? 1) - (b.score ?? 1))
      .map((r) => r.item)
      .slice(0, 20);
  }, [query, fuse]);

  return {
    results,
    loading: index === null,
  };
}
