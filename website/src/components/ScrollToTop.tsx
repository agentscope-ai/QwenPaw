import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/** Reset window scroll on route change (SPA default keeps previous scroll position). */
export function ScrollToTop() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (hash) return;
    window.scrollTo(0, 0);
  }, [pathname, hash]);

  return null;
}
