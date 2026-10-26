/**
 * themeTokens.ts — project plugin theme-token overrides into the document.
 *
 * The registry (`chatExtensions`) stores what plugins asked for; this module
 * turns the winning value per token into a single managed <style> element:
 *
 *   :root          { --app-<token>: <light>; }
 *   html.dark-mode { --app-<token>: <dark>;  }
 *
 * Writing both schemes into one stylesheet — instead of setting inline custom
 * properties on <html> — keeps the same selector specificity as
 * `styles/tokens.css` (`:root` / `html.dark-mode`), so switching the scheme
 * swaps the values without the two halves fighting each other. An empty
 * snapshot removes the element entirely, leaving the bundled defaults intact.
 */
import { chatExtensions } from "./registry/chatExtensions";
import type { ChatThemeTokenSnapshot } from "./registry/chatExtensions";
import { ThemeTokens } from "./registry/slotKeys";
import type { ThemeTokenKey } from "./registry/slotKeys";

export const THEME_TOKEN_STYLE_ID = "qwenpaw-plugin-theme-tokens";

/** Declaration order is fixed so the emitted CSS is stable across renders. */
const ORDERED_TOKENS = Object.values(ThemeTokens) as ThemeTokenKey[];

/** Pure: snapshot → stylesheet text. Empty snapshot → empty string. */
export function renderThemeTokensCss(snapshot: ChatThemeTokenSnapshot): string {
  const light: string[] = [];
  const dark: string[] = [];
  for (const token of ORDERED_TOKENS) {
    const entry = snapshot[token];
    if (!entry) continue;
    light.push(`  --app-${token}: ${entry.value.light};`);
    dark.push(`  --app-${token}: ${entry.value.dark};`);
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
