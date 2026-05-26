import { isTauriRuntime } from "./backendRuntime";
import {
  isSupportedExternalHref,
  openExternalLink,
} from "../utils/openExternalLink";

let installedCleanup: (() => void) | null = null;

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

function supportedHrefFromWindowOpenUrl(url?: string | URL): string | null {
  const href = url?.toString().trim();
  if (!href || !isSupportedExternalHref(href)) {
    return null;
  }

  return href;
}

/**
 * Tauri WebView does not reliably open target=_blank links or window.open()
 * calls. Route user-initiated external links through the shell plugin.
 */
export function installTauriExternalLinkInterceptor(): () => void {
  if (typeof window === "undefined" || !isTauriRuntime()) {
    return () => {};
  }

  if (installedCleanup) {
    return () => {};
  }

  const originalOpen = window.open;

  window.open = ((url?: string | URL, target?: string, features?: string) => {
    const href = supportedHrefFromWindowOpenUrl(url);
    if (href) {
      openExternalLink(href, target, features);
      return null;
    }

    return originalOpen.call(window, url, target, features);
  }) as typeof window.open;

  const handleClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0) {
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
    window.open = originalOpen;
    installedCleanup = null;
  };

  return installedCleanup;
}
