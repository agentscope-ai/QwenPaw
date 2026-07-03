import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Menu } from "lucide-react";
import { DocSearch } from "@/components/DocSearch";
import { DOC_GROUPS, prefetchDoc } from "../navigation";

interface DocsSidebarProps {
  activeSlug: string;
  lang: "zh" | "en";
  open: boolean;
  onToggle: () => void;
  onNavigate: () => void;
  searchQuery: string;
}

export function DocsSidebar({
  activeSlug,
  lang,
  open,
  onToggle,
  onNavigate,
  searchQuery,
}: DocsSidebarProps) {
  const { t } = useTranslation();

  return (
    <aside
      className={[
        "docs-sidebar z-40 w-64 shrink-0 border-r border-border bg-(--surface) px-2 py-4",
        "fixed left-0 top-14 bottom-0 overflow-y-auto transition-transform duration-200 md:static md:top-auto md:bottom-auto md:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full md:translate-x-0",
      ].join(" ")}
    >
      <button
        type="button"
        className="mb-2 inline-flex items-center rounded-md p-2 text-(--text) hover:bg-(--bg) md:hidden"
        onClick={onToggle}
        aria-label={t("docs.toggleSidebar")}
      >
        <Menu size={24} />
      </button>
      <DocSearch initialQuery={searchQuery} />
      <nav className="flex flex-col gap-3 pt-1">
        {DOC_GROUPS.map((group) => (
          <section key={group.titleKey}>
            <h3 className="mb-1 text-[1rem] leading-6 font-semibold text-(--color-text)">
              {t(group.titleKey)}
            </h3>
            <div className="flex flex-col gap-0.5">
              {group.children.map((entry) => (
                <Link
                  key={entry.slug}
                  to={`/docs/${entry.slug}`}
                  className={[
                    "flex items-center rounded-lg px-3 py-1.5 text-[0.9375rem] leading-6 transition-colors",
                    activeSlug === entry.slug
                      ? "bg-(--color-fill-secondary) font-medium text-(--color-text)"
                      : "text-(-color-text-secondary) hover:bg-[#F1F1F1] hover:text-(--color-text)",
                  ].join(" ")}
                  onClick={onNavigate}
                  onMouseEnter={() => prefetchDoc(entry.slug, lang)}
                  onFocus={() => prefetchDoc(entry.slug, lang)}
                >
                  {t(entry.titleKey)}
                </Link>
              ))}
            </div>
          </section>
        ))}
      </nav>
    </aside>
  );
}
