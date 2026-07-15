import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { trackPageView } from "@/lib/analytics";

const BLOG_POST_PATH = /^\/blog\/[^/]+$/;

/** Reset window scroll on route change (SPA default keeps previous scroll position). */
export function ScrollToTop() {
  const { pathname, hash, search } = useLocation();

  useEffect(() => {
    if (hash) return;
    window.scrollTo(0, 0);
  }, [pathname, hash]);

  useEffect(() => {
    if (BLOG_POST_PATH.test(pathname)) return;
    trackPageView(`${pathname}${search}`);
  }, [pathname, search]);

  return null;
}
