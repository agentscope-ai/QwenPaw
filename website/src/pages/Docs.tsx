import { useState, useEffect, useMemo, useRef } from "react";
import {
  Link,
  useParams,
  useNavigate,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import {
  BookOpen,
  Rocket,
  Zap,
  Terminal,
  MessageSquare,
  Wrench,
  Plug,
  Brain,
  Archive,
  Command,
  Activity,
  Settings,
  Shield,
  CircleHelp,
  Users,
  GitBranch,
  Map as MapIcon,
  Menu,
  Cpu,
  ChevronRight,
  ChevronDown,
  ArrowUp,
  Copy,
  Check,
  type LucideIcon,
} from "lucide-react";
import { MermaidBlock } from "@/components/MermaidBlock";
import { DocSearch } from "@/components/DocSearch";
import { DocSearchResults } from "@/components/DocSearchResults";
/* Code block theme: defined in index.css for high contrast */

function CodeBlockWithCopy({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
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
        aria-label={t("docs.copy")}
        title={t("docs.copy")}
      >
        {copied ? (
          <>
            <Check size={14} aria-hidden />
            <span>{t("docs.copied")}</span>
          </>
        ) : (
          <>
            <Copy size={14} aria-hidden />
            <span>{t("docs.copy")}</span>
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
  const idCounter = new Map<string, number>();
  const re = /^#{2,3}\s+(.+)$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(md)) !== null) {
    const level = m[0].startsWith("###") ? 3 : 2;
    const text = m[1].replace(/#+\s*$/, "").trim();
    const baseId = slugifyHeading(text);
    const count = (idCounter.get(baseId) ?? 0) + 1;
    idCounter.set(baseId, count);
    const id = count === 1 ? baseId : `${baseId}-${count}`;
    toc.push({ level, text, id });
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

interface FaqItem {
  question: string;
  answer: string;
}

function parseFaqContent(md: string): { intro: string; items: FaqItem[] } {
  const lines = md.split("\n");
  const introLines: string[] = [];
  const items: FaqItem[] = [];
  let currentQuestion: string | null = null;
  let currentAnswerLines: string[] = [];

  const flush = () => {
    if (!currentQuestion) return;
    items.push({
      question: currentQuestion,
      answer: currentAnswerLines.join("\n").trim(),
    });
    currentQuestion = null;
    currentAnswerLines = [];
  };

  for (const line of lines) {
    const m = line.match(/^###\s+(.+)$/);
    if (m) {
      flush();
      currentQuestion = m[1].trim();
      continue;
    }
    if (currentQuestion === null) introLines.push(line);
    else currentAnswerLines.push(line);
  }
  flush();

  return {
    intro: introLines.join("\n").trim(),
    items,
  };
}

const DOC_SLUG_ICONS: Record<string, LucideIcon> = {
  intro: Rocket,
  quickstart: Zap,
  console: Terminal,
  "multi-agent": Users,
  models: Cpu,
  channels: MessageSquare,
  skills: Wrench,
  mcp: Plug,
  memory: Brain,
  context: Archive,
  commands: Command,
  heartbeat: Activity,
  config: Settings,
  security: Shield,
  cli: Terminal,
  faq: CircleHelp,
  community: Users,
  contributing: GitBranch,
  roadmap: MapIcon,
};

const DOC_SLUGS: DocEntry[] = [
  { slug: "intro", titleKey: "docs.intro" },
  {
    slug: "quickstart",
    titleKey: "docs.quickstart",
    children: [{ slug: "desktop", titleKey: "docs.desktop" }],
  },
  {
    slug: "console",
    titleKey: "docs.console",
    children: [{ slug: "multi-agent", titleKey: "docs.multiAgent" }],
  },
  { slug: "models", titleKey: "docs.models" },
  { slug: "channels", titleKey: "docs.channels" },
  { slug: "skills", titleKey: "docs.skills" },
  { slug: "mcp", titleKey: "docs.mcp" },
  { slug: "memory", titleKey: "docs.memory" },
  { slug: "context", titleKey: "docs.context" },
  { slug: "commands", titleKey: "docs.commands" },
  { slug: "heartbeat", titleKey: "docs.heartbeat" },
  { slug: "config", titleKey: "docs.config" },
  { slug: "security", titleKey: "docs.security" },
  { slug: "cli", titleKey: "docs.cli" },
  { slug: "faq", titleKey: "docs.faq" },
  { slug: "community", titleKey: "docs.community" },
  { slug: "contributing", titleKey: "docs.contributing" },
  { slug: "roadmap", titleKey: "docs.roadmap" },
];

/** Collect all valid slugs (parents + children). */
const ALL_SLUGS = [
  ...DOC_SLUGS.flatMap((d) => [
    d.slug,
    ...(d.children?.map((c) => c.slug) ?? []),
  ]),
  "comparison", // Hidden page, accessible only via FAQ link
];

export function Docs() {
  const { t, i18n } = useTranslation();
  const lang: "zh" | "en" = i18n.resolvedLanguage === "zh" ? "zh" : "en";
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
  const ignoredHashRef = useRef<string | null>(null);
  const isTocClickScrollingRef = useRef(false);
  const tocClickScrollUnlockTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const [openFaqSet, setOpenFaqSet] = useState<Set<number>>(() => new Set([0]));
  const faqData = useMemo(() => parseFaqContent(content), [content]);
  const headingIdCounter = new Map<string, number>();
  const getHeadingId = (children: React.ReactNode) => {
    const baseId = slugifyHeading(headingText(children));
    const count = (headingIdCounter.get(baseId) ?? 0) + 1;
    headingIdCounter.set(baseId, count);
    return count === 1 ? baseId : `${baseId}-${count}`;
  };
  const mobileBreadcrumb = useMemo(() => {
    for (const entry of DOC_SLUGS) {
      if (entry.slug === activeSlug) {
        return { current: t(entry.titleKey) };
      }
      const child = entry.children?.find((c) => c.slug === activeSlug);
      if (child) {
        return { parent: t(entry.titleKey), current: t(child.titleKey) };
      }
    }
    return { current: t("docs.intro") };
  }, [activeSlug, t]);

  const flatDocNav = useMemo(() => {
    const out: Array<{ slug: string; title: string }> = [];
    for (const entry of DOC_SLUGS) {
      out.push({ slug: entry.slug, title: t(entry.titleKey) });
      for (const child of entry.children ?? []) {
        out.push({ slug: child.slug, title: t(child.titleKey) });
      }
    }
    return out;
  }, [t]);

  const { prevDoc, nextDoc } = useMemo(() => {
    const idx = flatDocNav.findIndex((d) => d.slug === activeSlug);
    return {
      prevDoc: idx > 0 ? flatDocNav[idx - 1] : null,
      nextDoc: idx >= 0 && idx < flatDocNav.length - 1 ? flatDocNav[idx + 1] : null,
    };
  }, [activeSlug, flatDocNav]);

  const getTocTargets = () => {
    const container = articleRef.current;
    if (!container) return [];
    // Keep the same order as parseToc: h2/h3 in document flow,
    // plus FAQ sections that carry ids.
    return Array.from(
      container.querySelectorAll<HTMLElement>(
        ".docs-content h2[id], .docs-content h3[id], .docs-content section[id]",
      ),
    );
  };

  const getTopInContainer = (container: HTMLElement, target: HTMLElement) => {
    return Math.max(
      0,
      container.scrollTop +
        (target.getBoundingClientRect().top - container.getBoundingClientRect().top) -
        16,
    );
  };

  useEffect(() => {
    const el = articleRef.current;
    if (!el) return;
    if (!location.hash) el.scrollTo(0, 0);
  }, [activeSlug, location.pathname]);

  useEffect(() => {
    if (isTocClickScrollingRef.current) return;
    const rawHash = location.hash?.slice(1) ?? "";
    const hash = rawHash ? decodeURIComponent(rawHash.replace(/\+/g, " ")) : "";
    if (!hash) return;
    if (ignoredHashRef.current && ignoredHashRef.current !== hash) {
      ignoredHashRef.current = null;
    }
    if (ignoredHashRef.current === hash) return;

    const scrollToHash = (): boolean => {
      const container = articleRef.current;
      if (!container) return false;
      const byId = container.querySelector<HTMLElement>(`#${hash}`);
      const byHref = document.querySelector<HTMLAnchorElement>(
        `.docs-toc-nav a[href="#${hash}"]`,
      );
      const idx = byHref
        ? Array.from(document.querySelectorAll(".docs-toc-nav a")).indexOf(byHref)
        : -1;
      const targets = getTocTargets();
      const target = byId ?? (idx >= 0 ? targets[idx] : null);
      if (!target) return false;
      container.scrollTo({
        top: getTopInContainer(container, target),
        behavior: "auto",
      });
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
      if (isTocClickScrollingRef.current) return;
      const containerTop = container.getBoundingClientRect().top;
      const trigger = containerTop + 120;
      let current: string | null = null;
      const targets = getTocTargets();
      for (let i = 0; i < toc.length; i += 1) {
        const el = targets[i];
        const { id } = toc[i];
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
    if (isTocClickScrollingRef.current) return;
    const tocEl = document.querySelector(".docs-toc");
    const link = document.querySelector<HTMLAnchorElement>(
      `.docs-toc-nav a[href="#${activeTocId}"]`,
    );
    if (!tocEl || !link) return;
    const linkTop = link.offsetTop;
    const linkH = link.offsetHeight;
    const tocH = tocEl.clientHeight;
    const maxScroll = tocEl.scrollHeight - tocH;
    const currentTop = tocEl.scrollTop;
    const currentBottom = currentTop + tocH;
    const linkBottom = linkTop + linkH;
    const isVisible = linkTop >= currentTop && linkBottom <= currentBottom;
    if (isVisible) return;
    const target = Math.max(
      0,
      Math.min(maxScroll, linkTop - tocH / 2 + linkH / 2),
    );
    tocEl.scrollTo({ top: target, behavior: "auto" });
  }, [activeTocId]);

  useEffect(() => {
    const container = articleRef.current;
    if (!container) return;
    const onScroll = () => setShowBackToTop(container.scrollTop > 400);
    container.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => container.removeEventListener("scroll", onScroll);
  }, [content]);

  useEffect(() => {
    return () => {
      if (tocClickScrollUnlockTimerRef.current) {
        clearTimeout(tocClickScrollUnlockTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [activeSlug, isSearchPage, searchQ]);

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
            "docs-sidebar z-40 w-64 shrink-0 border-r border-border bg-(--surface) px-2 py-4",
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
          <DocSearch initialQuery={isSearchPage ? searchQ : ""} />
          <nav className="flex flex-col gap-0.5">
            {DOC_SLUGS.map((entry) => {
              const { slug: s, titleKey, children } = entry;
              const isParentActive =
                activeSlug === s ||
                (children?.some((c) => c.slug === activeSlug) ?? false);
              const ParentIcon = DOC_SLUG_ICONS[s] ?? BookOpen;
              return (
                <div key={s}>
                  <Link
                    to={`/docs/${s}`}
                    className={[
                      "flex items-center gap-1 rounded-md px-2 py-2 text-[0.9375rem] transition-colors",
                      activeSlug === s
                        ? "bg-(--bg) text-(--text)"
                        : "text-(--text-muted) hover:bg-(--bg)/60 hover:text-(--text)",
                    ].join(" ")}
                    onClick={() => setSidebarOpen(false)}
                  >
                    <ParentIcon size={16} strokeWidth={1.5} aria-hidden />
                    {t(titleKey)}
                    {children && children.length > 0 && (
                      <ChevronDown
                        size={14}
                        className={[
                          "ml-auto transition-transform duration-150",
                          isParentActive ? "rotate-0" : "-rotate-90",
                        ].join(" ")}
                      />
                    )}
                    {!children && activeSlug === s && (
                      <ChevronRight size={16} className="ml-auto" />
                    )}
                  </Link>
                  {children && isParentActive && (
                    <div className="pl-5">
                      {children.map(({ slug: cs, titleKey: ct }) => {
                        const ChildIcon = DOC_SLUG_ICONS[cs] ?? BookOpen;
                        return (
                          <Link
                            key={cs}
                            to={`/docs/${cs}`}
                            className={[
                              "flex items-center gap-1 rounded-md px-2 py-1 text-sm transition-colors",
                              activeSlug === cs
                                ? "bg-(--bg) text-(--text)"
                                : "text-(--text-muted) hover:bg-(--bg)/60 hover:text-(--text)",
                            ].join(" ")}
                            onClick={() => setSidebarOpen(false)}
                          >
                            <ChildIcon
                              size={14}
                              strokeWidth={1.5}
                              aria-hidden
                            />
                            {t(ct)}
                            {activeSlug === cs && (
                              <ChevronRight size={14} className="ml-auto" />
                            )}
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
        </aside>
        <main className="docs-main relative min-w-0">
          <div className="docs-content-scroll" ref={articleRef}>
            <div className="sticky -top-px z-20 border-y border-border/60 bg-(--surface) py-3 md:hidden">
              <div
                className="flex items-center gap-2"
                onClick={() => setSidebarOpen((o) => !o)}
              >
                <button
                  type="button"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-md text-(--text-muted) hover:bg-(--bg)"
                  aria-label={
                    sidebarOpen
                      ? t("docs.closeSidebar")
                      : t("docs.toggleSidebar")
                  }
                >
                  <Menu size={20} />
                </button>
                <div className="min-w-0 text-base">
                  {mobileBreadcrumb.parent ? (
                    <>
                      <span className="align-middle text-(--text-muted)">
                        {mobileBreadcrumb.parent}
                      </span>
                      <ChevronRight
                        size={16}
                        className="mx-1 inline align-middle text-(--text-muted)"
                      />
                    </>
                  ) : null}
                  <span className="align-middle font-semibold text-(--text)">
                    {mobileBreadcrumb.current}
                  </span>
                </div>
              </div>
            </div>
            {isSearchPage ? (
              <DocSearchResults query={searchQ} />
            ) : (
              <>
                <article className="docs-content">
                  {activeSlug === "faq" ? (
                    <>
                      {faqData.intro ? (
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeRaw, rehypeHighlight]}
                          components={{
                            h2: ({ children }) => {
                              const id = getHeadingId(children);
                              return <h2 id={id}>{children}</h2>;
                            },
                            h3: ({ children }) => {
                              const id = getHeadingId(children);
                              return <h3 id={id}>{children}</h3>;
                            },
                          }}
                        >
                          {faqData.intro}
                        </ReactMarkdown>
                      ) : null}
                      <div className="mt-4">
                        {faqData.items.map((item, idx) => {
                          const opened = openFaqSet.has(idx);
                          const questionId = getHeadingId(item.question);
                          return (
                            <section
                              key={`${item.question}-${idx}`}
                              id={questionId}
                              className="mb-3 rounded-lg border border-border bg-(--surface)"
                            >
                              <button
                                type="button"
                                onClick={() => {
                                  setOpenFaqSet((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(idx)) next.delete(idx);
                                    else next.add(idx);
                                    return next;
                                  });
                                }}
                                className="flex w-full items-center justify-between gap-3 bg-transparent px-4 py-4 text-left text-base font-semibold text-(--text)"
                                aria-expanded={opened}
                              >
                                <span>{item.question}</span>
                                <ChevronDown
                                  size={16}
                                  className={[
                                    "shrink-0 transition-transform duration-150 ease-in-out",
                                    opened ? "rotate-180" : "rotate-0",
                                  ].join(" ")}
                                />
                              </button>
                                {opened ? (
                                <div className="docs-faq-answer border-t border-border px-4 pb-2 pt-3 *:first:mt-0 *:last:mb-0">
                                  <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    rehypePlugins={[rehypeRaw, rehypeHighlight]}
                                  >
                                    {item.answer}
                                  </ReactMarkdown>
                                </div>
                              ) : null}
                            </section>
                          );
                        })}
                      </div>
                    </>
                  ) : (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeRaw, rehypeHighlight]}
                      components={{
                        pre: ({ children, ...props }) => {
                          return (
                            <CodeBlockWithCopy>
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
                          const id = getHeadingId(children);
                          return <h2 id={id}>{children}</h2>;
                        },
                        h3: ({ children }) => {
                          const id = getHeadingId(children);
                          return <h3 id={id}>{children}</h3>;
                        },
                        table: ({ children }) => (
                          <div className="docs-table-wrap">
                            <table>{children}</table>
                          </div>
                        ),
                        code: ({ className, children, ...props }) => {
                          const match = /language-(\w+)/.exec(className || "");
                          const langCode = match?.[1];
                          if (langCode === "mermaid") {
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
                                {alt ?? t("docs.videoNotSupported")}
                              </video>
                            );
                          }
                          return <img src={src ?? undefined} alt={alt ?? ""} />;
                        },
                      }}
                    >
                      {content}
                    </ReactMarkdown>
                  )}

                  {!isSearchPage && (prevDoc || nextDoc) ? (
                    <div className="mt-10 rounded-xl border border-(--border) bg-(--surface) px-4 py-4 md:px-6">
                      <div className="flex items-center justify-between gap-4">
                        {prevDoc ? (
                          <Link
                            to={`/docs/${prevDoc.slug}`}
                            className="group inline-flex min-w-0 items-center gap-2 text-sm font-semibold text-(--color-text) no-underline hover:!text-(--color-primary) hover:no-underline"
                            style={{ textDecoration: "none" }}
                          >
                            <ChevronRight
                              size={16}
                              className="shrink-0 rotate-180 text-(--text-muted) group-hover:text-(--color-primary)"
                              aria-hidden
                            />
                            <span className="truncate group-hover:text-(--color-primary)">
                              {prevDoc.title}
                            </span>
                          </Link>
                        ) : (
                          <span />
                        )}

                        {nextDoc ? (
                          <Link
                            to={`/docs/${nextDoc.slug}`}
                            className="group inline-flex min-w-0 items-center justify-end gap-2 text-sm font-semibold text-(--color-text) no-underline hover:!text-(--color-primary) hover:no-underline"
                            style={{ textDecoration: "none" }}
                          >
                            <span className="truncate group-hover:text-(--color-primary)">
                              {nextDoc.title}
                            </span>
                            <ChevronRight
                              size={16}
                              className="shrink-0 text-(--text-muted) group-hover:text-(--color-primary)"
                              aria-hidden
                            />
                          </Link>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </article>
              </>
            )}
          </div>
          {!isSearchPage && toc.length > 0 && (
            <aside className="docs-toc" aria-label={t("docs.onThisPage")}>
              <nav className="docs-toc-nav">
                {toc.map(({ level, text, id }, idx) => (
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
                      const container = articleRef.current;
                      if (!container) return;
                      isTocClickScrollingRef.current = true;
                      setActiveTocId(id);
                      if (tocClickScrollUnlockTimerRef.current) {
                        clearTimeout(tocClickScrollUnlockTimerRef.current);
                      }
                      const targets = getTocTargets();
                      const top = targets[idx];
                      if (top) {
                        container.scrollTo({
                          top: getTopInContainer(container, top),
                          behavior: "auto",
                        });
                      } else {
                        const el = container.querySelector<HTMLElement>(`#${id}`);
                        if (!el) return;
                        container.scrollTo({
                          top: getTopInContainer(container, el),
                          behavior: "auto",
                        });
                      }
                      tocClickScrollUnlockTimerRef.current = setTimeout(() => {
                        isTocClickScrollingRef.current = false;
                      }, 120);
                      ignoredHashRef.current = id;
                      window.history.replaceState(
                        null,
                        "",
                        `#${encodeURIComponent(id)}`,
                      );
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
          aria-label={t("docs.backToTop")}
        >
          <ArrowUp size={20} aria-hidden />
          <span>{t("docs.backToTop")}</span>
        </button>
      )}
    </>
  );
}