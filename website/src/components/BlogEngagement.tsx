import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Eye, Heart } from "lucide-react";
import {
  isBlogStatsConfigured,
  recordBlogView,
  toggleBlogLike,
  type BlogStats,
} from "@/lib/blogEngagement";

function formatCount(n: number, locale: string): string {
  try {
    return new Intl.NumberFormat(locale, { notation: "compact" }).format(n);
  } catch {
    return String(n);
  }
}

type BlogEngagementProps = {
  slug: string;
};

/** Article-page views + like control. No-ops when Supabase env is missing. */
export function BlogEngagement({ slug }: BlogEngagementProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const [stats, setStats] = useState<BlogStats | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isBlogStatsConfigured()) return;
    let canceled = false;
    recordBlogView(slug).then((next) => {
      if (!canceled && next) setStats(next);
    });
    return () => {
      canceled = true;
    };
  }, [slug]);

  if (!isBlogStatsConfigured() || !stats) return null;

  const onToggleLike = async () => {
    if (busy) return;
    setBusy(true);
    const next = await toggleBlogLike(slug);
    if (next) setStats(next);
    setBusy(false);
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-(--color-text-tertiary) sm:mt-4 sm:gap-4 sm:text-sm">
      <span
        className="inline-flex items-center gap-1.5"
        title={t("blog.viewsLabel")}
      >
        <Eye size={15} strokeWidth={1.75} aria-hidden />
        <span>
          {t("blog.views", { count: formatCount(stats.views, locale) })}
        </span>
      </span>
      <button
        type="button"
        onClick={onToggleLike}
        disabled={busy}
        className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent p-0 transition-colors disabled:opacity-60 ${
          stats.liked
            ? "text-(--color-primary)"
            : "text-(--color-text-tertiary) hover:text-(--color-primary)"
        }`}
        aria-pressed={stats.liked}
        aria-label={stats.liked ? t("blog.unlike") : t("blog.like")}
        title={stats.liked ? t("blog.unlike") : t("blog.like")}
      >
        <Heart
          size={15}
          strokeWidth={1.75}
          fill={stats.liked ? "currentColor" : "none"}
          aria-hidden
        />
        <span>
          {t("blog.likes", { count: formatCount(stats.likes, locale) })}
        </span>
      </button>
    </div>
  );
}
