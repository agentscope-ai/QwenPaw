import { invoke } from "@tauri-apps/api/core";
import { isTauriRuntime } from "../tauri/backendRuntime";

const URL_WITH_SCHEME_RE = /^[a-z][a-z\d+\-.]*:/i;
const HTTP_PROTOCOLS = new Set(["http:", "https:"]);
const SUPPORTED_EXTERNAL_PROTOCOLS = new Set([
  "http:",
  "https:",
  "mailto:",
  "tel:",
]);

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

/**
 * Open an external URL in the user's system browser when running under a
 * desktop shell, and fall back to window.open in the web console.
 */
export function openExternalLink(
  url: string,
  target: string = "_blank",
  features: string = "noopener,noreferrer",
): void {
  if (!url) return;

  const fullUrl = resolveSupportedExternalUrl(url);
  if (!fullUrl) return;

  const pywebviewApi = getPyWebViewApi();
  if (pywebviewApi?.open_external_link && isHttpExternalUrl(fullUrl)) {
    pywebviewApi.open_external_link(fullUrl);
    return;
  }

  if (isTauriRuntime()) {
    void invoke("plugin:shell|open", { path: fullUrl }).catch((error) => {
      console.warn("Failed to open external link", error);
    });
    return;
  }

  window.open(fullUrl, target, features);
}
