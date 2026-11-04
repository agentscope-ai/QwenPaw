/**
 * themeTokens.ts — project plugin theme-token overrides into the document.
 *
 * The registry (`chatExtensions`) stores what plugins asked for; this module
 * turns the winning value per token into a single managed <style> element:
 *
 *   :root          { --app-<token>: <light> !important; }
 *   html.dark-mode { --app-<token>: <dark>  !important; }
 *
 * Priority: the user's theme preset is applied by App.tsx as *inline* custom
 * properties on <html> (`--app-surface`, `--app-accent`, …). Inline author
 * declarations outrank any stylesheet, so a plain rule here would lose on
 * every preset and the override would silently do nothing. Author
 * `!important` declarations outrank inline non-important ones, which is the
 * one lever a stylesheet has over `<html style>` — that is why each
 * declaration is emitted with `!important`.
 *
 * Logout: the preset is never mutated. It keeps living in the inline style
 * attribute, so disposing the last override (which removes this element)
 * restores the user's current preset with no extra round-trip.
 *
 * Keeping both schemes in one stylesheet (rather than one inline value)
 * matters too: inline custom properties cannot express a light/dark pair, and
 * reusing the `tokens.css` selectors keeps specificity identical so a scheme
 * flip needs no JS.
 */
import { chatExtensions } from "./registry/chatExtensions";
import type { ChatThemeTokenSnapshot } from "./registry/chatExtensions";
import { ThemeTokens } from "./registry/slotKeys";
import type { ThemeTokenKey } from "./registry/slotKeys";

export const THEME_TOKEN_STYLE_ID = "qwenpaw-plugin-theme-tokens";

/** Declaration order is fixed so the emitted CSS is stable across renders. */
const ORDERED_TOKENS = Object.values(ThemeTokens) as ThemeTokenKey[];

// The preset writes the same custom properties inline on <html>, which beats
// any normal stylesheet declaration; `!important` is what lets a plugin layer
// win without touching (or having to restore) the user's preset.
const IMPORTANT = " !important";

/** Pure: snapshot → stylesheet text. Empty snapshot → empty string. */
export function renderThemeTokensCss(snapshot: ChatThemeTokenSnapshot): string {
  const light: string[] = [];
  const dark: string[] = [];
  for (const token of ORDERED_TOKENS) {
    const entry = snapshot[token];
    if (!entry) continue;
    light.push(`  --app-${token}: ${entry.value.light}${IMPORTANT};`);
    dark.push(`  --app-${token}: ${entry.value.dark}${IMPORTANT};`);
  }
  if (light.length === 0) return "";
  return `:root {\n${light.join("\n")}\n}\n\nhtml.dark-mode {\n${dark.join(
    "\n",
  )}\n}\n`;
}

/**
 * Apply the current snapshot to the document. Idempotent: the element is
 * reused, and its text is only rewritten when the css actually changed.
 */
export function syncThemeTokens(
  snapshot: ChatThemeTokenSnapshot = chatExtensions.getThemeTokenSnapshot(),
): void {
  if (typeof document === "undefined") return;

  const css = renderThemeTokensCss(snapshot);
  const existing = document.getElementById(THEME_TOKEN_STYLE_ID);

  if (css === "") {
    existing?.remove();
    return;
  }

  const style = (existing as HTMLStyleElement | null) ?? createStyleElement();
  if (style.textContent !== css) style.textContent = css;
}

/** Append last in <head> so it wins ties against the bundled stylesheet. */
function createStyleElement(): HTMLStyleElement {
  const style = document.createElement("style");
  style.id = THEME_TOKEN_STYLE_ID;
  (document.head ?? document.documentElement).appendChild(style);
  return style;
}

/**
 * Subscribe the document to registry changes. Call once at startup.
 * Returns an unsubscribe callback (used by tests and by teardown).
 */
export function installThemeTokenSync(): () => void {
  const unsubscribe = chatExtensions.subscribe(() => syncThemeTokens());
  syncThemeTokens();
  return () => {
    unsubscribe();
    if (typeof document !== "undefined") {
      document.getElementById(THEME_TOKEN_STYLE_ID)?.remove();
    }
  };
}
