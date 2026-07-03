export const GA_ID = "G-BEX1XSB9KE";

declare global {
  interface Window {
    dataLayer: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/**
 * Load Google Analytics script asynchronously.
 * Skipped in development and when gtag is already present.
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
  function gtag(...args: unknown[]) {
    window.dataLayer.push(args);
  }
  window.gtag = gtag;

  gtag("js", new Date());
  gtag("config", id);

  const script = document.createElement("script");
  script.src = `https://www.googletagmanager.com/gtag/js?id=${id}`;
  script.async = true;

  let isLoaded = false;
  const timeoutId = setTimeout(() => {
    if (!isLoaded) {
      console.warn("[GA] Load timeout - removing script");
      script.remove();
      delete window.gtag;
    }
  }, 6000);

  script.onload = () => {
    isLoaded = true;
    clearTimeout(timeoutId);
    console.log("[GA] Loaded successfully");
  };

  script.onerror = () => {
    isLoaded = true;
    clearTimeout(timeoutId);
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
