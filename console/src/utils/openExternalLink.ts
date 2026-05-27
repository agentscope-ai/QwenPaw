import { invoke, isTauri } from "@tauri-apps/api/core";

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

export function isHttpExternalUrl(url: string): boolean {
  try {
    return HTTP_PROTOCOLS.has(protocolOf(url));
  } catch {
    return false;
  }
}

function isSupportedExternalUrl(url: string): boolean {
  try {
    return SUPPORTED_EXTERNAL_PROTOCOLS.has(protocolOf(url));
  } catch {
    return false;
  }
}

function resolveSupportedExternalUrl(url: string): string | null {
  const resolvedUrl = resolveExternalUrl(url);
  if (!resolvedUrl || !isSupportedExternalUrl(resolvedUrl)) {
    return null;
  }

  return resolvedUrl;
}

export function isSupportedExternalHref(href?: string): href is string {
  const trimmedHref = href?.trim();
  if (!trimmedHref || !URL_WITH_SCHEME_RE.test(trimmedHref)) {
    return false;
  }

  return resolveSupportedExternalUrl(trimmedHref) !== null;
}

type PyWebViewApi = NonNullable<Window["pywebview"]>["api"];

function getPyWebViewApi(): PyWebViewApi | undefined {
  return window.pywebview?.api;
}

export function isDesktopTauriRuntime(): boolean {
  // When Tauri loads a remote-origin console, injected internals can still be
  // available even when the SDK helper does not report the runtime.
  return isTauri() || hasTauriInternals();
}

function hasTauriInternals(): boolean {
  if (typeof window === "undefined") return false;

  return (
    typeof (window as { __TAURI_INTERNALS__?: { invoke?: unknown } })
      .__TAURI_INTERNALS__?.invoke === "function"
  );
}

function externalUrlForLog(url: string): string {
  try {
    const parsedUrl = new URL(url);
    return `${parsedUrl.protocol}//${parsedUrl.host}${parsedUrl.pathname}`;
  } catch {
    return "<unparseable>";
  }
}

// Runtime priority is intentional: the legacy pywebview bridge has its own
// opener, while packaged Tauri should use the native command exposed to the
// WebView, including backend-hosted remote origins allowed by capabilities.
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
 * Open an external URL in the user's system browser when running under a
 * desktop shell, and fall back to window.open in the web console. This is
 * fire-and-forget: desktop bridge failures are logged asynchronously.
 */
export function openExternalLink(
  url: string,
  target: string = "_blank",
  features: string = "noopener,noreferrer",
): void {
  if (!url) return;

  const fullUrl = resolveSupportedExternalUrl(url);
  if (!fullUrl) return;

  switch (detectExternalLinkRuntime(fullUrl)) {
    case "pywebview": {
      getPyWebViewApi()?.open_external_link(fullUrl);
      return;
    }
    case "tauri": {
      void invoke(TAURI_OPEN_EXTERNAL_LINK_COMMAND, { url: fullUrl }).catch(
        (error) => {
          console.warn("[external-link] Tauri open command failed", {
            error,
            url: externalUrlForLog(fullUrl),
          });
        },
      );
      return;
    }
    case "browser":
      window.open(fullUrl, target, features);
  }
}
