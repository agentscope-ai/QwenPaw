/** Shared validation for permanent PawApp identity and route scoping. */

const APP_ID_PATTERN = /^[a-z0-9][a-z0-9-]*$/;

export function normalizeAppId(appId: string): string {
  const normalized = appId.trim();
  if (!APP_ID_PATTERN.test(normalized)) {
    throw new Error(`Invalid PawApp id: ${appId}`);
  }
  return normalized;
}

function decodeForValidation(path: string): string {
  let decoded = path;
  // Decode repeatedly so double-encoded traversal cannot cross an app scope
  // after a browser, reverse proxy, or backend performs another decode pass.
  for (let pass = 0; pass < 8; pass += 1) {
    let next: string;
    try {
      next = decodeURIComponent(decoded);
    } catch {
      throw new Error(`Invalid PawApp path encoding: ${path}`);
    }
    if (next === decoded) return decoded;
    decoded = next;
  }
  throw new Error(`PawApp path has excessive encoding depth: ${path}`);
}

function hasControlCharacters(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x1f || code === 0x7f;
  });
}

/**
 * Return an app-relative URL path with exactly one leading slash.
 * Query parameters must use PawRequestOptions.query so scope checks cannot be
 * bypassed by URL parsing differences between the browser and backend.
 */
export function normalizeAppRelativePath(path: string): string {
  if (/^[a-z][a-z\d+.-]*:/i.test(path)) {
    throw new Error("PawApp paths must be relative, not absolute URLs");
  }

  const normalized = path.startsWith("/") ? path : `/${path}`;
  const decoded = decodeForValidation(normalized);
  if (
    normalized.startsWith("//") ||
    decoded.startsWith("//") ||
    decoded.includes("\\") ||
    decoded.includes("?") ||
    decoded.includes("#") ||
    hasControlCharacters(decoded)
  ) {
    throw new Error(`Invalid PawApp scoped path: ${path}`);
  }

  if (
    decoded.split("/").some((segment) => segment === "." || segment === "..")
  ) {
    throw new Error(`PawApp path cannot contain dot segments: ${path}`);
  }
  return normalized;
}
