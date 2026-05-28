import { invoke, isTauri } from "@tauri-apps/api/core";
import { buildAuthHeaders } from "../api/authHeaders";
import { getApiUrl } from "../api/config";

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
type ExternalLinkDebugPayload = {
  phase: string;
  url?: string;
  runtime?: string;
  tauri_api?: boolean;
  global_is_tauri?: boolean;
  has_tauri_internals?: boolean;
  has_pywebview_open?: boolean;
  location?: string;
  error?: string;
};

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

function shouldSendExternalLinkDiagnostics(): boolean {
  if (typeof window === "undefined") return false;

  return !(
    window as { __QWENPAW_DISABLE_EXTERNAL_LINK_DIAGNOSTICS__?: boolean }
  ).__QWENPAW_DISABLE_EXTERNAL_LINK_DIAGNOSTICS__;
}

function getExternalLinkDiagnosticState(): Omit<
  ExternalLinkDebugPayload,
  "phase" | "runtime" | "url" | "error"
> {
  let tauriApi = false;
  try {
    tauriApi = isTauri();
  } catch {
    tauriApi = false;
  }

  const globalScope = globalThis as { isTauri?: unknown };
  return {
    tauri_api: tauriApi,
    global_is_tauri: Boolean(globalScope.isTauri),
    has_tauri_internals: hasTauriInternals(),
    has_pywebview_open:
      typeof window.pywebview?.api?.open_external_link === "function",
    location: `${window.location.protocol}//${window.location.host}${window.location.pathname}`,
  };
}

function postExternalLinkDiagnostic(payload: ExternalLinkDebugPayload): void {
  if (!shouldSendExternalLinkDiagnostics()) return;

  void fetch(getApiUrl("/console/debug/external-link"), {
    method: "POST",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...getExternalLinkDiagnosticState(),
      ...payload,
    }),
  }).catch(() => {});
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
  if (!fullUrl) {
    postExternalLinkDiagnostic({ phase: "ignored-unsupported-url" });
    return;
  }

  const runtime = detectExternalLinkRuntime(fullUrl);
  postExternalLinkDiagnostic({
    phase: "called",
    runtime,
    url: externalUrlForLog(fullUrl),
  });

  switch (runtime) {
    case "pywebview": {
      postExternalLinkDiagnostic({
        phase: "pywebview-open",
        runtime,
        url: externalUrlForLog(fullUrl),
      });
      getPyWebViewApi()?.open_external_link(fullUrl);
      return;
    }
    case "tauri": {
      postExternalLinkDiagnostic({
        phase: "tauri-dispatch",
        runtime,
        url: externalUrlForLog(fullUrl),
      });
      void invoke(TAURI_OPEN_EXTERNAL_LINK_COMMAND, { url: fullUrl })
        .then(() => {
          postExternalLinkDiagnostic({
            phase: "tauri-success",
            runtime,
            url: externalUrlForLog(fullUrl),
          });
        })
        .catch((error) => {
          postExternalLinkDiagnostic({
            phase: "tauri-error",
            runtime,
            url: externalUrlForLog(fullUrl),
            error: error instanceof Error ? error.message : String(error),
          });
          console.warn("[external-link] Tauri open command failed", {
            error,
            url: externalUrlForLog(fullUrl),
          });
        });
      return;
    }
    case "browser":
      postExternalLinkDiagnostic({
        phase: "browser-window-open",
        runtime,
        url: externalUrlForLog(fullUrl),
      });
      window.open(fullUrl, target, features);
  }
}
