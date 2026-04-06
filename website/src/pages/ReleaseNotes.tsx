import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import { ChevronDown, ChevronRight, FileText, Menu } from "lucide-react";

interface ReleaseNote {
  version: string;
  content: string;
  date?: string;
}

const RELEASE_NOTES_DATA: { version: string; date?: string }[] = [
  { version: "v1.0.1" },
  { version: "v1.0.0" },
  { version: "v0.2.0" },
  { version: "v0.1.0" },
  { version: "v0.0.7" },
  { version: "v0.0.6" },
  { version: "v0.0.5" },
  // { version: "v0.0.5-beta.3" },
  // { version: "v0.0.5-beta.2" },
  // { version: "v0.0.5-beta.1" },
  { version: "v0.0.4" },
];

export function ReleaseNotes() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [releases, setReleases] = useState<ReleaseNote[]>([]);
  const [expandedSet, setExpandedSet] = useState<Set<number>>(
    () => new Set([0]),
  );
  const [loading, setLoading] = useState(true);
  const [activeVersion, setActiveVersion] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const versionRefs = useRef<Map<string, HTMLElement>>(new Map());

  useEffect(() => {
    setLoading(true);
    const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") || "";

    const fetchPromises = RELEASE_NOTES_DATA.map(
      async ({ version, date }): Promise<ReleaseNote | null> => {
        try {
          let response;

          // Chinese: try .zh.md first, then fallback to .md
          if (isZh) {
            response = await fetch(`${base}/release-notes/${version}.zh.md`);
            if (!response.ok) {
              response = await fetch(`${base}/release-notes/${version}.md`);
            }
          } else {
            // English and other languages: use .md directly
            response = await fetch(`${base}/release-notes/${version}.md`);
          }

          if (response.ok) {
            const content = await response.text();
            return { version, content, ...(date && { date }) };
          }
        } catch (error) {
          console.error(`Failed to fetch release note for ${version}:`, error);
        }
        return null;
      },
    );

    Promise.all(fetchPromises).then((results) => {
      const validReleases = results.filter((r): r is ReleaseNote => r !== null);
      setReleases(validReleases);
      if (validReleases.length > 0) {
        setActiveVersion(validReleases[0].version);
      }
      setLoading(false);
    });
  }, [isZh]);

  // Monitor scroll position to update active version
  useEffect(() => {
    const container = contentRef.current;
    if (!container || releases.length === 0) return;

    const updateActive = () => {
      const containerTop = container.getBoundingClientRect().top;

      let current: string | null = null;
      releases.forEach((release) => {
        const el = versionRefs.current.get(release.version);
        if (el) {
          const rect = el.getBoundingClientRect();
          if (rect.top - containerTop <= 100) {
            current = release.version;
          }
        }
      });

      if (current) {
        setActiveVersion(current);
      }
    };

    updateActive();
    container.addEventListener("scroll", updateActive, { passive: true });
    return () => container.removeEventListener("scroll", updateActive);
  }, [releases]);

  useEffect(() => {
    setSidebarOpen(false);
  }, [isZh]);

  const handleVersionClick = (version: string, idx: number) => {
    const el = versionRefs.current.get(version);
    if (el && contentRef.current) {
      const top = el.offsetTop - 20;
      contentRef.current.scrollTo({ top, behavior: "smooth" });

      // Expand the clicked version if it's not already expanded
      if (!expandedSet.has(idx)) {
        setExpandedSet((prev) => {
          const next = new Set(prev);
          next.add(idx);
          return next;
        });
      }
    }
    setSidebarOpen(false);
  };

  if (loading) {
    return (
      <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center text-(--text-muted)">
        {t("docs.searchLoading")}
      </div>
    );
  }

  return (
    <>
      <div className="docs-layout relative">
        {sidebarOpen && (
          <button
            type="button"
            className="fixed inset-0 z-30 bg-black/40 md:hidden"
            aria-label={t("docs.closeSidebar")}
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <aside
          className={[
            "docs-sidebar z-40 w-64 shrink-0 border-r border-(--border) bg-(--surface) px-2 py-4",
            "fixed left-0 top-14 bottom-0 overflow-y-auto transition-transform duration-200 md:static md:top-auto md:bottom-auto md:translate-x-0",
            sidebarOpen
              ? "translate-x-0"
              : "-translate-x-full md:translate-x-0",
          ].join(" ")}
        >
          <button
            type="button"
            className="mb-2 inline-flex items-center rounded-md p-2 text-(--text) hover:bg-(--bg) md:hidden"
            onClick={() => setSidebarOpen((o) => !o)}
            aria-label={t("docs.toggleSidebar")}
          >
            <Menu size={24} />
          </button>

          <div className="mb-3 flex items-center gap-2 px-2 py-2">
            <FileText size={20} strokeWidth={1.5} aria-hidden />
            <h2 className="m-0 text-base font-semibold text-(--text)">
              {t("releaseNotes.title")}
            </h2>
          </div>

          <nav className="flex flex-col gap-0.5">
            {releases.map((release, idx) => {
              const isActive = activeVersion === release.version;
              return (
                <button
                  key={release.version}
                  type="button"
                  onClick={() => handleVersionClick(release.version, idx)}
                  className={[
                    "flex w-full items-center gap-1 rounded-md border-0 px-2 py-2 text-left text-[0.9375rem] transition-colors",
                    isActive
                      ? "bg-(--bg) font-medium text-(--text)"
                      : "text-(--text-muted) hover:bg-(--bg)/60 hover:text-(--text)",
                  ].join(" ")}
                >
                  <span className="flex-1">{release.version}</span>
                  {isActive && <ChevronRight size={16} className="shrink-0" />}
                </button>
              );
            })}
          </nav>
        </aside>

        <main className="docs-main relative min-w-0">
          <div className="docs-content-scroll" ref={contentRef}>
            <div className="border-y border-(--border)/60 bg-(--surface) py-3 md:hidden">
              <div
                className="flex items-center gap-2 px-4"
                onClick={() => setSidebarOpen((o) => !o)}
              >
                <button
                  type="button"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-(--text-muted) hover:bg-(--bg)"
                  aria-label={
                    sidebarOpen
                      ? t("docs.closeSidebar")
                      : t("docs.toggleSidebar")
                  }
                >
                  <Menu size={18} />
                </button>
                <span className="text-sm font-semibold text-(--text)">
                  {t("releaseNotes.title")}
                </span>
              </div>
            </div>
            <article className="docs-content  mt-6 md:mt-0">
              {releases.length === 0 ? (
                <div className="p-(--space-8) text-center text-(--text-muted)">
                  {t("releaseNotes.noReleases")}
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  {releases.map((release, idx) => {
                    const expanded = expandedSet.has(idx);
                    return (
                      <section
                        key={release.version}
                        ref={(el) => {
                          if (el) versionRefs.current.set(release.version, el);
                        }}
                        className="overflow-hidden rounded-xl border border-(--border) bg-(--surface)"
                      >
                        <button
                          type="button"
                          onClick={() => {
                            setExpandedSet((prev) => {
                              const next = new Set(prev);
                              if (next.has(idx)) next.delete(idx);
                              else next.add(idx);
                              return next;
                            });
                          }}
                          className="flex w-full items-center justify-between gap-3 border-0 bg-transparent px-4 py-2 text-left md:gap-4 md:px-6 md:py-5"
                          aria-expanded={expanded}
                        >
                          <div className="leading-tight">
                            <h2
                              style={{
                                fontSize: "1.5rem",
                                fontWeight: 600,
                                color: "var(--text)",
                                margin: 0,
                                marginBottom: release.date ? "0.25rem" : 0,
                              }}
                            >
                              {release.version}
                            </h2>
                            {release.date && (
                              <div className="text-sm text-(--text-muted)">
                                {release.date}
                              </div>
                            )}
                          </div>
                          <ChevronDown
                            size={20}
                            className={[
                              "shrink-0 text-(--text-muted) transition-transform duration-200 ease-in-out",
                              expanded ? "rotate-180" : "rotate-0",
                            ].join(" ")}
                          />
                        </button>
                        {expanded && (
                          <div className="release-notes-content border-t border-(--border) px-4 pb-4 pt-4 md:px-6 md:pb-6 md:pt-6 [&>:first-child]:mt-0 [&>:last-child]:mb-0">
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              rehypePlugins={[rehypeRaw, rehypeHighlight]}
                              components={{
                                h1: ({ children }) => (
                                  <h3 className="mt-0 text-xl">{children}</h3>
                                ),
                                h2: ({ children }) => (
                                  <h3 className="text-lg">{children}</h3>
                                ),
                                h3: ({ children }) => (
                                  <h4 className="text-base">{children}</h4>
                                ),
                                a: ({ href, children }) => (
                                  <a
                                    href={href}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {children}
                                  </a>
                                ),
                              }}
                            >
                              {release.content}
                            </ReactMarkdown>
                          </div>
                        )}
                      </section>
                    );
                  })}
                </div>
              )}
            </article>
          </div>
        </main>
      </div>
    </>
  );
}
