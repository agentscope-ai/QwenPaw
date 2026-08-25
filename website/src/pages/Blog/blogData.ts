export type BlogPostMeta = {
  slug: string;
  /** Optional hero/thumbnail; falls back to a themed placeholder. */
  cover?: string;
};

/** Display order is determined by frontmatter `date` (newest first). */
export const BLOG_POSTS: BlogPostMeta[] = [
  {
    slug: "creator-install-guide",
    cover:
      "https://img.alicdn.com/imgextra/i4/6000000000246/O1CN01Ic1vFhQin1E6mS1k_!!6000000000246-0-tbvideo.jpg",
  },
  {
    slug: "introducing-qwenpaw-hub",
  },
  {
    slug: "qwenpaw-long-term-memory",
    cover:
      "https://img.alicdn.com/imgextra/i3/O1CN01IvOZgheUdXK3OTaP_!!6000000004070-2-tps-1672-941.png",
  },
  {
    slug: "qwenpaw-files-workspace",
    cover:
      "https://img.alicdn.com/imgextra/i4/O1CN01pEZk6a8g9lK3gjEp_!!6000000001665-2-tps-1817-866.png",
  },
  {
    slug: "tool-call-offload-mechanism",
    cover:
      "https://img.alicdn.com/imgextra/i4/O1CN019X5yeUaofRG37MB6_!!6000000005163-0-tps-1536-1024.jpg",
  },
  {
    slug: "qwenpaw-scroll-executable-memory",
  },
  {
    slug: "qwenpaw-os-shell",
    cover:
      "https://img.alicdn.com/imgextra/i1/O1CN01KdzUBgLJLmH3OTaP_!!6000000003854-2-tps-1672-941.png",
  },
  {
    slug: "cross-harness-agent-os",
    cover:
      "https://img.alicdn.com/imgextra/i4/O1CN01Rag1j315f8J7Nxgw_!!6000000005570-2-tps-3638-1716.png",
  },
  {
    slug: "qwenPaw-visual-compression",
    cover:
      "https://img.alicdn.com/imgextra/i2/O1CN01yY4c4j29VUb5FtFhp_!!6000000008073-2-tps-1561-858.png",
  },
  {
    slug: "qwenpaw-loop-engineering",
    cover:
      "https://img.alicdn.com/imgextra/i1/O1CN01D73t2s1WdUUsjMQ2C_!!6000000002811-2-tps-1536-1024.png",
  },
  {
    slug: "qwenpaw-sandbox",
    cover:
      "https://img.alicdn.com/imgextra/i4/O1CN01lN8QDc1ZB2kAtxHH5_!!6000000003155-2-tps-1536-1024.png",
  },
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
  {
    slug: "qwenpaw-plugin-picks-1",
    cover:
      "https://img.alicdn.com/imgextra/i1/6000000004826/O1CN014843Da1lWMZIlKBgv_!!6000000004826-0-tbvideo.jpg",
  },
  {
    slug: "qwenpaw-checkpoint",
    cover:
      "https://img.alicdn.com/imgextra/i3/O1CN01LXaNPg4UfYB3rvs1_!!6000000007061-2-tps-1906-943.png",
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
