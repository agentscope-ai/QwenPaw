import {
  isWorkspaceArtifactPreviewKind,
  type WorkspaceArtifactPreviewKind,
} from "../../../../types/workspaceArtifacts";

export interface ArtifactEntry {
  path: string;
  name: string;
  extension: string;
  mime_type: string;
  size: number;
  change: "created" | "modified";
  preview: WorkspaceArtifactPreviewKind;
}

export interface ArtifactManifest {
  version: number;
  agent_id: string;
  chat_id: string;
  turn_id: string;
  artifacts: ArtifactEntry[];
  changes: Array<{ path: string; change: string }>;
  truncated: boolean;
}

export function parseManifest(result: unknown): ArtifactManifest | null {
  if (typeof result !== "string") return null;
  try {
    const parsed = JSON.parse(result) as { manifest?: unknown };
    const manifest = parsed.manifest ?? parsed;
    if (typeof manifest !== "object" || manifest === null) {
      return null;
    }
    const candidate = manifest as Partial<ArtifactManifest>;
    if (candidate.version !== 1 || !Array.isArray(candidate.artifacts)) {
      return null;
    }
    if (
      candidate.artifacts.some(
        (artifact) =>
          typeof artifact !== "object" ||
          artifact === null ||
          !isWorkspaceArtifactPreviewKind(artifact.preview),
      )
    ) {
      return null;
    }
    return candidate as ArtifactManifest;
  } catch {
    return null;
  }
}
