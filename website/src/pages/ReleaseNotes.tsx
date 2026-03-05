import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import { ChevronDown, ChevronRight, FileText, Menu } from "lucide-react";
import { Nav } from "../components/Nav";
import { Footer } from "../components/Footer";
import type { SiteConfig } from "../config";
import { type Lang, t } from "../i18n";

interface ReleaseNote {
  version: string;
  content: string;
  date?: string;
}

interface ReleaseNotesProps {
  config: SiteConfig;
  lang: Lang;
  onLangClick: () => void;
}

const RELEASE_NOTES_DATA: { version: string; date?: string }[] = [
  { version: "v0.0.5-beta.2" },
  { version: "v0.0.5-beta.1" },
  { version: "v0.0.4" },
];

export function ReleaseNotes({ config, lang, onLangClick }: ReleaseNotesProps) {
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
          if (lang === "zh") {
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
  }, [lang]);

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
      <>
        <Nav
          projectName={config.projectName}
          lang={lang}
          onLangClick={onLangClick}
          docsPath={config.docsPath}
          repoUrl={config.repoUrl}
        />
        <div
          style={{
            minHeight: "calc(100vh - 4rem)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text-muted)",
          }}
        >
          {t(lang, "docs.searchLoading")}
        </div>
      </>
    );
  }

  return (
    <>
      <Nav
        projectName={config.projectName}
        lang={lang}
        onLangClick={onLangClick}
        docsPath={config.docsPath}
        repoUrl={config.repoUrl}
      />
      <div className="docs-layout">
        <aside
          style={{
            width: "16rem",
            flexShrink: 0,
            borderRight: "1px solid var(--border)",
            padding: "var(--space-4) var(--space-2)",
            background: "var(--surface)",
          }}
          className={sidebarOpen ? "docs-sidebar open" : "docs-sidebar"}
        >
          <button
            type="button"
            className="docs-sidebar-toggle"
            onClick={() => setSidebarOpen((o) => !o)}
            aria-label="Toggle sidebar"
            style={{
              display: "none",
              background: "none",
              border: "none",
              padding: "var(--space-2)",
            }}
          >
            <Menu size={24} />
          </button>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--space-2)",
              padding: "var(--space-2)",
              marginBottom: "var(--space-3)",
            }}
          >
            <FileText size={20} strokeWidth={1.5} aria-hidden />
            <h2
              style={{
                fontSize: "1rem",
                fontWeight: 600,
                color: "var(--text)",
                margin: 0,
              }}
            >
              {t(lang, "releaseNotes.title")}
            </h2>
          </div>

          <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {releases.map((release, idx) => {
              const isActive = activeVersion === release.version;
              return (
                <button
                  key={release.version}
                  type="button"
                  onClick={() => handleVersionClick(release.version, idx)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-1)",
                    padding: "var(--space-2)",
                    borderRadius: "0.375rem",
                    fontSize: "0.9375rem",
                    fontWeight: isActive ? 500 : 400,
                    color: isActive ? "var(--text)" : "var(--text-muted)",
                    background: isActive ? "var(--bg)" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    width: "100%",
                    transition: "all 0.15s",
                  }}
                >
                  <span style={{ flex: 1 }}>{release.version}</span>
                  {isActive && (
                    <ChevronRight size={16} style={{ flexShrink: 0 }} />
                  )}
                </button>
              );
            })}
          </nav>
        </aside>

        <main className="docs-main">
          <div className="docs-content-scroll" ref={contentRef}>
            <article className="docs-content">
              {releases.length === 0 ? (
                <div
                  style={{
                    textAlign: "center",
                    padding: "var(--space-8)",
                    color: "var(--text-muted)",
                  }}
                >
                  {t(lang, "releaseNotes.noReleases")}
                </div>
              ) : (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "1rem",
                  }}
                >
                  {releases.map((release, idx) => {
                    const expanded = expandedSet.has(idx);
                    return (
                      <section
                        key={release.version}
                        ref={(el) => {
                          if (el) versionRefs.current.set(release.version, el);
                        }}
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: "0.75rem",
                          background: "var(--surface)",
                          overflow: "hidden",
                        }}
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
                          style={{
                            width: "100%",
                            textAlign: "left",
                            background: "transparent",
                            border: "none",
                            padding: "1.25rem 1.5rem",
                            cursor: "pointer",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: "1rem",
                          }}
                          aria-expanded={expanded}
                        >
                          <div>
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
                              <div
                                style={{
                                  fontSize: "0.875rem",
                                  color: "var(--text-muted)",
                                }}
                              >
                                {release.date}
                              </div>
                            )}
                          </div>
                          <ChevronDown
                            size={24}
                            style={{
                              flexShrink: 0,
                              transform: expanded
                                ? "rotate(180deg)"
                                : "rotate(0deg)",
                              transition: "transform 0.2s ease",
                              color: "var(--text-muted)",
                            }}
                          />
                        </button>
                        {expanded && (
                          <div
                            className="release-notes-content"
                            style={{
                              padding: "0 1.5rem 1.5rem 1.5rem",
                              borderTop: "1px solid var(--border)",
                              paddingTop: "1.5rem",
                            }}
                          >
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              rehypePlugins={[rehypeRaw, rehypeHighlight]}
                              components={{
                                h1: ({ children }) => (
                                  <h3
                                    style={{
                                      fontSize: "1.25rem",
                                      marginTop: 0,
                                    }}
                                  >
                                    {children}
                                  </h3>
                                ),
                                h2: ({ children }) => (
                                  <h3 style={{ fontSize: "1.125rem" }}>
                                    {children}
                                  </h3>
                                ),
                                h3: ({ children }) => (
                                  <h4 style={{ fontSize: "1rem" }}>
                                    {children}
                                  </h4>
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
            <footer className="docs-page-footer" aria-label="Document footer">
              <Footer lang={lang} />
            </footer>
          </div>
        </main>
      </div>
      <style>{`
        .release-notes-content > :first-child {
          margin-top: 0;
        }
        .release-notes-content > :last-child {
          margin-bottom: 0;
        }
        @media (max-width: 768px) {
          .docs-sidebar {
            position: fixed;
            left: 0;
            top: 3.5rem;
            bottom: 0;
            z-index: 20;
            transform: translateX(-100%);
            transition: transform 0.2s;
          }
          .docs-sidebar.open {
            transform: translateX(0);
          }
          .docs-sidebar-toggle {
            display: flex !important;
          }
        }
      `}</style>
    </>
  );
}
