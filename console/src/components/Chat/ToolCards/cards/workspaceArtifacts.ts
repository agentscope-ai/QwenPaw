export interface ArtifactEntry {
  path: string;
  name: string;
  extension: string;
  mime_type: string;
  size: number;
  change: "created" | "modified";
  preview: string;
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
    const parsed = JSON.parse(result) as { manifest?: ArtifactManifest };
    const manifest = parsed.manifest ?? (parsed as ArtifactManifest);
    if (manifest.version !== 1 || !Array.isArray(manifest.artifacts)) {
      return null;
    }
    return manifest;
  } catch {
    return null;
  }
}
