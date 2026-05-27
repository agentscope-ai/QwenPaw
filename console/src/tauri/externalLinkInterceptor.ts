import {
  isDesktopTauriRuntime,
  isSupportedExternalHref,
  openExternalLink,
} from "../utils/openExternalLink";

let installedCleanup: (() => void) | null = null;
let installCount = 0;

function findAnchor(event: MouseEvent): HTMLAnchorElement | null {
  const path = event.composedPath?.() ?? [];
  for (const target of path) {
    if (target instanceof HTMLAnchorElement) {
      return target;
    }
  }

  const target = event.target;
  if (target instanceof Element) {
    return target.closest("a[href]");
  }

  return null;
}

function supportedHrefFromAnchor(anchor: HTMLAnchorElement): string | null {
  if (anchor.hasAttribute("download")) {
    return null;
  }

  const href = anchor.getAttribute("href")?.trim();
  if (!href || !isSupportedExternalHref(href)) {
    return null;
  }

  return href;
}

/**
 * Tauri WebView does not reliably open target=_blank anchor clicks. Route
 * user-initiated external links through the desktop opener.
 */
export function installTauriExternalLinkInterceptor(): () => void {
  if (typeof window === "undefined" || !isDesktopTauriRuntime()) {
    return () => {};
  }

  installCount += 1;
  let cleanupCalled = false;

  if (!installedCleanup) {
    const handleClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      const anchor = findAnchor(event);
      if (!anchor) {
        return;
      }

      const href = supportedHrefFromAnchor(anchor);
      if (!href) {
        return;
      }

      // Stop WebView navigation while allowing React/user click handlers to run.
      event.preventDefault();
      openExternalLink(href);
    };

    document.addEventListener("click", handleClick, true);

    installedCleanup = () => {
      document.removeEventListener("click", handleClick, true);
      installedCleanup = null;
    };
  } else if (import.meta.env.DEV) {
    console.warn(
      "[external-link] Tauri external link interceptor already installed",
    );
  }

  return () => {
    if (cleanupCalled) return;
    cleanupCalled = true;
    installCount = Math.max(0, installCount - 1);
    if (installCount === 0) {
      installedCleanup?.();
    }
  };
}
