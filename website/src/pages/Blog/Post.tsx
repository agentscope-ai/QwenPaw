import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { BLOG_POSTS, getNextBlogSlug, getPrevBlogSlug } from "./blogData";
import {
  compareBlogPostsByDateDesc,
  formatBlogDate,
  parseBlogMarkdown,
  type ParsedBlogPost,
} from "@/lib/parseBlogMarkdown";
import { MermaidBlock } from "@/components/MermaidBlock";
import { ImageZoom } from "@/components/ImageZoom";
import { trackBlogPostView } from "@/lib/analytics";
import { BlogEngagement } from "@/components/BlogEngagement";
import { BlogRelatedCard } from "@/components/BlogRelatedCard";

/** Turn plain "Meeting link: https://…" lines into markdown links for session lists. */
function linkifySessionUrls(body: string): string {
  return body.replace(
    /^((?:会议链接|Meeting link)[：:]\s*)(https?:\/\/\S+)$/gm,
    (_, prefix, url) => `${prefix}[${url}](${url})`,
  );
}

const DEVELOPER_DAY_COLLECTION_SLUG = "qwenpaw-developer-day-collection";

async function fetchBlogPost(
  slug: string,
  isZh: boolean,
): Promise<ParsedBlogPost | null> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") || "";
  const langSuffix = isZh ? "zh" : "en";
  let response = await fetch(`${base}/blog/${slug}.${langSuffix}.md`);
  if (!response.ok && isZh) {
    response = await fetch(`${base}/blog/${slug}.en.md`);
  }
  if (!response.ok) return null;
  return parseBlogMarkdown(await response.text(), {
    sessionList: slug === DEVELOPER_DAY_COLLECTION_SLUG,
  });
}

function BlogPostShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-(--bg)">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 md:py-12">
        {children}
      </div>
    </div>
  );
}

export default function BlogPost() {
  const { slug } = useParams<{ slug: string }>();
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const locale = i18n.resolvedLanguage ?? "en";
  const [post, setPost] = useState<ParsedBlogPost | null>(null);
  const [adjacentPost, setAdjacentPost] = useState<{
    slug: string;
    title: string;
    direction: "next" | "prev";
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const isKnownSlug = BLOG_POSTS.some((entry) => entry.slug === slug);
  const isSessionList = slug === "qwenpaw-developer-day-collection";

  useEffect(() => {
    if (!slug || !isKnownSlug) {
      setNotFound(true);
      setLoading(false);
      return;
    }

    let canceled = false;
    setLoading(true);
    setNotFound(false);

    fetchBlogPost(slug, isZh).then((parsed) => {
      if (canceled) return;
      if (!parsed) {
        setNotFound(true);
        setPost(null);
      } else {
        setPost(parsed);
        trackBlogPostView({
          slug,
          title: parsed.frontmatter.title,
          lang: isZh ? "zh" : "en",
        });
      }
      setLoading(false);
    });

    return () => {
      canceled = true;
    };
  }, [slug, isZh, isKnownSlug]);

  useEffect(() => {
    if (!slug || !isKnownSlug) {
      setAdjacentPost(null);
      return;
    }

    let canceled = false;
    Promise.all(
      BLOG_POSTS.map(async ({ slug: entrySlug }) => {
        const parsed = await fetchBlogPost(entrySlug, isZh);
        return parsed ? { slug: entrySlug, ...parsed } : null;
      }),
    ).then((results) => {
      if (canceled) return;

      const posts = results.filter(
        (item): item is ParsedBlogPost & { slug: string } => item != null,
      );
      const sorted = [...posts].sort(compareBlogPostsByDateDesc);
      const sortedSlugs = sorted.map((item) => item.slug);

      const currentIndex = sortedSlugs.indexOf(slug);
      const isLast = currentIndex === sortedSlugs.length - 1;
      const adjacentSlug = isLast
        ? getPrevBlogSlug(slug, sortedSlugs)
        : getNextBlogSlug(slug, sortedSlugs);

      if (!adjacentSlug) {
        setAdjacentPost(null);
        return;
      }

      const adjacent = sorted.find((item) => item.slug === adjacentSlug);
      if (adjacent) {
        setAdjacentPost({
          slug: adjacentSlug,
          title: adjacent.frontmatter.title,
          direction: isLast ? "prev" : "next",
        });
      } else {
        setAdjacentPost(null);
      }
    });

    return () => {
      canceled = true;
    };
  }, [slug, isZh, isKnownSlug]);

  if (loading) {
    return (
      <BlogPostShell>
        <p className="py-8 text-center text-sm text-(--color-text-tertiary)">
          {t("docs.searchLoading")}
        </p>
      </BlogPostShell>
    );
  }

  if (notFound || !post) {
    return (
      <BlogPostShell>
        <div className="py-8 text-center">
          <p className="text-sm text-(--color-text-tertiary)">
            {t("blog.notFound")}
          </p>
          <Link
            to="/blog"
            className="mt-4 inline-block text-sm text-(--color-primary)"
          >
            {t("blog.backToList")}
          </Link>
        </div>
      </BlogPostShell>
    );
  }

  const { frontmatter, body, readMinutes, sessionCount } = post;
  const dateLabel = formatBlogDate(frontmatter.date, locale);

  return (
    <BlogPostShell>
      <article>
        <nav
          className="font-inter mb-4 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-(--color-text-tertiary) sm:mb-6 sm:text-sm"
          aria-label="Breadcrumb"
        >
          <Link
            to="/blog"
            className="inline-flex shrink-0 items-center gap-1 hover:text-(--color-primary)"
          >
            <ArrowLeft size={14} aria-hidden />
            {t("blog.breadcrumbCurrent")}
          </Link>
          <span className="shrink-0" aria-hidden>
            /
          </span>
          <span className="min-w-0 truncate text-(--color-text) md:max-w-md">
            {frontmatter.title}
          </span>
        </nav>

        <header className="mb-5 border-b border-[#DCC1B2] pb-5 sm:mb-6 sm:pb-6">
          {frontmatter.tags.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5 sm:mb-3">
              {frontmatter.tags.map((tag) => (
                <span
                  key={tag}
                  className="box-border border border-[#DCC1B2] bg-[#FFFFFF] px-2 py-px text-[10px] text-(--color-text-tertiary) sm:px-2.5 sm:py-0.5 sm:text-xs"
                >
                  #{tag}
                </span>
              ))}
            </div>
          )}
          <h1 className="font-newsreader text-2xl font-semibold leading-tight text-(--color-text) sm:text-3xl md:text-4xl">
            {frontmatter.title}
          </h1>
          <p className="font-inter mt-2 flex flex-wrap gap-x-1.5 gap-y-0.5 text-[11px] leading-relaxed text-(--color-text-tertiary) sm:mt-3 sm:text-sm">
            <span>
              {isSessionList
                ? t("blog.latestUpdate", { date: dateLabel })
                : dateLabel}
            </span>
            {!isSessionList && frontmatter.author && (
              <>
                <span aria-hidden>·</span>
                <span>{frontmatter.author}</span>
              </>
            )}
            <span aria-hidden>·</span>
            <span>
              {sessionCount != null
                ? t("blog.sessionCount", { count: sessionCount })
                : t("blog.readTime", { minutes: readMinutes })}
            </span>
          </p>
          {slug ? <BlogEngagement slug={slug} /> : null}
        </header>

        {frontmatter.related ? (
          <BlogRelatedCard related={frontmatter.related} />
        ) : null}

        <div
          className={`docs-content blog-content${
            isSessionList ? " blog-content--sessions" : ""
          }`}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw, rehypeHighlight]}
            components={{
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={
                    isSessionList
                      ? "break-all"
                      : "break-all text-(--color-primary) underline-offset-2 hover:underline"
                  }
                >
                  {children}
                </a>
              ),
              table: ({ children }) => (
                <div className="docs-table-wrap">
                  <table>{children}</table>
                </div>
              ),
              code: ({ className, children, ...props }) => {
                const match = /language-(\w+)/.exec(className || "");
                if (match?.[1] === "mermaid") {
                  const chart = String(children).replace(/\n$/, "");
                  return <MermaidBlock chart={chart} />;
                }
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              },
              img: ({ src, alt, className }) => (
                <ImageZoom
                  src={src ?? ""}
                  alt={alt ?? ""}
                  className={className}
                />
              ),
            }}
          >
            {isSessionList ? linkifySessionUrls(body) : body}
          </ReactMarkdown>
        </div>

        <nav
          className="mt-8 flex items-start justify-end gap-4 border-t border-[#DCC1B2] pt-5 sm:mt-10 sm:justify-between sm:pt-6"
          aria-label="Post navigation"
        >
          <Link
            to="/blog"
            className="hidden shrink-0 items-center gap-1 text-sm font-medium text-(--color-primary) hover:underline sm:inline-flex"
          >
            <ArrowLeft size={14} aria-hidden />
            {t("blog.backToList")}
          </Link>
          {adjacentPost && (
            <Link
              to={`/blog/${adjacentPost.slug}`}
              className="inline-flex min-w-0 max-w-[min(100%,20rem)] items-center gap-1 text-sm font-medium text-(--color-primary) hover:underline sm:max-w-md"
            >
              {adjacentPost.direction === "prev" && (
                <ArrowLeft size={14} className="shrink-0" aria-hidden />
              )}
              <span className="truncate">{adjacentPost.title}</span>
              {adjacentPost.direction === "next" && (
                <ArrowRight size={14} className="shrink-0" aria-hidden />
              )}
            </Link>
          )}
        </nav>
      </article>
    </BlogPostShell>
  );
}
