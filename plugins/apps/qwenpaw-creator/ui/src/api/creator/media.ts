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

/** Rendered document page image (doc-page:// evidence ref). */
export function getDocumentPageUrl(
  projectId: string,
  checksum: string,
  page: number,
): string {
  return creatorAuthenticatedUrl(
    `/projects/${encodeURIComponent(projectId)}/doc-pages/${encodeURIComponent(
      checksum,
    )}/${page}`,
  );
}

const motionDocumentCache = new Map<string, Promise<string>>();

/**
 * Deterministic backend-rendered poster frame for one externalized
 * html_js motion document. The live preview never executes document
 * scripts, so this settled frame stands in for the animation.
 */
export function getMotionDocumentPosterUrl(
  fileId: string,
  width = 640,
  height = 360,
): string {
  const query = new URLSearchParams({
    format: "html_js",
    width: String(Math.max(16, Math.min(1920, Math.round(width)))),
    height: String(Math.max(16, Math.min(1080, Math.round(height)))),
  });
  return creatorAuthenticatedUrl(
    `/media/motion-documents/${encodeURIComponent(
      fileId,
    )}/poster?${query.toString()}`,
  );
}

/**
 * Self-contained playable copy of one html_js motion document: vendored
 * runtimes inlined and a postMessage seek bridge appended, so the same
 * document the render worker captures also plays in a sandboxed iframe
 * (hyperframes-style same-source preview).
 */
export function getMotionDocumentPreviewUrl(fileId: string): string {
  return creatorAuthenticatedUrl(
    `/media/motion-documents/${encodeURIComponent(fileId)}/preview`,
  );
}

/**
 * Fetch one externalized motion document body. Content-addressed and
 * immutable, so results are cached for the session.
 */
export function fetchMotionDocument(fileId: string): Promise<string> {
  const cached = motionDocumentCache.get(fileId);
  if (cached) return cached;
  const url = creatorAuthenticatedUrl(
    `/media/motion-documents/${encodeURIComponent(fileId)}`,
  );
  const request = fetch(url).then((response) => {
    if (!response.ok) {
      throw new Error(`motion document ${fileId}: HTTP ${response.status}`);
    }
    return response.text();
  });
  request.catch(() => motionDocumentCache.delete(fileId));
  motionDocumentCache.set(fileId, request);
  return request;
}
