import type { WorkspaceRoot } from "../features/files-workspace/types";

export interface WorkspaceArtifactLocator {
  agentId: string;
  chatId: string;
  path: string;
  root: WorkspaceRoot;
  rootRef?: string;
}

export type WorkspaceArtifactPreviewKind =
  | "image"
  | "pdf"
  | "markdown"
  | "csv"
  | "text"
  | "none";

export const ARTIFACT_TEXT_PREVIEW_MAX_BYTES = 5 * 1024 * 1024;
export const ARTIFACT_BINARY_PREVIEW_MAX_BYTES = 50 * 1024 * 1024;

export function getArtifactPreviewLimit(
  preview: WorkspaceArtifactPreviewKind,
): number | null {
  if (["markdown", "csv", "text"].includes(preview)) {
    return ARTIFACT_TEXT_PREVIEW_MAX_BYTES;
  }
  if (["image", "pdf"].includes(preview)) {
    return ARTIFACT_BINARY_PREVIEW_MAX_BYTES;
  }
  return null;
}

const PREVIEW_KINDS = new Set<WorkspaceArtifactPreviewKind>([
  "image",
  "pdf",
  "markdown",
  "csv",
  "text",
  "none",
]);

export function isWorkspaceArtifactPreviewKind(
  value: unknown,
): value is WorkspaceArtifactPreviewKind {
  return (
    typeof value === "string" &&
    PREVIEW_KINDS.has(value as WorkspaceArtifactPreviewKind)
  );
}
