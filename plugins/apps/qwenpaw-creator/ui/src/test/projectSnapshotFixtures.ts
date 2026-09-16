import { vi } from "vitest";

/** Minimal typed-enough JSON Response stub for store polling tests. */
export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: new Headers(headers),
    json: vi.fn(async () => body),
  } as unknown as Response;
}

/** Minimal file-native project.json document (project p1). */
export function projectJson(
  generation: number,
  name = `Project ${generation}`,
) {
  return {
    schema_version: 1,
    project_id: "p1",
    generation,
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
    name,
    description: "",
    scenario: "general",
    settings: {},
    strategy: {},
    sources: {},
    visual: {},
    story: {},
    production: {},
    post_production: {},
    assets: {},
  };
}

/** A healthy snapshot response with the generation-derived ETag. */
export function snapshotResponse(generation: number, name?: string): Response {
  return jsonResponse(
    200,
    {
      projectId: "p1",
      generation,
      etag: `sha256:g${generation}`,
      syncStatus: "healthy",
      project: projectJson(generation, name),
    },
    { ETag: `"sha256:g${generation}"` },
  );
}
