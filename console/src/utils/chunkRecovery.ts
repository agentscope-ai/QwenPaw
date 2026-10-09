const RELOAD_KEY = "qwenpaw:chunk-reload-build";
// Production bundle URLs contain content hashes; HMR URLs identify dev builds.
export const FRONTEND_BUILD_ID =
  Array.from(document.scripts).find(
    (script) =>
      script.type === "module" &&
      script.src &&
      !script.src.endsWith("/@vite/client"),
  )?.src ?? import.meta.url;

/** Match module loading failures without treating API fetch errors as chunks. */
export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.name === "ChunkLoadError" ||
    /loading (?:css )?chunk|dynamically imported module|importing a module script failed|unable to preload css/i.test(
      error.message,
    )
  );
}

/** Reload once per build and tab, retaining the guard across successful pages. */
export function reloadAfterChunkError(beforeReload?: () => void): boolean {
  if (!window.navigator.onLine) return false;
  try {
    if (window.sessionStorage.getItem(RELOAD_KEY) === FRONTEND_BUILD_ID)
      return false;
    window.sessionStorage.setItem(RELOAD_KEY, FRONTEND_BUILD_ID);
    beforeReload?.();
    window.location.reload();
    return true;
  } catch {
    // Storage restrictions must not permit an unguarded reload loop.
    return false;
  }
}
