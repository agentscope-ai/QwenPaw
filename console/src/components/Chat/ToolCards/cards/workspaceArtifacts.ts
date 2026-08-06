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
  modified_ns: number;
  change: "created" | "modified";
  preview: WorkspaceArtifactPreviewKind;
}

export interface ArtifactManifest {
  version: number;
  agent_id: string;
  chat_id: string;
  turn_id: string;
  created_at: string;
  artifacts: ArtifactEntry[];
  changes: Array<{
    path: string;
    change: "created" | "modified" | "deleted";
  }>;
  truncated: boolean;
}

type ArtifactChangeEntry = ArtifactManifest["changes"][number];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isNonNegativeFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isArtifactEntry(value: unknown): value is ArtifactEntry {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.path) &&
    isNonEmptyString(value.name) &&
    typeof value.extension === "string" &&
    isNonEmptyString(value.mime_type) &&
    isNonNegativeSafeInteger(value.size) &&
    isNonNegativeFiniteNumber(value.modified_ns) &&
    (value.change === "created" || value.change === "modified") &&
    isWorkspaceArtifactPreviewKind(value.preview)
  );
}

function isArtifactChange(
  value: unknown,
): value is "created" | "modified" | "deleted" {
  return value === "created" || value === "modified" || value === "deleted";
}

function isArtifactChangeEntry(value: unknown): value is ArtifactChangeEntry {
  return (
    isRecord(value) &&
    isNonEmptyString(value.path) &&
    isArtifactChange(value.change)
  );
}

export function parseManifest(result: unknown): ArtifactManifest | null {
  if (typeof result !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(result);
    if (!isRecord(parsed)) return null;
    const manifest = isRecord(parsed.manifest) ? parsed.manifest : parsed;
    const artifacts = manifest.artifacts;
    const changes = manifest.changes;
    if (
      manifest.version !== 1 ||
      !isNonEmptyString(manifest.agent_id) ||
      !isNonEmptyString(manifest.chat_id) ||
      !isNonEmptyString(manifest.turn_id) ||
      !isNonEmptyString(manifest.created_at) ||
      !Array.isArray(artifacts) ||
      !Array.isArray(changes) ||
      typeof manifest.truncated !== "boolean"
    ) {
      return null;
    }
    const validArtifacts = artifacts.filter(isArtifactEntry);
    const validChanges = changes.filter(isArtifactChangeEntry);
    if (
      validArtifacts.length !== artifacts.length ||
      validChanges.length !== changes.length
    ) {
      return null;
    }
    return {
      version: 1,
      agent_id: manifest.agent_id,
      chat_id: manifest.chat_id,
      turn_id: manifest.turn_id,
      created_at: manifest.created_at,
      artifacts: validArtifacts,
      changes: validChanges,
      truncated: manifest.truncated,
    };
  } catch {
    return null;
  }
}
