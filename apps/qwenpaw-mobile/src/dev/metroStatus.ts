const RUNNING_STATUS = "packager-status:running";

export function metroStatusUrl(
  scriptUrl: string | null | undefined,
  hostUri?: string | null,
): string | null {
  const fromScript = httpOrigin(scriptUrl);
  if (fromScript) return `${fromScript}/status`;

  if (!hostUri?.trim()) return null;
  const normalized = /^https?:\/\//i.test(hostUri)
    ? hostUri
    : `http://${hostUri}`;
  const fromHost = httpOrigin(normalized);
  return fromHost ? `${fromHost}/status` : null;
}

export function isMetroRunningStatus(body: string): boolean {
  return body.trim() === RUNNING_STATUS;
}

function httpOrigin(value: string | null | undefined): string | null {
  if (!value?.trim()) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.origin
      : null;
  } catch {
    return null;
  }
}
