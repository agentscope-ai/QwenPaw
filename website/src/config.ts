export interface SiteConfig {
  projectName: string;
  projectTaglineEn: string;
  projectTaglineZh: string;
  repoUrl: string;
  docsPath: string;
  /** When true or omitted, show Testimonials on homepage. */
  showTestimonials?: boolean;
  /**
   * ModelScope Studio one-click setup URL (no Python install).
   * Replace target when officially launched.
   */
  modelScopeForkUrl?: string;
}

export const defaultConfig: SiteConfig = {
  projectName: "QwenPaw",
  projectTaglineEn: "Works for you, grows with you",
  projectTaglineZh: "懂你所需，伴你左右",
  repoUrl: "https://github.com/agentscope-ai/QwenPaw",
  docsPath: "/docs/",
  showTestimonials: true,
  modelScopeForkUrl:
    "https://modelscope.cn/studios/fork?target=AgentScope/QwenPaw",
};

let cached: SiteConfig | null = null;

export async function loadSiteConfig(): Promise<SiteConfig> {
  if (cached) return cached;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 4000);
  try {
    const r = await fetch(`${import.meta.env.BASE_URL}site.config.json`, {
      signal: controller.signal,
    });
    if (r.ok) {
      cached = (await r.json()) as SiteConfig;
      return cached;
    }
  } catch {
    /* use defaults */
  } finally {
    window.clearTimeout(timer);
  }
  return defaultConfig;
}
