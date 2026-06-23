/**
 * Cross-runtime external link opener for browser, legacy pywebview, and Tauri.
 * It validates supported protocols and delegates desktop shells to native openers.
 */
import { invoke, isTauri } from "@tauri-apps/api/core";
import { getPyWebViewApi } from "./pywebview";

const URL_WITH_SCHEME_RE = /^[a-z][a-z\d+\-.]*:/i;
const HTTP_PROTOCOLS = new Set(["http:", "https:"]);
// Keep in sync with console/src-tauri/src/external_link.rs.
const SUPPORTED_EXTERNAL_PROTOCOLS = new Set([
  "http:",
  "https:",
  "mailto:",
  "tel:",
]);
const TAURI_OPEN_EXTERNAL_LINK_COMMAND = "open_external_link";
type ExternalLinkRuntime = "pywebview" | "tauri" | "browser";

function hasHttpUrlPrefix(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/** Resolve absolute and app-relative URLs while ignoring empty or hash-only links. */
export function resolveExternalUrl(url: string): string | null {
  const trimmedUrl = url.trim();
  if (!trimmedUrl || trimmedUrl.startsWith("#")) {
    return null;
  }

  try {
    if (URL_WITH_SCHEME_RE.test(trimmedUrl)) {
      return trimmedUrl;
    }
    return new URL(trimmedUrl, window.location.origin).toString();
  } catch {
    return null;
  }
}

function protocolOf(url: string): string {
  return new URL(url).protocol;
}

/** Return true when a resolved URL is HTTP(S), the legacy desktop bridge's scope. */
export function isHttpExternalUrl(url: string): boolean {
  try {
    return hasHttpUrlPrefix(url) && HTTP_PROTOCOLS.has(protocolOf(url));
  } catch {
    return false;
  }
}

function isSupportedExternalUrl(url: string): boolean {
  try {
    const protocol = protocolOf(url);
    if (HTTP_PROTOCOLS.has(protocol)) {
      return hasHttpUrlPrefix(url);
    }
    return SUPPORTED_EXTERNAL_PROTOCOLS.has(protocol);
  } catch {
    return false;
  }
}

/** Resolve an input URL only if its protocol is safe to hand to external openers. */
function resolveSupportedExternalUrl(url: string): string | null {
  const resolvedUrl = resolveExternalUrl(url);
  if (!resolvedUrl || !isSupportedExternalUrl(resolvedUrl)) {
    return null;
  }

  return resolvedUrl;
}

/** Detect Tauri even after the app has navigated to the backend-hosted console. */
export function isDesktopTauriRuntime(): boolean {
  // When Tauri loads a remote-origin console, injected internals can still be
  // available even when the SDK helper does not report the runtime.
  return isTauri() || hasTauriInternals();
}

/** Check for Tauri's injected invoke hook when the SDK helper is unavailable. */
function hasTauriInternals(): boolean {
  if (typeof window === "undefined") return false;

  return (
    typeof (window as { __TAURI_INTERNALS__?: { invoke?: unknown } })
      .__TAURI_INTERNALS__?.invoke === "function"
  );
}

// Runtime priority is intentional: the legacy pywebview bridge has its own
// opener, while packaged Tauri should use the native command exposed to the
// WebView, including backend-hosted remote origins allowed by capabilities.
/** Choose which runtime should handle a validated external URL. */
function detectExternalLinkRuntime(fullUrl: string): ExternalLinkRuntime {
  const pywebviewApi = getPyWebViewApi();
  if (pywebviewApi?.open_external_link && isHttpExternalUrl(fullUrl)) {
    return "pywebview";
  }

  if (isDesktopTauriRuntime()) {
    return "tauri";
  }

  return "browser";
}

/**
 * Open a supported external URL in the OS/browser-appropriate target.
 * Desktop bridge failures are logged asynchronously because clicks are
 * fire-and-forget from the UI's perspective.
 */
export function openExternalLink(
  url: string,
  target: string = "_blank",
  features: string = "noopener,noreferrer",
): void {
  if (!url) return;

  const fullUrl = resolveSupportedExternalUrl(url);
  if (!fullUrl) {
    return;
  }

  const runtime = detectExternalLinkRuntime(fullUrl);

  switch (runtime) {
    case "pywebview": {
      getPyWebViewApi()?.open_external_link?.(fullUrl);
      return;
    }
    case "tauri": {
      void invoke(TAURI_OPEN_EXTERNAL_LINK_COMMAND, { url: fullUrl }).catch(
        (error) => {
          console.warn("[external-link] Tauri open command failed", error);
        },
      );
      return;
    }
    case "browser":
      window.open(fullUrl, target, features);
  }
}
