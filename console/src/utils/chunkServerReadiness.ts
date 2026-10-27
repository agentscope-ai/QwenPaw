const REQUEST_TIMEOUT_MS = 2500;
const READINESS_TIMEOUT_MS = 30_000;
const PROBE_INTERVAL_MS = 1000;
const REQUIRED_SUCCESSES = 3;

export interface ChunkServerReadiness {
  outcome: "ready" | "timeout" | "cancelled" | "not-applicable";
  attempts: number;
  consecutiveSuccesses: number;
  elapsedMs: number;
  lastStatus: number | null;
}

function abortError() {
  return new DOMException("Readiness check aborted", "AbortError");
}

async function readResponse(
  url: URL,
  signal: AbortSignal,
  report: ChunkServerReadiness,
) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timeout = window.setTimeout(abort, REQUEST_TIMEOUT_MS);
  signal.addEventListener("abort", abort, { once: true });
  const aborted = new Promise<never>((_resolve, reject) => {
    controller.signal.addEventListener("abort", () => reject(abortError()), {
      once: true,
    });
  });
  if (signal.aborted) abort();
  report.lastStatus = null;
  try {
    return await Promise.race([
      aborted,
      (async () => {
        if (controller.signal.aborted) throw abortError();
        const response = await fetch(url.href, {
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          signal: controller.signal,
        });
        if (controller.signal.aborted || !response.ok) {
          void response.body?.cancel().catch(() => undefined);
          if (!controller.signal.aborted) report.lastStatus = response.status;
          throw new Error("Readiness request did not succeed");
        }
        report.lastStatus = response.status;
        const body = await response.text();
        if (controller.signal.aborted) throw abortError();
        return {
          body,
          contentType: response.headers.get("content-type") ?? "",
        };
      })(),
    ]);
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener("abort", abort);
    controller.abort();
  }
}

async function waitForNextProbe(signal: AbortSignal) {
  let timer: number | undefined;
  let abort: () => void = () => undefined;
  try {
    await new Promise<void>((resolve, reject) => {
      abort = () => reject(abortError());
      signal.addEventListener("abort", abort, { once: true });
      timer = window.setTimeout(resolve, PROBE_INTERVAL_MS);
      if (signal.aborted) abort();
    });
  } finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}

/** A fresh entry allows a reload even when an old hashed chunk was removed. */
function entryUrl(body: string, page: URL): URL {
  const html = new DOMParser().parseFromString(body, "text/html");
  const base = new URL(
    html.querySelector("base[href]")?.getAttribute("href") ?? page.href,
    page,
  );
  const entry = Array.from(
    html.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'),
  ).find(
    (script) =>
      new URL(script.getAttribute("src")!, base).pathname !== "/@vite/client",
  );
  if (!entry) throw new Error("No module entry in the current page");
  const url = new URL(entry.getAttribute("src")!, base);
  if (url.origin !== page.origin || url.username || url.password) {
    throw new Error("Module entry must use the same origin");
  }
  return url;
}

/** Observe local HTTP and static availability without spending reload budget. */
export async function waitForChunkServerReady(
  resourceUrl: string | null,
  signal: AbortSignal,
): Promise<ChunkServerReadiness> {
  const report: ChunkServerReadiness = {
    outcome: "not-applicable",
    attempts: 0,
    consecutiveSuccesses: 0,
    elapsedMs: 0,
    lastStatus: null,
  };
  if (signal.aborted) return { ...report, outcome: "cancelled" };
  const page = new URL(window.location.href);
  if (
    !/^https?:$/.test(page.protocol) ||
    !["localhost", "127.0.0.1", "[::1]"].includes(page.hostname) ||
    (resourceUrl && new URL(resourceUrl, page).origin !== page.origin)
  ) {
    return report;
  }
  page.username = "";
  page.password = "";
  page.search = "";
  page.hash = "";
  const startedAt = Date.now();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  const deadline = window.setTimeout(abort, READINESS_TIMEOUT_MS);
  report.outcome = "timeout";
  try {
    while (!controller.signal.aborted) {
      report.attempts += 1;
      try {
        const version = await readResponse(
          new URL("/api/version", page),
          controller.signal,
          report,
        );
        const payload = JSON.parse(version.body);
        if (
          !/^application\/json(?:\s*;|$)/i.test(version.contentType) ||
          typeof payload?.version !== "string" ||
          !payload.version.trim()
        ) {
          throw new Error("Invalid public version response");
        }
        const document = await readResponse(page, controller.signal, report);
        if (
          !/^(?:text\/html|application\/xhtml\+xml)(?:\s*;|$)/i.test(
            document.contentType,
          )
        ) {
          throw new Error("Invalid page response");
        }
        const entry = await readResponse(
          entryUrl(document.body, page),
          controller.signal,
          report,
        );
        if (
          !/^(?:text|application)\/(?:javascript|ecmascript)(?:\s*;|$)/i.test(
            entry.contentType,
          ) ||
          !entry.body.trim()
        ) {
          throw new Error("Invalid module entry response");
        }
        report.consecutiveSuccesses += 1;
      } catch {
        report.consecutiveSuccesses = 0;
      }
      if (controller.signal.aborted) break;
      if (report.consecutiveSuccesses === REQUIRED_SUCCESSES) {
        report.outcome = "ready";
        break;
      }
      await waitForNextProbe(controller.signal);
    }
  } catch {
    // The deadline or caller cancelled a pending interval.
  } finally {
    report.outcome = signal.aborted ? "cancelled" : report.outcome;
    report.elapsedMs = Date.now() - startedAt;
    window.clearTimeout(deadline);
    signal.removeEventListener("abort", abort);
    controller.abort();
  }
  return report;
}
