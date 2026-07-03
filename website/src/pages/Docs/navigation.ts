export interface DocEntry {
  slug: string;
  titleKey: string;
}

export interface DocGroup {
  titleKey: string;
  children: DocEntry[];
}

export const DOC_GROUPS: DocGroup[] = [
  {
    titleKey: "docs.groupWelcome",
    children: [
      { slug: "intro", titleKey: "docs.intro" },
      { slug: "quickstart", titleKey: "docs.quickstart" },
      { slug: "desktop", titleKey: "docs.desktop" },
      { slug: "functiondemo", titleKey: "docs.demo" },
    ],
  },
  {
    titleKey: "docs.groupControl",
    children: [
      { slug: "console", titleKey: "docs.console" },
      { slug: "tui", titleKey: "docs.tui" },
      { slug: "channels", titleKey: "docs.channels" },
      { slug: "commands", titleKey: "docs.commands" },
      { slug: "cron", titleKey: "docs.cron" },
      { slug: "heartbeat", titleKey: "docs.heartbeat" },
      { slug: "memory", titleKey: "docs.memory" },
      {
        slug: "memory-evolving-and-proactive",
        titleKey: "docs.memoryEvolvingAndProactive",
      },
      { slug: "coding-mode", titleKey: "docs.codingMode" },
    ],
  },
  {
    titleKey: "docs.groupAgent",
    children: [
      { slug: "persona", titleKey: "docs.agentPersona" },
      { slug: "multi-agent", titleKey: "docs.multiAgent" },
      { slug: "skills", titleKey: "docs.skills" },
      { slug: "mcp", titleKey: "docs.mcp" },
      { slug: "context", titleKey: "docs.context" },
      {
        slug: "loop-engineering",
        titleKey: "docs.loopEngineering",
      },
      { slug: "config", titleKey: "docs.config" },
    ],
  },
  {
    titleKey: "docs.groupSettings",
    children: [
      { slug: "models", titleKey: "docs.models" },
      { slug: "security", titleKey: "docs.security" },
      { slug: "backup", titleKey: "docs.backup" },
      { slug: "cli", titleKey: "docs.cli" },
      { slug: "plugins", titleKey: "docs.plugins" },
    ],
  },
  {
    titleKey: "docs.groupPractice",
    children: [
      { slug: "practice-agent-team", titleKey: "docs.practiceAgentTeam" },
    ],
  },
  {
    titleKey: "docs.groupOthers",
    children: [
      { slug: "architecture", titleKey: "docs.architecture" },
      { slug: "faq", titleKey: "docs.faq" },
      { slug: "api-tutorial", titleKey: "docs.apiTutorial" },
      { slug: "acp-integration", titleKey: "docs.acpServer" },
      { slug: "community", titleKey: "docs.community" },
      { slug: "contributing", titleKey: "docs.contributing" },
      { slug: "roadmap", titleKey: "docs.roadmap" },
    ],
  },
];

/** Collect all valid slugs (parents + children). */
export const ALL_SLUGS = [
  ...DOC_GROUPS.flatMap((g) => g.children.map((d) => d.slug)),
  "comparison", // Hidden page, accessible only via FAQ link
  "practice-agent-team", // Practice section
];

const DOC_TITLE_BANNERS = [
  "https://img.alicdn.com/imgextra/i3/O1CN01AFF5p31rkup6lRZdP_!!6000000005670-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01XVYxhh1qss5VAHS8W_!!6000000005552-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01bVhRvK1Kk6o0OBTvx_!!6000000001201-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01iKcnsI1zblqDgJj1g_!!6000000006733-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i4/O1CN017vxGqK1X43RXh4MiW_!!6000000002869-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01a1gbkF1W6VxFh6e6X_!!6000000002739-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01jM1xfY1oTYyDha2cC_!!6000000005226-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i1/O1CN018pVqGD1TeurBxIlox_!!6000000002408-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01IH0RKW1YhGyQLgQnH_!!6000000003090-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01LXpygR1HHlRkroefl_!!6000000000733-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i4/O1CN01YhyXsW25kMyJd5Xuh_!!6000000007564-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01nrpSe11fGR4mcMCWr_!!6000000003979-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i4/O1CN01ZZCKMR1TYxhxRVeuz_!!6000000002395-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i1/O1CN01RkWA7H1QJtppbRCYy_!!6000000001956-2-tps-1708-954.png",
  "https://img.alicdn.com/imgextra/i1/O1CN0125urEE1XvBO2jAQnn_!!6000000002985-2-tps-1708-954.png",
] as const;

export const DOC_BANNER_BY_SLUG = (() => {
  const map = new Map<string, (typeof DOC_TITLE_BANNERS)[number]>();
  const allDocs = DOC_GROUPS.flatMap((group) => group.children);
  let bannerIndex = 0;
  for (const entry of allDocs) {
    map.set(entry.slug, DOC_TITLE_BANNERS[bannerIndex]);
    bannerIndex += 1;
    if (bannerIndex >= DOC_TITLE_BANNERS.length) bannerIndex = 0;
  }
  return map;
})();

export const FALLBACK_DOC_BANNER = DOC_TITLE_BANNERS[0];

const docContentCache = new Map<string, Promise<string>>();

/**
 * Fetch a doc's markdown (language-specific, falling back to the
 * language-less file). Results are cached in memory so hover prefetch
 * and the actual navigation share the same request.
 */
export function fetchDocContent(
  slug: string,
  lang: "zh" | "en",
): Promise<string> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") || "";
  const cacheKey = `${slug}.${lang}`;
  const cached = docContentCache.get(cacheKey);
  if (cached) return cached;

  const promise = fetch(`${base}/docs/${slug}.${lang}.md`)
    .then((r) => (r.ok ? r.text() : ""))
    .then((text) => {
      if (text) return text;
      return fetch(`${base}/docs/${slug}.md`).then((r) =>
        r.ok ? r.text() : "",
      );
    })
    .catch(() => {
      // Allow retry on a later attempt if the fetch failed.
      docContentCache.delete(cacheKey);
      return "";
    });
  docContentCache.set(cacheKey, promise);
  return promise;
}

/** Warm the in-memory doc cache so navigation feels instant. */
export function prefetchDoc(slug: string, lang: "zh" | "en"): void {
  if (slug === "functiondemo") return;
  void fetchDocContent(slug, lang);
}
