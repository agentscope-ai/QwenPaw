import { Link } from "react-router-dom";
import { FileText } from "lucide-react";
import type { Lang } from "../i18n";
import { t } from "../i18n";
import { useDocSearch } from "../lib/docsSearch";
import type { SearchRow } from "../lib/docsSearch";

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Split text by query terms and return segments; odd indices are matches. */
function getHighlightRegex(query: string): RegExp | null {
  const words = query.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return null;
  const pattern = words.map(escapeRegex).join("|");
  return new RegExp(`(${pattern})`, "gi");
}

function Highlighted({ text, query }: { text: string; query: string }) {
  const re = getHighlightRegex(query);
  if (!re || !text) return <>{text}</>;
  const parts = text.split(re);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="docs-search-highlight">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

const SNIPPET_RADIUS = 60;
const SNIPPET_MAX = 200;

function getSnippet(fullText: string, query: string): string {
  const q = query.trim();
  if (!q || !fullText) return fullText.slice(0, SNIPPET_MAX).trim();
  const normalized = fullText.replace(/\s+/g, " ").trim();
  const words = q.split(/\s+/).filter(Boolean);
  let bestStart = 0;
  let bestLen = 0;
  const lower = normalized.toLowerCase();
  for (const w of words) {
    const idx = lower.indexOf(w.toLowerCase());
    if (idx === -1) continue;
    const start = Math.max(0, idx - SNIPPET_RADIUS);
    const end = Math.min(normalized.length, idx + w.length + SNIPPET_RADIUS);
    const len = end - start;
    if (len > bestLen) {
      bestStart = start;
      bestLen = len;
    }
  }
  if (bestLen === 0) return normalized.slice(0, SNIPPET_MAX).trim();
  let snippet = normalized.slice(bestStart, bestStart + bestLen);
  if (bestStart > 0) snippet = "…" + snippet;
  if (bestStart + bestLen < normalized.length) snippet = snippet + "…";
  return snippet.length > SNIPPET_MAX
    ? snippet.slice(0, SNIPPET_MAX - 1) + "…"
    : snippet;
}

interface DocSearchResultsProps {
  lang: Lang;
  query: string;
}

export function DocSearchResults({ lang, query }: DocSearchResultsProps) {
  const { results, loading } = useDocSearch(lang, query);

  return (
    <div
      className="docs-search-results-page"
      style={{
        maxWidth: "44rem",
        margin: "0 auto",
        padding: "var(--space-6) var(--space-4)",
      }}
    >
      <h1
        style={{
          fontSize: "1.5rem",
          fontWeight: 600,
          marginBottom: "var(--space-4)",
          color: "var(--text)",
        }}
      >
        {query.trim()
          ? t(lang, "docs.searchResultsTitle")
          : t(lang, "docs.searchResultsTitleEmpty")}
      </h1>
      {loading ? (
        <p
          style={{
            fontSize: "0.9375rem",
            color: "var(--text-muted)",
          }}
        >
          {t(lang, "docs.searchLoading")}
        </p>
      ) : !query.trim() ? (
        <p
          style={{
            fontSize: "0.9375rem",
            color: "var(--text-muted)",
          }}
        >
          {t(lang, "docs.searchHint")}
        </p>
      ) : results.length === 0 ? (
        <p
          style={{
            fontSize: "0.9375rem",
            color: "var(--text-muted)",
          }}
        >
          {t(lang, "docs.searchNoResults")}
        </p>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-4)",
          }}
        >
          {results.map((row, i) => (
            <ResultCard
              key={`${row.slug}-${row.headingId ?? "doc"}-${i}`}
              row={row}
              query={query}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultCard({ row, query }: { row: SearchRow; query: string }) {
  const to = row.headingId
    ? `/docs/${row.slug}#${row.headingId}`
    : `/docs/${row.slug}`;
  const snippet = getSnippet(row.searchText, query);

  return (
    <li>
      <Link
        to={to}
        className="docs-search-result-link"
        style={{
          display: "block",
          padding: "var(--space-4)",
          borderRadius: "0.5rem",
          border: "1px solid var(--border)",
          background: "var(--surface)",
          color: "var(--text)",
          textDecoration: "none",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "var(--space-2)",
          }}
        >
          <FileText
            size={20}
            strokeWidth={1.5}
            style={{
              flexShrink: 0,
              marginTop: 2,
              color: "var(--text-muted)",
            }}
            aria-hidden
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: "1rem",
                fontWeight: 600,
                marginBottom: "var(--space-1)",
                color: "var(--text)",
              }}
            >
              <Highlighted text={row.title} query={query} />
              {row.headingText && (
                <>
                  <span style={{ margin: "0 0.25rem", fontWeight: 400 }}>
                    ›
                  </span>
                  <Highlighted text={row.headingText} query={query} />
                </>
              )}
            </div>
            {snippet && (
              <p
                style={{
                  fontSize: "0.875rem",
                  lineHeight: 1.5,
                  color: "var(--text-muted)",
                  margin: 0,
                }}
              >
                <Highlighted text={snippet} query={query} />
              </p>
            )}
          </div>
        </div>
      </Link>
    </li>
  );
}
