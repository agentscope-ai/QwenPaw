/**
 * Open an external URL, using the pywebview bridge in desktop app or
 * window.open in browser.
 *
 * @param url - The URL to open
 * @param target - Target window name (default: "_blank")
 * @param features - Window features string (default: "noopener,noreferrer")
 */
export function openExternalLink(
  url: string,
  target: string = "_blank",
  features: string = "noopener,noreferrer",
): void {
  if (!url) return;

  // Resolve relative URLs to absolute (needed for pywebview which runs outside the WebView context)
  const fullUrl = url.startsWith("http")
    ? url
    : `${window.location.origin}${url}`;

  const pywebview = (window as any).pywebview;
  if (pywebview?.api?.open_external_link) {
    // Desktop app: use pywebview bridge to open in system browser
    pywebview.api.open_external_link(fullUrl);
  } else {
    // Web browser: use standard window.open
    window.open(fullUrl, target, features);
  }
}
