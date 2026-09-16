import { useContext, useSyncExternalStore } from "react";
import { OsWindowSizeContext } from "../os/osWindowSizeContext";

const MOBILE_BREAKPOINT_PX = 768;
const MOBILE_MEDIA_QUERY = `(max-width: ${MOBILE_BREAKPOINT_PX}px)`;

const viewportSubscribers = new Set<() => void>();
let mobileMediaQuery: MediaQueryList | null = null;
let removeViewportListener: (() => void) | null = null;

function getMobileMediaQuery(): MediaQueryList | null {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return null;
  }
  mobileMediaQuery ??= window.matchMedia(MOBILE_MEDIA_QUERY);
  return mobileMediaQuery;
}

function notifyViewportSubscribers() {
  viewportSubscribers.forEach((subscriber) => subscriber());
}

function subscribeToMobileViewport(subscriber: () => void) {
  viewportSubscribers.add(subscriber);

  if (viewportSubscribers.size === 1 && typeof window !== "undefined") {
    const mediaQuery = getMobileMediaQuery();
    if (mediaQuery?.addEventListener) {
      mediaQuery.addEventListener("change", notifyViewportSubscribers);
      removeViewportListener = () =>
        mediaQuery.removeEventListener("change", notifyViewportSubscribers);
    } else if (mediaQuery?.addListener) {
      mediaQuery.addListener(notifyViewportSubscribers);
      removeViewportListener = () =>
        mediaQuery.removeListener(notifyViewportSubscribers);
    } else {
      window.addEventListener("resize", notifyViewportSubscribers);
      removeViewportListener = () =>
        window.removeEventListener("resize", notifyViewportSubscribers);
    }
  }

  return () => {
    viewportSubscribers.delete(subscriber);
    if (viewportSubscribers.size === 0) {
      removeViewportListener?.();
      removeViewportListener = null;
    }
  };
}

function getViewportSnapshot() {
  const mediaQuery = getMobileMediaQuery();
  if (mediaQuery) {
    return mediaQuery.matches;
  }
  return (
    typeof window !== "undefined" && window.innerWidth <= MOBILE_BREAKPOINT_PX
  );
}

function getServerSnapshot() {
  return false;
}

/**
 * Returns true when the effective width is at or below the mobile breakpoint.
 * Inside an OS window the enclosing window's content width wins (so pages
 * adapt to the window, not the screen); otherwise the viewport width is used.
 * Safe for SSR (defaults to false when window is undefined).
 */
export function useIsMobile() {
  const containerWidth = useContext(OsWindowSizeContext);
  const isViewportMobile = useSyncExternalStore(
    subscribeToMobileViewport,
    getViewportSnapshot,
    getServerSnapshot,
  );

  if (containerWidth != null) {
    return containerWidth <= MOBILE_BREAKPOINT_PX;
  }
  return isViewportMobile;
}
