import { useTranslation } from "react-i18next";
import type { TocItem } from "../markdown";

interface DocsTocProps {
  toc: TocItem[];
  activeTocId: string | null;
  onItemClick: (id: string, index: number) => void;
}

/** "On this page" table of contents. */
export function DocsToc({ toc, activeTocId, onItemClick }: DocsTocProps) {
  const { t } = useTranslation();

  return (
    <aside className="docs-toc" aria-label={t("docs.onThisPage")}>
      <nav className="docs-toc-nav">
        {toc.map(({ level, text, id }, idx) => (
          <a
            key={id}
            href={`#${id}`}
            className={
              level === 3 ? "docs-toc-item docs-toc-item-h3" : "docs-toc-item"
            }
            data-active={activeTocId === id ? "true" : undefined}
            onClick={(e) => {
              e.preventDefault();
              onItemClick(id, idx);
            }}
          >
            {text}
          </a>
        ))}
      </nav>
    </aside>
  );
}
