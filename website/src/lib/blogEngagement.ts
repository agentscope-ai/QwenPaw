import {
  getSupabase,
  isBlogStatsConfigured,
  type BlogStatsRow,
} from "./supabase";

const VIEWED_PREFIX = "qwenpaw:blog:viewed:";
const LIKED_PREFIX = "qwenpaw:blog:liked:";

const pendingLikeToggles = new Set<string>();

export type BlogStats = {
  views: number;
  likes: number;
  liked: boolean;
};

function viewedKey(slug: string) {
  return `${VIEWED_PREFIX}${slug}`;
}

function likedKey(slug: string) {
  return `${LIKED_PREFIX}${slug}`;
}

export function hasLikedLocally(slug: string): boolean {
  try {
    return localStorage.getItem(likedKey(slug)) === "1";
  } catch {
    return false;
  }
}

function markLikedLocally(slug: string, liked: boolean) {
  try {
    if (liked) localStorage.setItem(likedKey(slug), "1");
    else localStorage.removeItem(likedKey(slug));
  } catch {
    /* ignore quota / private mode */
  }
}

function hasViewedThisSession(slug: string): boolean {
  try {
    return sessionStorage.getItem(viewedKey(slug)) === "1";
  } catch {
    return false;
  }
}

function markViewedThisSession(slug: string) {
  try {
    sessionStorage.setItem(viewedKey(slug), "1");
  } catch {
    /* ignore */
  }
}

function rowToStats(row: BlogStatsRow | null, slug: string): BlogStats {
  return {
    views: row?.views ?? 0,
    likes: row?.likes ?? 0,
    liked: hasLikedLocally(slug),
  };
}

/** Fetch stats for one post (no side effects). */
export async function fetchBlogStats(slug: string): Promise<BlogStats | null> {
  const sb = getSupabase();
  if (!sb) return null;

  const { data, error } = await sb
    .from("blog_stats")
    .select("slug, views, likes")
    .eq("slug", slug)
    .maybeSingle();

  if (error) {
    console.warn("[blogStats] fetch failed", error.message);
    return null;
  }

  return rowToStats(data as BlogStatsRow | null, slug);
}

/** Batch-fetch view counts for the blog list. */
export async function fetchBlogViewCounts(
  slugs: string[],
): Promise<Record<string, number>> {
  const sb = getSupabase();
  if (!sb || slugs.length === 0) return {};

  const { data, error } = await sb
    .from("blog_stats")
    .select("slug, views")
    .in("slug", slugs);

  if (error) {
    console.warn("[blogStats] batch fetch failed", error.message);
    return {};
  }

  const out: Record<string, number> = {};
  for (const row of data ?? []) {
    out[(row as { slug: string; views: number }).slug] =
      (row as { slug: string; views: number }).views ?? 0;
  }
  return out;
}

/**
 * Record one view per browser tab session, then return latest stats.
 * Safe to call on every article mount.
 */
export async function recordBlogView(slug: string): Promise<BlogStats | null> {
  const sb = getSupabase();
  if (!sb) return null;

  if (hasViewedThisSession(slug)) {
    return fetchBlogStats(slug);
  }

  const { data, error } = await sb.rpc("increment_blog_view", {
    p_slug: slug,
  });

  if (error) {
    console.warn("[blogStats] view increment failed", error.message);
    return fetchBlogStats(slug);
  }

  markViewedThisSession(slug);
  return rowToStats(data as BlogStatsRow, slug);
}

/** Toggle like using localStorage ownership + RPC increment/decrement. */
export async function toggleBlogLike(slug: string): Promise<BlogStats | null> {
  const sb = getSupabase();
  if (!sb) return null;

  if (pendingLikeToggles.has(slug)) {
    return fetchBlogStats(slug);
  }
  pendingLikeToggles.add(slug);

  try {
    const currentlyLiked = hasLikedLocally(slug);
    const rpc = currentlyLiked ? "decrement_blog_like" : "increment_blog_like";

    // Optimistic local flag so rapid clicks stay consistent
    markLikedLocally(slug, !currentlyLiked);

    const { data, error } = await sb.rpc(rpc, { p_slug: slug });

    if (error) {
      markLikedLocally(slug, currentlyLiked);
      console.warn("[blogStats] like toggle failed", error.message);
      return fetchBlogStats(slug);
    }

    return rowToStats(data as BlogStatsRow, slug);
  } finally {
    pendingLikeToggles.delete(slug);
  }
}

export { isBlogStatsConfigured };
