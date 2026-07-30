import { creatorAuthenticatedUrl } from "./client";

export function getAssetVersionMediaUrl(versionId: string): string {
  return creatorAuthenticatedUrl(
    `/media/assets/${encodeURIComponent(versionId)}`,
  );
}

export function getAssetVersionFrameUrl(
  versionId: string,
  timestamp: number,
  width = 640,
): string {
  const query = new URLSearchParams({
    timestamp: Math.max(0, timestamp).toFixed(3),
    width: String(width),
  });
  return creatorAuthenticatedUrl(
    `/media/assets/${encodeURIComponent(versionId)}/frame?${query.toString()}`,
  );
}

export function getArtifactVersionMediaUrl(versionId: string): string {
  return creatorAuthenticatedUrl(
    `/media/artifacts/${encodeURIComponent(versionId)}`,
  );
}

export function getArtifactVersionFrameUrl(
  versionId: string,
  timestamp = 0,
  width = 640,
): string {
  const query = new URLSearchParams({
    timestamp: Math.max(0, timestamp).toFixed(3),
    width: String(width),
  });
  return creatorAuthenticatedUrl(
    `/media/artifacts/${encodeURIComponent(
      versionId,
    )}/frame?${query.toString()}`,
  );
}

export function getGeneratedMediaUrl(url: string): string {
  if (url.startsWith("/generated/")) return creatorAuthenticatedUrl(url);
  return url;
}
