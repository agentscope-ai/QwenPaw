/**
 * Shared access point for the legacy pywebview desktop bridge.
 * Keeping the bridge type here prevents runtime helpers from drifting apart.
 */

export type PyWebViewApi = NonNullable<Window["pywebview"]>["api"];
export type PyWebViewSaveFile = NonNullable<PyWebViewApi["save_file"]>;

/** Return the legacy pywebview bridge when the old desktop shell injects it. */
export function getPyWebViewApi(): PyWebViewApi | undefined {
  return window.pywebview?.api;
}
