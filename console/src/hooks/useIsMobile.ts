import { useEffect, useState } from "react";

const MOBILE_BREAKPOINT_PX = 768;

/**
 * Returns true when the viewport width is at or below the mobile breakpoint.
 * Safe for SSR (defaults to false when window is undefined).
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" && window.innerWidth <= MOBILE_BREAKPOINT_PX,
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const sync = () => setIsMobile(window.innerWidth <= MOBILE_BREAKPOINT_PX);
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  return isMobile;
}
