import {
  useState,
  useEffect,
  useMemo,
  useRef,
  createContext,
  useContext,
} from "react";
import {
  Link,
  useParams,
  useNavigate,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  BookOpen,
  Menu,
  ChevronRight,
  ChevronDown,
  ArrowUp,
  Copy,
  Check,
} from "lucide-react";
import { Nav } from "../components/Nav";
import { Footer } from "../components/Footer";
import { MermaidBlock } from "../components/MermaidBlock";
import { DocSearch } from "../components/DocSearch";
import { DocSearchResults } from "../components/DocSearchResults";
import type { SiteConfig } from "../config";
import { type Lang, t } from "../i18n";
/* Code block theme: defined in index.css for high contrast */

const LangContext = createContext<Lang>("en");

function CodeBlockWithCopy({
  children,
  lang,
}: {
  children: React.ReactNode;
  lang: Lang;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    const code = wrapRef.current?.querySelector("code");
    const text = code?.textContent ?? "";
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="docs-code-wrap" ref={wrapRef}>
      <button
        type="button"
        className="docs-code-copy"
        onClick={handleCopy}
        aria-label={t(lang, "docs.copy")}
        title={t(lang, "docs.copy")}
      >
        {copied ? (
          <>
            <Check size={14} aria-hidden />
            <span>{t(lang, "docs.copied")}</span>
          </>
        ) : (
          <>
            <Copy size={14} aria-hidden />
            <span>{t(lang, "docs.copy")}</span>
          </>
        )}
      </button>
      {children}
    </div>
  );
}

/** Build URL-safe id from heading text (en + zh). */
function slugifyHeading(text: string): string {
  const s = text
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9_\-\u4e00-\u9fa5]/g, "");
  return s || "section";
}

/** Extract h2/h3 from markdown in order. */
function parseToc(
  md: string,
): Array<{ level: 2 | 3; text: string; id: string }> {
  const toc: Array<{ level: 2 | 3; text: string; id: string }> = [];
  const re = /^#{2,3}\s+(.+)$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(md)) !== null) {
    const level = m[0].startsWith("###") ? 3 : 2;
    const text = m[1].replace(/#+\s*$/, "").trim();
    toc.push({ level, text, id: slugifyHeading(text) });
  }
  return toc;
}

/** Flatten React children to string for slug. */
function headingText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(headingText).join("");
  if (children && typeof children === "object" && "props" in children)
    return headingText((children as React.ReactElement).props.children);
  return "";
}

interface DocEntry {
  slug: string;
  titleKey: string;
  children?: DocEntry[];
}

const DOC_SLUGS: DocEntry[] = [
  { slug: "intro", titleKey: "docs.intro" },
  { slug: "quickstart", titleKey: "docs.quickstart" },
  { slug: "console", titleKey: "docs.console" },
  { slug: "channels", titleKey: "docs.channels" },
  { slug: "skills", titleKey: "docs.skills" },
  {
    slug: "memory",
    titleKey: "docs.memory",
    children: [
      { slug: "compact", titleKey: "docs.compact" },
      { slug: "commands", titleKey: "docs.commands" },
    ],
  },
  { slug: "heartbeat", titleKey: "docs.heartbeat" },
  { slug: "config", titleKey: "docs.config" },
  { slug: "cli", titleKey: "docs.cli" },
  { slug: "community", titleKey: "docs.community" },
  { slug: "contributing", titleKey: "docs.contributing" },
];

/** Collect all valid slugs (parents + children). */
const ALL_SLUGS = DOC_SLUGS.flatMap((d) => [
  d.slug,
  ...(d.children?.map((c) => c.slug) ?? []),
]);

const DOC_TITLES: Record<Lang, Record<string, string>> = {
  zh: {
    "docs.intro": "项目介绍",
    "docs.quickstart": "快速开始",
    "docs.channels": "频道配置",
    "docs.heartbeat": "心跳",
    "docs.cli": "CLI",
    "docs.console": "控制台",
    "docs.skills": "Skills",
    "docs.memory": "记忆",
    "docs.compact": "压缩",
    "docs.config": "配置与工作目录",
    "docs.commands": "系统命令",
    "docs.community": "问题反馈与交流",
    "docs.contributing": "开源与贡献",
  },
  en: {
    "docs.intro": "Introduction",
    "docs.quickstart": "Quick start",
    "docs.channels": "Channels",
    "docs.heartbeat": "Heartbeat",
    "docs.cli": "CLI",
    "docs.console": "Console",
    "docs.skills": "Skills",
    "docs.memory": "Memory",
    "docs.compact": "Compaction",
    "docs.config": "Config & working dir",
    "docs.commands": "Commands",
    "docs.community": "Bug reports & community",
    "docs.contributing": "Open source & contribution",
  },
};

interface DocsProps {
  config: SiteConfig;
  lang: Lang;
  onLangClick: () => void;
}

export function Docs({ config, lang, onLangClick }: DocsProps) {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeSlug = slug ?? "intro";
  const isSearchPage = activeSlug === "search";
  const searchQ = searchParams.get("q") ?? "";
  const [content, setContent] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const toc = useMemo(() => parseToc(content), [content]);
  const [activeTocId, setActiveTocId] = useState<string | null>(null);
  const [showBackToTop, setShowBackToTop] = useState(false);
  const articleRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = articleRef.current;
    if (!el) return;
    if (!location.hash) el.scrollTo(0, 0);
  }, [activeSlug, location.pathname]);

  useEffect(() => {
    const rawHash = location.hash?.slice(1) ?? "";
    const hash = rawHash ? decodeURIComponent(rawHash.replace(/\+/g, " ")) : "";
    if (!hash) return;

    const scrollToHash = (): boolean => {
      const el = document.getElementById(hash);
      if (!el) return false;
      el.scrollIntoView({ behavior: "auto", block: "start" });
      return true;
    };

    let cancelled = false;
    let raf2: number | undefined;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    const raf1 = requestAnimationFrame(() => {
      if (cancelled) return;
      raf2 = requestAnimationFrame(() => {
        if (cancelled) return;
        if (scrollToHash()) return;
        timeoutId = setTimeout(() => {
          if (!cancelled) scrollToHash();
        }, 300);
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf1);
      if (raf2 !== undefined) cancelAnimationFrame(raf2);
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [content, location.hash]);

  useEffect(() => {
    if (isSearchPage) return;
    if (!ALL_SLUGS.includes(activeSlug)) {
      navigate("/docs/intro", { replace: true });
      return;
    }
    setContent("");
    let cancelled = false;
    const langSuffix = lang === "zh" ? "zh" : "en";
    const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") || "";
    const url = `${base}/docs/${activeSlug}.${langSuffix}.md`;
    fetch(url)
      .then((r) => (r.ok ? r.text() : ""))
      .then((text) => {
        if (cancelled) return;
        if (text) {
          setContent(text);
          return;
        }
        return fetch(`${base}/docs/${activeSlug}.md`).then((r) =>
          r.ok ? r.text() : "",
        );
      })
      .then((fallback) => {
        if (!cancelled && typeof fallback === "string") setContent(fallback);
      })
      .catch(() => {
        if (!cancelled) setContent("");
      });
    return () => {
      cancelled = true;
    };
  }, [activeSlug, lang, navigate, isSearchPage]);

  useEffect(() => {
    if (toc.length === 0) return;
    const container = articleRef.current;
    if (!container) return;
    const updateActive = () => {
      const containerTop = container.getBoundingClientRect().top;
      const trigger = containerTop + 120;
      let current: string | null = null;
      for (const { id } of toc) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= trigger) current = id;
      }
      setActiveTocId(current ?? toc[0]?.id ?? null);
    };
    updateActive();
    container.addEventListener("scroll", updateActive, { passive: true });
    return () => container.removeEventListener("scroll", updateActive);
  }, [content, toc]);

  useEffect(() => {
    if (!activeTocId) return;
    const tocEl = document.querySelector(".docs-toc");
    const link = document.querySelector<HTMLAnchorElement>(
      `.docs-toc-nav a[href="#${activeTocId}"]`,
    );
    if (!tocEl || !link) return;
    const linkTop = link.offsetTop;
    const linkH = link.offsetHeight;
    const tocH = tocEl.clientHeight;
    const maxScroll = tocEl.scrollHeight - tocH;
    const target = Math.max(
      0,
      Math.min(maxScroll, linkTop - tocH / 2 + linkH / 2),
    );
    tocEl.scrollTo({ top: target, behavior: "smooth" });
  }, [activeTocId]);

  useEffect(() => {
    const container = articleRef.current;
    if (!container) return;
    const onScroll = () => setShowBackToTop(container.scrollTop > 400);
    container.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => container.removeEventListener("scroll", onScroll);
  }, [content]);

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
          <DocSearch lang={lang} initialQuery={isSearchPage ? searchQ : ""} />
          <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {DOC_SLUGS.map((entry) => {
              const { slug: s, titleKey, children } = entry;
              const isParentActive =
                activeSlug === s ||
                (children?.some((c) => c.slug === activeSlug) ?? false);
              return (
                <div key={s}>
                  <Link
                    to={`/docs/${s}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--space-1)",
                      padding: "var(--space-2)",
                      borderRadius: "0.375rem",
                      fontSize: "0.9375rem",
                      color:
                        activeSlug === s ? "var(--text)" : "var(--text-muted)",
                      background:
                        activeSlug === s ? "var(--bg)" : "transparent",
                    }}
                  >
                    <BookOpen size={16} strokeWidth={1.5} aria-hidden />
                    {DOC_TITLES[lang][titleKey] ?? titleKey}
                    {children && children.length > 0 && (
                      <ChevronDown
                        size={14}
                        style={{
                          marginLeft: "auto",
                          transform: isParentActive
                            ? "rotate(0deg)"
                            : "rotate(-90deg)",
                          transition: "transform 0.15s",
                        }}
                      />
                    )}
                    {!children && activeSlug === s && (
                      <ChevronRight size={16} style={{ marginLeft: "auto" }} />
                    )}
                  </Link>
                  {children && isParentActive && (
                    <div style={{ paddingLeft: "1.25rem" }}>
                      {children.map(({ slug: cs, titleKey: ct }) => (
                        <Link
                          key={cs}
                          to={`/docs/${cs}`}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "var(--space-1)",
                            padding: "var(--space-1) var(--space-2)",
                            borderRadius: "0.375rem",
                            fontSize: "0.875rem",
                            color:
                              activeSlug === cs
                                ? "var(--text)"
                                : "var(--text-muted)",
                            background:
                              activeSlug === cs ? "var(--bg)" : "transparent",
                          }}
                        >
                          {DOC_TITLES[lang][ct] ?? ct}
                          {activeSlug === cs && (
                            <ChevronRight
                              size={14}
                              style={{ marginLeft: "auto" }}
                            />
                          )}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
        </aside>
        <main className="docs-main">
          <div className="docs-content-scroll" ref={articleRef}>
            {isSearchPage ? (
              <DocSearchResults lang={lang} query={searchQ} />
            ) : (
              <>
                <article className="docs-content">
                  <LangContext.Provider value={lang}>
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeHighlight]}
                      components={{
                        pre: ({ children, ...props }) => {
                          const langCtx = useContext(LangContext);
                          return (
                            <CodeBlockWithCopy lang={langCtx}>
                              <pre {...props}>{children}</pre>
                            </CodeBlockWithCopy>
                          );
                        },
                        a: ({ href, children }) => {
                          const trimmed = href?.replace(/\.md$/, "") ?? "";
                          const isRelative =
                            trimmed.startsWith("./") ||
                            trimmed.startsWith("/docs/");
                          if (isRelative) {
                            const path = trimmed.startsWith("./")
                              ? "/docs/" + trimmed.slice(2)
                              : trimmed;
                            const [pathname, hash] = path.split("#");
                            const to = hash ? `${pathname}#${hash}` : pathname;
                            return <Link to={to}>{children}</Link>;
                          }
                          return (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {children}
                            </a>
                          );
                        },
                        h2: ({ children }) => {
                          const id = slugifyHeading(headingText(children));
                          return <h2 id={id}>{children}</h2>;
                        },
                        h3: ({ children }) => {
                          const id = slugifyHeading(headingText(children));
                          return <h3 id={id}>{children}</h3>;
                        },
                        table: ({ children }) => (
                          <div className="docs-table-wrap">
                            <table>{children}</table>
                          </div>
                        ),
                        code: ({ className, children, ...props }) => {
                          const match = /language-(\w+)/.exec(className || "");
                          const lang = match?.[1];
                          if (lang === "mermaid") {
                            const chart = String(children).replace(/\n$/, "");
                            return <MermaidBlock chart={chart} />;
                          }
                          // inline code vs block code
                          const isInline = !className;
                          if (isInline) {
                            return (
                              <code className={className} {...props}>
                                {children}
                              </code>
                            );
                          }
                          return (
                            <code className={className} {...props}>
                              {children}
                            </code>
                          );
                        },
                        img: ({ src, alt }) => {
                          const isVideo = /\.(mp4|webm|ogg|mov)(\?|$)/i.test(
                            src ?? "",
                          );
                          if (isVideo) {
                            return (
                              <video src={src ?? undefined} controls>
                                {alt ?? "您的浏览器不支持 video 标签。"}
                              </video>
                            );
                          }
                          return <img src={src ?? undefined} alt={alt ?? ""} />;
                        },
                      }}
                    >
                      {content}
                    </ReactMarkdown>
                  </LangContext.Provider>
                </article>
                <footer
                  className="docs-page-footer"
                  aria-label="Document footer"
                >
                  <Footer lang={lang} />
                </footer>
              </>
            )}
          </div>
          {!isSearchPage && toc.length > 0 && (
            <aside className="docs-toc" aria-label="On this page">
              <nav className="docs-toc-nav">
                {toc.map(({ level, text, id }) => (
                  <a
                    key={id}
                    href={`#${id}`}
                    className={
                      level === 3
                        ? "docs-toc-item docs-toc-item-h3"
                        : "docs-toc-item"
                    }
                    data-active={activeTocId === id ? "true" : undefined}
                    onClick={(e) => {
                      e.preventDefault();
                      const el = document.getElementById(id);
                      if (el && articleRef.current) {
                        const top = Math.max(0, el.offsetTop - 16);
                        articleRef.current.scrollTo({
                          top,
                          behavior: "smooth",
                        });
                        window.history.replaceState(null, "", `#${id}`);
                      }
                    }}
                  >
                    {text}
                  </a>
                ))}
              </nav>
            </aside>
          )}
        </main>
      </div>
      {showBackToTop && (
        <button
          type="button"
          className="docs-back-to-top"
          onClick={() =>
            articleRef.current?.scrollTo({ top: 0, behavior: "smooth" })
          }
          aria-label={t(lang, "docs.backToTop")}
        >
          <ArrowUp size={20} aria-hidden />
          <span>{t(lang, "docs.backToTop")}</span>
        </button>
      )}
      <style>{`
        @media (max-width: 768px) {
          .docs-sidebar { position: fixed; left: 0; top: 3.5rem; bottom: 0; z-index: 20; transform: translateX(-100%); transition: transform 0.2s; }
          .docs-sidebar.open { transform: translateX(0); }
          .docs-sidebar-toggle { display: flex !important; }
        }
      `}</style>
    </>
  );
}
