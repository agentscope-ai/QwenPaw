export type BlogPostMeta = {
  slug: string;
  /** Optional hero/thumbnail; falls back to a themed placeholder. */
  cover?: string;
};

/** Display order is determined by frontmatter `date` (newest first). */
export const BLOG_POSTS: BlogPostMeta[] = [
  {
    slug: "qwenpaw-developer-day-collection",
    cover:
      "https://img.alicdn.com/imgextra/i1/O1CN01x0yknl1moyGt1kpxU_!!6000000005002-2-tps-1224-696.png",
  },
  {
    slug: "introducing-qwenpaw-driver",
    cover:
      "https://img.alicdn.com/imgextra/i2/O1CN01IHOJzn1Jm6wO0Jy9L_!!6000000001070-2-tps-1224-696.png",
  },
  {
    slug: "play-with-qwenpaw-pet",
    cover:
      "https://img.alicdn.com/imgextra/i3/O1CN01eC3Ngx1Tzz5zy5VCX_!!6000000002454-2-tps-1536-1024.png",
  },
  {
    slug: "paw-git",
    cover:
      "https://img.alicdn.com/imgextra/i2/O1CN01cdSRbU26gXIFiTRjL_!!6000000007691-2-tps-1254-1254.png",
  },
  {
    slug: "runtime-architecture-upgrade",
    cover:
      "https://img.alicdn.com/imgextra/i1/O1CN01eByOkk1h3Gwf2q0It_!!6000000004221-2-tps-1536-1024.png",
  },
];

/** Previous post in list order (top → bottom on /blog, date-desc). */
export function getPrevBlogSlug(
  currentSlug: string,
  sortedSlugs: string[],
): string | undefined {
  const index = sortedSlugs.indexOf(currentSlug);
  if (index <= 0) return undefined;
  return sortedSlugs[index - 1];
}

/** Next post in list order (top → bottom on /blog, date-desc). */
export function getNextBlogSlug(
  currentSlug: string,
  sortedSlugs: string[],
): string | undefined {
  const index = sortedSlugs.indexOf(currentSlug);
  if (index < 0 || index >= sortedSlugs.length - 1) return undefined;
  return sortedSlugs[index + 1];
}
