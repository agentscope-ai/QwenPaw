import { useContext, useEffect, useState } from "react";
import { OsWindowSizeContext } from "../os/osWindowSizeContext";

const MOBILE_BREAKPOINT_PX = 768;

/**
 * Returns true when the effective width is at or below the mobile breakpoint.
 * Inside an OS window the enclosing window's content width wins (so pages
 * adapt to the window, not the screen); otherwise the viewport width is used.
 * Safe for SSR (defaults to false when window is undefined).
 */
export function useIsMobile() {
  const containerWidth = useContext(OsWindowSizeContext);
  const [isViewportMobile, setIsViewportMobile] = useState(
    typeof window !== "undefined" && window.innerWidth <= MOBILE_BREAKPOINT_PX,
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const sync = () =>
      setIsViewportMobile(window.innerWidth <= MOBILE_BREAKPOINT_PX);
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  if (containerWidth != null) {
    return containerWidth <= MOBILE_BREAKPOINT_PX;
  }
  return isViewportMobile;
}
