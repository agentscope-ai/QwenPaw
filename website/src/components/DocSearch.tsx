import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import type { Lang } from "../i18n";
import { t } from "../i18n";

interface DocSearchProps {
  lang: Lang;
  /** When on search page, pass the current q so input shows it */
  initialQuery?: string;
}

export function DocSearch({ lang, initialQuery = "" }: DocSearchProps) {
  const [inputValue, setInputValue] = useState(initialQuery);
  const navigate = useNavigate();

  useEffect(() => {
    setInputValue(initialQuery);
  }, [initialQuery]);

  const runSearch = () => {
    const q = inputValue.trim();
    if (!q) return;
    navigate(`/docs/search?q=${encodeURIComponent(q)}`);
  };

  return (
    <div
      className="docs-search-wrap"
      style={{
        marginBottom: "var(--space-2)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-1)",
          padding: "var(--space-1) var(--space-2)",
          borderRadius: "0.375rem",
          background: "var(--bg)",
          border: "1px solid var(--border)",
        }}
      >
        <Search
          size={16}
          strokeWidth={1.5}
          style={{ flexShrink: 0, color: "var(--text-muted)" }}
          aria-hidden
        />
        <input
          type="search"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              runSearch();
            }
          }}
          placeholder={t(lang, "docs.searchPlaceholder")}
          aria-label={t(lang, "docs.searchPlaceholder")}
          style={{
            flex: 1,
            minWidth: 0,
            border: "none",
            background: "none",
            fontSize: "0.875rem",
            color: "var(--text)",
            outline: "none",
          }}
        />
      </div>
    </div>
  );
}
