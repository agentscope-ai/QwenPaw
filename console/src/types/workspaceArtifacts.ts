export type WorkspaceArtifactPreviewKind =
  | "image"
  | "pdf"
  | "markdown"
  | "csv"
  | "text"
  | "none";

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
