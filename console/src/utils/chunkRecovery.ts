const RELOAD_KEY = "qwenpaw:chunk-reload-build";
const MAX_RELOADS = 2;

export interface ChunkReloadDecision {
  reason:
    | "reload"
    | "limit-reached"
    | "offline"
    | "storage-unavailable"
    | "reload-failed";
  attempts: number | null;
  maxAttempts: number;
}

export interface ErrorLike {
  message: string;
  name?: unknown;
  stack?: unknown;
}

/** Error constructors differ across WebView, iframe, and plugin realms. */
export function isErrorLike(error: unknown): error is ErrorLike {
  return (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string"
  );
}

// Production bundle URLs contain content hashes; HMR URLs identify dev builds.
export function getFrontendBuildId(): string {
  return (
    Array.from(document.scripts).find(
      (script) =>
        script.type === "module" &&
        script.src &&
        !script.src.endsWith("/@vite/client"),
    )?.src ?? document.baseURI
  );
}

/** Match module loading failures without treating API fetch errors as chunks. */
export function isChunkLoadError(error: unknown): error is ErrorLike {
  if (!isErrorLike(error)) return false;
  return (
    error.name === "ChunkLoadError" ||
    /loading (?:css )?chunk|dynamically imported module|importing a module script failed|unable to preload css/i.test(
      error.message,
    )
  );
}

/** Publish every decision and reload at most twice per build and tab. */
export function reloadAfterChunkError(
  onDecision?: (decision: ChunkReloadDecision) => void,
): boolean {
  let decision: ChunkReloadDecision = {
    reason: "offline",
    attempts: null,
    maxAttempts: MAX_RELOADS,
  };
  if (window.navigator.onLine) {
    try {
      const build = getFrontendBuildId();
      const stored = window.sessionStorage.getItem(RELOAD_KEY);
      // The previous implementation stored only the build URL after one reload.
      let attempts = stored === build ? 1 : 0;
      if (stored && stored !== build) {
        try {
          const guard = JSON.parse(stored);
          if (guard?.build === build) {
            attempts =
              Number.isInteger(guard.attempts) && guard.attempts >= 0
                ? guard.attempts
                : MAX_RELOADS;
          }
        } catch {
          // A legacy marker for another build does not consume this budget.
        }
      }
      decision = {
        ...decision,
        reason: attempts >= MAX_RELOADS ? "limit-reached" : "reload",
        attempts,
      };
      if (decision.reason === "reload") {
        decision.attempts = attempts + 1;
        window.sessionStorage.setItem(
          RELOAD_KEY,
          JSON.stringify({ build, attempts: decision.attempts }),
        );
      }
    } catch {
      // Storage restrictions must not permit an unguarded reload loop.
      decision = { ...decision, reason: "storage-unavailable", attempts: null };
    }
  }
  onDecision?.(decision);
  if (decision.reason !== "reload") return false;
  try {
    window.location.reload();
    return true;
  } catch {
    onDecision?.({ ...decision, reason: "reload-failed" });
    return false;
  }
}
