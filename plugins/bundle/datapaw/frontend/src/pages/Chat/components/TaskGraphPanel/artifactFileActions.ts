import { filesApi } from "@/api/modules/files";
import { buildAuthHeaders } from "@/api/authHeaders";

export interface ArtifactFileLike {
  name: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  preview_url?: string;
  download_url?: string;
}

export async function downloadArtifactFile(
  file: ArtifactFileLike,
  sessionId: string,
  userId: string,
): Promise<void> {
  const url = filesApi.resolveArtifactUrl(
    file.download_url,
    file.path,
    sessionId,
    userId,
    "download",
  );
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = file.name;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(blobUrl);
}
