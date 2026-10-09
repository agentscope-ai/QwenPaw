import { getFrontendBuildId } from "./chunkRecovery";
import { getLazyImportFailure } from "./lazyImportFailure";

const STORAGE_KEY = "qwenpaw:chunk-diagnostic";
const RECHECK_TIMEOUT_MS = 2000;
const URL_PATTERN = /(?:https?:\/\/|\/)[^\s"'<>()[\]]+/g;

export type ResourceOutcome =
  | "missing"
  | "denied"
  | "html"
  | "http-error"
  | "available"
  | "request-failed"
  | "timeout"
  | "unavailable";

export interface ResourceRecheck {
  checkedAt: string;
  outcome: ResourceOutcome;
  status: number | null;
  contentType: string | null;
}

export interface ChunkDiagnostic {
  capturedAt: string;
  page: string;
  frontendBuild: string;
  browser: string;
  online: boolean;
  originalError: { name: string; message: string; stack: string };
  modulePath: string | null;
  attempts: number | null;
  resourceUrl: string | null;
  originalResourceStatus: number | null;
  recheck: ResourceRecheck | null;
  automaticReloadAttempted: boolean;
  phase?: "startup";
  startupFailure?: "resource" | "runtime" | "timeout";
  elapsedMs?: number;
}

function safeUrl(value: string): string {
  const url = new URL(value, window.location.href);
  url.username = "";
  url.password = "";
  for (const key of [...url.searchParams.keys()]) {
    if (key !== "v" && key !== "t") url.searchParams.delete(key);
  }
  url.hash = "";
  return url.toString();
}

function safeErrorText(text: string): string {
  return text.replace(URL_PATTERN, (value) => {
    try {
      return safeUrl(value);
    } catch {
      return "[invalid URL]";
    }
  });
}

/** Browsers may omit the failed URL, notably Safari/WebView. */
export function failedResourceUrl(error: Error): string | null {
  for (const value of error.message.match(URL_PATTERN) ?? []) {
    try {
      const url = new URL(value.replace(/[.,;]+$/, ""), window.location.href);
      if (
        /^https?:$/.test(url.protocol) &&
        /\.(?:m?js|jsx|tsx?|css)$/i.test(url.pathname)
      ) {
        return url.toString();
      }
    } catch {
      // An incomplete browser message does not establish a resource address.
    }
  }
  return null;
}

export function captureChunkDiagnostic(
  error: Error,
  resourceUrl = failedResourceUrl(error),
): ChunkDiagnostic {
  const timing = resourceUrl
    ? (performance.getEntriesByName(resourceUrl, "resource").slice(-1)[0] as
        | (PerformanceResourceTiming & { responseStatus?: number })
        | undefined)
    : undefined;
  const failure = getLazyImportFailure(error);
  return {
    capturedAt: new Date().toISOString(),
    page: `${window.location.origin}${window.location.pathname}`,
    frontendBuild: safeUrl(getFrontendBuildId()),
    browser: navigator.userAgent,
    online: navigator.onLine,
    originalError: {
      name: error.name,
      message: safeErrorText(error.message).slice(0, 4000),
      stack: safeErrorText(error.stack ?? "").slice(0, 16000),
    },
    modulePath: failure?.modulePath ?? null,
    attempts: failure?.attempts ?? null,
    resourceUrl: resourceUrl ? safeUrl(resourceUrl) : null,
    originalResourceStatus: timing?.responseStatus || null,
    recheck: null,
    automaticReloadAttempted: false,
  };
}

export function saveChunkDiagnostic(report: ChunkDiagnostic): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(report));
  } catch {
    // In-page details and copying remain available when storage is blocked.
  }
}

export function readChunkDiagnostic(): ChunkDiagnostic | null {
  try {
    const report = JSON.parse(
      window.sessionStorage.getItem(STORAGE_KEY) ?? "null",
    );
    return report &&
      typeof report.capturedAt === "string" &&
      typeof report.page === "string" &&
      typeof report.originalError?.message === "string"
      ? (report as ChunkDiagnostic)
      : null;
  } catch {
    return null;
  }
}

/** A bounded fresh request observes current availability, not the first failure. */
export async function recheckChunkResource(
  resourceUrl: string | null,
): Promise<ResourceRecheck> {
  const result: ResourceRecheck = {
    checkedAt: new Date().toISOString(),
    outcome: "unavailable",
    status: null,
    contentType: null,
  };
  if (!resourceUrl) return result;
  const url = new URL(resourceUrl);
  if (url.origin !== window.location.origin || !navigator.onLine) return result;
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  try {
    const response = await Promise.race([
      fetch(url.toString(), {
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal,
      }),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => {
          timedOut = true;
          controller.abort();
          reject(new Error("Resource recheck timed out"));
        }, RECHECK_TIMEOUT_MS);
      }),
    ]);
    result.status = response.status;
    result.contentType = response.headers.get("content-type");
    result.outcome =
      response.status === 404
        ? "missing"
        : response.status === 401 || response.status === 403
        ? "denied"
        : !response.ok
        ? "http-error"
        : /(?:text\/html|application\/xhtml\+xml)/i.test(
            result.contentType ?? "",
          )
        ? "html"
        : "available";
    void response.body?.cancel().catch(() => undefined);
  } catch {
    result.outcome = timedOut ? "timeout" : "request-failed";
  } finally {
    clearTimeout(timeout);
  }
  return result;
}
