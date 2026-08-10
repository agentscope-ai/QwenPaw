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
  root: ArtifactRoot;
  root_ref?: string;
}

export type ArtifactRoot = "workspace" | "project";

export interface ArtifactManifest {
  version: 1 | 2 | 3;
  agent_id: string;
  chat_id: string;
  turn_id: string;
  created_at: string;
  artifacts: ArtifactEntry[];
  changes: Array<{
    path: string;
    change: "created" | "modified" | "deleted";
    root: ArtifactRoot;
    root_ref?: string;
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

function isArtifactRoot(value: unknown): value is ArtifactRoot {
  return value === "workspace" || value === "project";
}

function parseArtifactEntry(
  value: unknown,
  version: 1 | 2 | 3,
): ArtifactEntry | null {
  if (!isRecord(value)) return null;
  if (
    isNonEmptyString(value.path) &&
    isNonEmptyString(value.name) &&
    typeof value.extension === "string" &&
    isNonEmptyString(value.mime_type) &&
    isNonNegativeSafeInteger(value.size) &&
    isNonNegativeFiniteNumber(value.modified_ns) &&
    (value.change === "created" || value.change === "modified") &&
    isWorkspaceArtifactPreviewKind(value.preview) &&
    (version === 1 || isArtifactRoot(value.root)) &&
    (version !== 3 || isNonEmptyString(value.root_ref))
  ) {
    return {
      path: value.path,
      name: value.name,
      extension: value.extension,
      mime_type: value.mime_type,
      size: value.size,
      modified_ns: value.modified_ns,
      change: value.change,
      preview: value.preview,
      root: version === 1 ? "workspace" : (value.root as ArtifactRoot),
      ...(version === 3 ? { root_ref: value.root_ref as string } : {}),
    };
  }
  return null;
}

function isArtifactChange(
  value: unknown,
): value is "created" | "modified" | "deleted" {
  return value === "created" || value === "modified" || value === "deleted";
}

function parseArtifactChangeEntry(
  value: unknown,
  version: 1 | 2 | 3,
): ArtifactChangeEntry | null {
  if (
    isRecord(value) &&
    isNonEmptyString(value.path) &&
    isArtifactChange(value.change) &&
    (version === 1 || isArtifactRoot(value.root)) &&
    (version !== 3 || isNonEmptyString(value.root_ref))
  ) {
    return {
      path: value.path,
      change: value.change,
      root: version === 1 ? "workspace" : (value.root as ArtifactRoot),
      ...(version === 3 ? { root_ref: value.root_ref as string } : {}),
    };
  }
  return null;
}

export function parseManifest(result: unknown): ArtifactManifest | null {
  if (typeof result !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(result);
    if (!isRecord(parsed)) return null;
    const manifest = isRecord(parsed.manifest) ? parsed.manifest : parsed;
    const artifacts = manifest.artifacts;
    const changes = manifest.changes;
    const version = manifest.version;
    if (
      (version !== 1 && version !== 2 && version !== 3) ||
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
    const validArtifacts = artifacts.map((item) =>
      parseArtifactEntry(item, version),
    );
    const validChanges = changes.map((item) =>
      parseArtifactChangeEntry(item, version),
    );
    if (
      validArtifacts.some((item) => item === null) ||
      validChanges.some((item) => item === null)
    ) {
      return null;
    }
    return {
      version,
      agent_id: manifest.agent_id,
      chat_id: manifest.chat_id,
      turn_id: manifest.turn_id,
      created_at: manifest.created_at,
      artifacts: validArtifacts as ArtifactEntry[],
      changes: validChanges as ArtifactChangeEntry[],
      truncated: manifest.truncated,
    };
  } catch {
    return null;
  }
}
