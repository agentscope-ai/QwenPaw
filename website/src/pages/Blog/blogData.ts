export type BlogPostMeta = {
  slug: string;
  /** Optional hero/thumbnail; falls back to a themed placeholder. */
  cover?: string;
};

/** Display order (first = top of /blog). Add entries when publishing under public/blog/. */
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
];
