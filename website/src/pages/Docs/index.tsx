import { useState, useEffect, useMemo, useRef } from "react";
import {
  Link,
  useParams,
  useNavigate,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Menu, ChevronRight, ArrowUp } from "lucide-react";
import { DocSearchResults } from "@/components/DocSearchResults";
import { FeatureDemoGallery } from "@/components/FeatureDemoGallery";
import { parseToc } from "./markdown";
import {
  DOC_GROUPS,
  ALL_SLUGS,
  DOC_BANNER_BY_SLUG,
  FALLBACK_DOC_BANNER,
  fetchDocContent,
} from "./navigation";
import { DocsSidebar } from "./components/DocsSidebar";
import { DocsToc } from "./components/DocsToc";
import { DocMarkdown } from "./components/DocMarkdown";
import { FaqArticle } from "./components/FaqArticle";

export default function Docs() {
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
  const titleBannerSrc = useMemo(
    () => DOC_BANNER_BY_SLUG.get(activeSlug) ?? FALLBACK_DOC_BANNER,
    [activeSlug],
  );
  const mobileBreadcrumb = useMemo<{ parent?: string; current: string }>(() => {
    const currentEntry = DOC_GROUPS.flatMap((g) => g.children).find(
      (entry) => entry.slug === activeSlug,
    );
    if (!currentEntry) {
      return { parent: t("docs.groupWelcome"), current: t("docs.intro") };
    }
    const group = DOC_GROUPS.find((g) =>
      g.children.some((entry) => entry.slug === activeSlug),
    );
    return {
      parent: group ? t(group.titleKey) : undefined,
      current: t(currentEntry.titleKey),
    };
  }, [activeSlug, t]);

  const flatDocNav = useMemo(() => {
    const out: Array<{ slug: string; title: string }> = [];
    for (const group of DOC_GROUPS) {
      for (const entry of group.children) {
        out.push({ slug: entry.slug, title: t(entry.titleKey) });
      }
    }
    return out;
  }, [t]);

  const { prevDoc, nextDoc } = useMemo(() => {
    const idx = flatDocNav.findIndex((d) => d.slug === activeSlug);
    return {
      prevDoc: idx > 0 ? flatDocNav[idx - 1] : null,
      nextDoc:
        idx >= 0 && idx < flatDocNav.length - 1 ? flatDocNav[idx + 1] : null,
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
        (target.getBoundingClientRect().top -
          container.getBoundingClientRect().top) -
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
        ? Array.from(document.querySelectorAll(".docs-toc-nav a")).indexOf(
            byHref,
          )
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
    if (activeSlug === "functiondemo") {
      setContent("");
      return;
    }
    let cancelled = false;
    fetchDocContent(activeSlug, lang).then((text) => {
      if (!cancelled) setContent(text);
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

  const handleTocItemClick = (id: string, idx: number) => {
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
    window.history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  };

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
        <DocsSidebar
          activeSlug={activeSlug}
          lang={lang}
          open={sidebarOpen}
          onToggle={() => setSidebarOpen((o) => !o)}
          onNavigate={() => setSidebarOpen(false)}
          searchQuery={isSearchPage ? searchQ : ""}
        />
        <main className="docs-main relative min-w-0">
          <div className="docs-content-scroll" ref={articleRef}>
            <div className="sticky -top-px z-20 border-b border-border/60 bg-(--surface) pb-3 md:hidden">
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
                  {mobileBreadcrumb.parent && (
                    <>
                      <span className="align-middle text-(--text-muted)">
                        {mobileBreadcrumb.parent}
                      </span>
                      <ChevronRight
                        size={16}
                        className="mx-1 inline align-middle text-(--text-muted)"
                      />
                    </>
                  )}
                  <span className="align-middle font-semibold text-(--text)">
                    {mobileBreadcrumb.current}
                  </span>
                </div>
              </div>
            </div>
            {isSearchPage ? (
              <DocSearchResults query={searchQ} />
            ) : (
              <article className="docs-content">
                {activeSlug === "functiondemo" && (
                  <>
                    <h1>{t("docs.demoTitle")}</h1>
                    <FeatureDemoGallery />
                  </>
                )}
                {activeSlug === "faq" && (
                  <FaqArticle content={content} bannerSrc={titleBannerSrc} />
                )}
                {activeSlug !== "faq" && activeSlug !== "functiondemo" && (
                  <DocMarkdown content={content} bannerSrc={titleBannerSrc} />
                )}

                {(prevDoc || nextDoc) && (
                  <div className="mt-10 px-4 py-8 md:px-6">
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

                      {nextDoc && (
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
                      )}
                    </div>
                  </div>
                )}
              </article>
            )}
          </div>
          {!isSearchPage && toc.length > 0 && (
            <DocsToc
              toc={toc}
              activeTocId={activeTocId}
              onItemClick={handleTocItemClick}
            />
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
        </button>
      )}
    </>
  );
}
