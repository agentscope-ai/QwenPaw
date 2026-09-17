/**
 * Global click interceptor for `target="_blank"` anchors inside the Tauri
 * WebView.
 *
 * Some content (e.g. chat markdown) is rendered by vendor components we cannot
 * override at the React level, so their links become native
 * `<a target="_blank" rel="noopener noreferrer">` anchors. The Tauri WebView
 * ignores such clicks entirely — no new window, no navigation — so the link
 * appears dead. This delegate catches those clicks and routes the URL through
 * `openExternalLink`, which opens it in the system browser.
 *
 * Scope is intentionally narrow to avoid hijacking in-app SPA navigation:
 * only anchors that carry `target="_blank"` are handled, and only when the URL
 * resolves to a supported external protocol (http/https/mailto/tel).
 */
import {
  openExternalLink,
  resolveSupportedExternalUrl,
} from "./openExternalLink";

/**
 * Attach a capture-phase click listener that opens `_blank` links externally.
 * Returns a disposer that removes the listener.
 */
export function interceptBlankLinkClicks(): () => void {
  const handleClick = (event: MouseEvent) => {
    // Respect modifier-key clicks and non-primary buttons (let the OS/WebView
    // do whatever it would normally do for those).
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }

    const target = event.target as Element | null;
    const anchor = target?.closest?.("a[href]") as HTMLAnchorElement | null;
    if (!anchor || anchor.target !== "_blank") {
      return;
    }

    // Use the raw attribute so we validate the author's URL rather than the
    // DOM-resolved `.href`, which would rewrite relative links to same-origin.
    const href = anchor.getAttribute("href");
    if (!href) return;

    const externalUrl = resolveSupportedExternalUrl(href);
    if (!externalUrl) return;

    event.preventDefault();
    openExternalLink(externalUrl);
  };

  document.addEventListener("click", handleClick, true);
  return () => document.removeEventListener("click", handleClick, true);
}
