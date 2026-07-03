import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft } from "lucide-react";
import { BLOG_POSTS } from "./blogData";
import {
  formatBlogDate,
  parseBlogMarkdown,
  type ParsedBlogPost,
} from "@/lib/parseBlogMarkdown";

type BlogListItem = ParsedBlogPost & { slug: string; cover?: string };

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
  const md = await response.text();
  return parseBlogMarkdown(md, {
    sessionList: slug === DEVELOPER_DAY_COLLECTION_SLUG,
  });
}

function BlogCover({ title, cover }: { title: string; cover?: string }) {
  if (cover) {
    return (
      <img
        src={cover}
        alt=""
        className="block h-full w-full object-cover object-center"
        loading="lazy"
      />
    );
  }
  return (
    <div
      className="flex h-full w-full items-center justify-center bg-linear-to-br from-orange-100 via-amber-50 to-orange-200 px-3 text-center text-xs font-medium text-orange-800/80 md:text-sm"
      aria-hidden
    >
      {title}
    </div>
  );
}

export default function Blog() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const locale = i18n.resolvedLanguage ?? "en";
  const [posts, setPosts] = useState<BlogListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let canceled = false;
    setLoading(true);

    Promise.all(
      BLOG_POSTS.map(async ({ slug, cover }) => {
        const parsed = await fetchBlogPost(slug, isZh);
        if (!parsed) return null;
        return {
          slug,
          cover: cover ?? parsed.frontmatter.cover,
          ...parsed,
        };
      }),
    ).then((results) => {
      if (canceled) return;
      const valid: BlogListItem[] = [];
      for (const item of results) {
        if (item) valid.push(item);
      }
      valid.sort((a, b) => {
        const indexA = BLOG_POSTS.findIndex((entry) => entry.slug === a.slug);
        const indexB = BLOG_POSTS.findIndex((entry) => entry.slug === b.slug);
        return indexA - indexB;
      });
      setPosts(valid);
      setLoading(false);
    });

    return () => {
      canceled = true;
    };
  }, [isZh]);

  return (
    <div className="min-h-screen bg-(--bg)">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 md:py-12">
        <nav
          className="font-inter mb-4 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-(--color-text-tertiary) sm:mb-6 sm:text-sm"
          aria-label="Breadcrumb"
        >
          <Link
            to="/"
            className="inline-flex shrink-0 items-center gap-1 hover:text-(--color-primary)"
          >
            <ArrowLeft size={14} aria-hidden />
            {t("blog.breadcrumbHome")}
          </Link>
          <span className="shrink-0" aria-hidden>
            /
          </span>
          <span className="text-(--color-text)">
            {t("blog.breadcrumbCurrent")}
          </span>
        </nav>

        <header className="mb-4 sm:mb-6">
          <h1 className="font-newsreader text-2xl font-semibold text-(--color-text) sm:text-3xl md:text-4xl">
            {t("blog.title")}
          </h1>
          <p className="font-inter mt-2 text-sm leading-relaxed text-(--color-text-tertiary) md:mt-3 md:text-base">
            {t("blog.subtitle")}
          </p>
        </header>

        <div
          className="mb-6 h-px w-full bg-[#DCC1B2] md:mb-10"
          role="separator"
          aria-hidden
        />

        {loading ? (
          <p className="text-center text-sm text-(--color-text-tertiary)">
            {t("docs.searchLoading")}
          </p>
        ) : posts.length === 0 ? (
          <p className="text-center text-sm text-(--color-text-tertiary)">
            {t("blog.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-4 md:gap-5">
            {posts.map((post) => {
              const { slug, frontmatter, readMinutes, sessionCount, cover } =
                post;
              console.log("frontmatter.date", post);
              const dateLabel = formatBlogDate(frontmatter.date, locale);
              const metaSecondary =
                sessionCount != null
                  ? t("blog.sessionCount", { count: sessionCount })
                  : t("blog.readTime", { minutes: readMinutes });
              const metaPrimary =
                sessionCount != null
                  ? t("blog.latestUpdate", { date: dateLabel })
                  : dateLabel;
              return (
                <li key={slug}>
                  <Link
                    to={`/blog/${slug}`}
                    className="group box-border flex flex-col gap-2.5 border border-[#DCC1B2] bg-[#FFFFFF] p-3 no-underline transition-shadow hover:shadow-md sm:gap-3 md:flex-row md:items-center md:gap-5 md:p-4"
                  >
                    <div className="aspect-[1224/696] w-full shrink-0 md:h-[7.5rem] md:w-auto">
                      <BlogCover title={frontmatter.title} cover={cover} />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col justify-center">
                      <p className="font-inter text-[11px] leading-relaxed text-(--color-text-tertiary) sm:text-xs">
                        {metaPrimary}
                        <span className="mx-1.5">·</span>
                        {metaSecondary}
                      </p>
                      <h2 className="font-newsreader mt-1 text-[15px] font-semibold leading-snug text-(--color-text) group-hover:text-(--color-primary) sm:mt-1.5 sm:text-base md:text-lg">
                        {frontmatter.title}
                      </h2>
                      {frontmatter.excerpt && (
                        <p className="font-inter mt-1 line-clamp-2 text-[13px] leading-relaxed text-(--color-text-tertiary) sm:mt-1.5 sm:text-sm">
                          {frontmatter.excerpt}
                        </p>
                      )}
                      {frontmatter.tags.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1 sm:mt-2 sm:gap-1.5">
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
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
