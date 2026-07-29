export const GA_ID = "G-WTLZ23BMC2";

declare global {
  interface Window {
    dataLayer: IArguments[];
    gtag?: (...args: unknown[]) => void;
  }
}

/**
 * Load Google Analytics script asynchronously.
 * Must push `arguments` (not a rest-args Array) for gtag queue compatibility.
 * DEV skip temporarily disabled for local collect verification.
 */
export function loadGoogleAnalytics(id: string) {
  if (window.gtag || import.meta.env.DEV) {
    if (import.meta.env.DEV) {
      console.log("[GA] Skipped in development environment");
    }
    return;
  }

  console.log("[GA] Starting to load Google Analytics...");

  window.dataLayer = window.dataLayer || [];
  // Official snippet uses Arguments object; Array rest-args break queued commands.
  window.gtag = function gtag() {
    // eslint-disable-next-line prefer-rest-params
    window.dataLayer.push(arguments);
  };

  window.gtag("js", new Date());
  window.gtag("config", id);

  const script = document.createElement("script");
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(
    id,
  )}`;
  script.async = true;

  script.onload = () => {
    console.log("[GA] Loaded successfully");
  };

  script.onerror = () => {
    console.warn("[GA] Failed to load (may be blocked)");
    delete window.gtag;
  };

  document.head.appendChild(script);
}

/** Report a SPA route change as a page view. */
export function trackPageView(pagePath: string, pageTitle?: string) {
  if (!window.gtag) return;

  window.gtag("config", GA_ID, {
    page_path: pagePath,
    ...(pageTitle ? { page_title: pageTitle } : {}),
  });
}

/** Record a blog article page view with article metadata. */
export function trackBlogPostView(params: {
  slug: string;
  title: string;
  lang: string;
}) {
  if (!window.gtag) return;

  const pagePath = `/blog/${params.slug}`;

  window.gtag("config", GA_ID, {
    page_path: pagePath,
    page_title: params.title,
  });

  window.gtag("event", "blog_view", {
    blog_slug: params.slug,
    blog_title: params.title,
    blog_lang: params.lang,
    page_path: pagePath,
  });
}
