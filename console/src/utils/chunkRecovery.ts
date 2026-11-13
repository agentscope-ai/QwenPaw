const RELOAD_KEY = "qwenpaw:chunk-reload-build";
const MAX_RELOADS = 2;
const HEALTHY_PERIOD_MS = 60_000;

let healthyPages = 0;
let healthBlocks = 0;
let healthyTimer: number | undefined;

function cancelHealthyReset() {
  if (healthyTimer !== undefined) window.clearTimeout(healthyTimer);
  healthyTimer = undefined;
}

function isHealthy() {
  return (
    healthyPages > 0 &&
    healthBlocks === 0 &&
    window.navigator.onLine &&
    document.visibilityState === "visible"
  );
}

function canResetGuard(stored: string | null, build: string) {
  if (stored === build) return true;
  if (!stored) return false;
  try {
    const guard = JSON.parse(stored);
    return (
      guard?.build === build &&
      Number.isInteger(guard.attempts) &&
      guard.attempts > 0
    );
  } catch {
    return false;
  }
}

function restartHealthyReset() {
  if (!isHealthy()) {
    cancelHealthyReset();
    return;
  }
  if (healthyTimer !== undefined) return;
  try {
    const build = getFrontendBuildId();
    const stored = window.sessionStorage.getItem(RELOAD_KEY);
    if (!canResetGuard(stored, build)) return;
    healthyTimer = window.setTimeout(() => {
      healthyTimer = undefined;
      if (!isHealthy()) return;
      try {
        if (
          getFrontendBuildId() === build &&
          window.sessionStorage.getItem(RELOAD_KEY) === stored
        ) {
          window.sessionStorage.removeItem(RELOAD_KEY);
        }
      } catch {
        // Storage restrictions keep the existing reload protection intact.
      }
    }, HEALTHY_PERIOD_MS);
  } catch {
    // A healthy page must remain usable when session storage is restricted.
  }
}

function trackRecoveryHealth(healthy: boolean): () => void {
  if (healthyPages + healthBlocks === 0) {
    window.addEventListener("online", restartHealthyReset);
    window.addEventListener("offline", restartHealthyReset);
    document.addEventListener("visibilitychange", restartHealthyReset);
  }
  if (healthy) healthyPages += 1;
  else healthBlocks += 1;
  restartHealthyReset();
  let tracked = true;
  return () => {
    if (!tracked) return;
    tracked = false;
    if (healthy) healthyPages -= 1;
    else healthBlocks -= 1;
    restartHealthyReset();
    if (healthyPages + healthBlocks === 0) {
      window.removeEventListener("online", restartHealthyReset);
      window.removeEventListener("offline", restartHealthyReset);
      document.removeEventListener("visibilitychange", restartHealthyReset);
    }
  };
}

/** Restore recovery only after committed content stays healthy for a minute. */
export function markChunkPageHealthy(): () => void {
  return trackRecoveryHealth(true);
}

/** Loading and error views block every healthy page in the same tab. */
export function blockChunkRecoveryHealth(): () => void {
  return trackRecoveryHealth(false);
}

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

/** Reload at most twice per build and tab between sustained healthy periods. */
export function reloadAfterChunkError(
  onDecision?: (decision: ChunkReloadDecision) => void,
): boolean {
  cancelHealthyReset();
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
