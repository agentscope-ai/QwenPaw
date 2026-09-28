const UI_FONT_SIZE_STORAGE_KEY = "qwenpaw_ui_font_size";
const UI_FONT_SIZE_CHANGE_EVENT = "qwenpaw:ui-font-size-change";

/** Smallest selectable base font size, in pixels. */
export const UI_FONT_SIZE_MIN = 12;
/** Largest selectable base font size, in pixels. */
export const UI_FONT_SIZE_MAX = 20;
/**
 * Default base font size, in pixels. Matches Ant Design's built-in
 * `token.fontSize`, so at this value the UI looks exactly as before.
 */
export const UI_FONT_SIZE_DEFAULT = 14;

/** Clamp any input to an integer within the supported range. */
export function clampUiFontSize(size: number): number {
  if (!Number.isFinite(size)) return UI_FONT_SIZE_DEFAULT;
  const rounded = Math.round(size);
  if (rounded < UI_FONT_SIZE_MIN) return UI_FONT_SIZE_MIN;
  if (rounded > UI_FONT_SIZE_MAX) return UI_FONT_SIZE_MAX;
  return rounded;
}

/** Read the persisted base font size, falling back to the default. */
export function getUiFontSize(): number {
  try {
    const stored = localStorage.getItem(UI_FONT_SIZE_STORAGE_KEY);
    if (stored === null) return UI_FONT_SIZE_DEFAULT;
    return clampUiFontSize(Number.parseInt(stored, 10));
  } catch {
    return UI_FONT_SIZE_DEFAULT;
  }
}

/**
 * Persist the base font size and notify subscribers. The default value is
 * stored as "absence" (key removed) to keep storage tidy.
 */
export function setUiFontSize(size: number): void {
  const next = clampUiFontSize(size);
  try {
    if (next === UI_FONT_SIZE_DEFAULT) {
      localStorage.removeItem(UI_FONT_SIZE_STORAGE_KEY);
    } else {
      localStorage.setItem(UI_FONT_SIZE_STORAGE_KEY, String(next));
    }
  } catch {
    // storage unavailable
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(UI_FONT_SIZE_CHANGE_EVENT));
  }
}

/** Subscribe to changes; designed for React's useSyncExternalStore. */
export function subscribeUiFontSize(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(UI_FONT_SIZE_CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener(UI_FONT_SIZE_CHANGE_EVENT, onStoreChange);
  };
}

/**
 * Apply the base font size to the document root. Sets two things:
 *  - `font-size` as a percentage relative to the browser default, so text
 *    that inherits (no explicit size) scales. Ant Design components carry
 *    explicit px via the theme token, so they never compound with this.
 *  - `--app-font-scale`, consumed by the semantic typography tokens in
 *    tokens.css (`calc(<baseline>px * var(--app-font-scale))`) for project
 *    styles that declare an explicit px size.
 * At the default size both resolve to no-ops (100% / scale 1), leaving the
 * current appearance unchanged.
 */
export function applyUiFontSizeToRoot(size: number): void {
  if (typeof document === "undefined") return;
  const clamped = clampUiFontSize(size);
  const scale = clamped / UI_FONT_SIZE_DEFAULT;
  const percent = Math.round(scale * 100 * 1000) / 1000;
  const root = document.documentElement;
  root.style.fontSize = `${percent}%`;
  root.style.setProperty(
    "--app-font-scale",
    String(Math.round(scale * 1000) / 1000),
  );
}
