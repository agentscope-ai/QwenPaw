import type {
  AssetImportAccepted,
  AssetImportView,
  AssetIngestAccepted,
  PostIngestAction,
} from "@/contracts/creator";
import {
  creatorAuthenticatedUrl,
  creatorRequest,
  jsonBody,
  newClientId,
} from "./client";

const assetsPath = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/assets`;

export function ingestAssetFile(
  projectId: string,
  file: File,
  postIngestAction: PostIngestAction,
  clientRequestId = newClientId("asset"),
): Promise<AssetIngestAccepted> {
  const form = new FormData();
  form.append("clientRequestId", clientRequestId);
  form.append("postIngestAction", postIngestAction);
  form.append("file", file, file.name);
  return creatorRequest(assetsPath(projectId), {
    method: "POST",
    headers: { "Idempotency-Key": clientRequestId },
    body: form,
  });
}

export function ingestAssetValue(
  projectId: string,
  input: {
    kind: "url" | "text";
    name: string;
    value: string;
    postIngestAction: PostIngestAction;
  },
  clientRequestId = newClientId("asset"),
): Promise<AssetIngestAccepted> {
  return creatorRequest(assetsPath(projectId), {
    method: "POST",
    headers: { "Idempotency-Key": clientRequestId },
    body: jsonBody({ clientRequestId, ...input }),
  });
}

export function createAssetImport(
  projectId: string,
  files: File[],
  postIngestAction: PostIngestAction,
  clientRequestId = newClientId("asset-import"),
): Promise<AssetImportAccepted> {
  const form = new FormData();
  form.append("clientRequestId", clientRequestId);
  form.append("postIngestAction", postIngestAction);
  form.append(
    "relativePaths",
    JSON.stringify(
      files.map(
        (file) =>
          (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
          file.name,
      ),
    ),
  );
  files.forEach((file) =>
    form.append(
      "files",
      file,
      (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
        file.name,
    ),
  );
  return creatorRequest(
    `/projects/${encodeURIComponent(projectId)}/asset-imports`,
    {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId },
      body: form,
    },
  );
}

export function getAssetImport(
  projectId: string,
  importId: string,
): Promise<AssetImportView> {
  return creatorRequest(
    `/projects/${encodeURIComponent(
      projectId,
    )}/asset-imports/${encodeURIComponent(importId)}`,
  );
}

export function getAssetContentUrl(
  projectId: string,
  assetId: string,
  assetVersionId?: string,
): string {
  const query = assetVersionId
    ? `?versionId=${encodeURIComponent(assetVersionId)}`
    : "";
  return creatorAuthenticatedUrl(
    `/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(
      assetId,
    )}/content${query}`,
  );
}

export function getAssetUnderstanding(
  projectId: string,
  assetId: string,
  versionId?: string,
) {
  const suffix = versionId ? `/${encodeURIComponent(versionId)}` : "";
  return creatorRequest<import("@/contracts/creator").AssetUnderstandingView>(
    `${assetsPath(projectId)}/${encodeURIComponent(
      assetId,
    )}/understanding${suffix}`,
  );
}

export function querySourceIndex(
  projectId: string,
  assetId: string,
  query: string,
) {
  return creatorRequest<Record<string, unknown>>(
    `${assetsPath(projectId)}/${encodeURIComponent(
      assetId,
    )}/source-index/query?query=${encodeURIComponent(query)}`,
  );
}
