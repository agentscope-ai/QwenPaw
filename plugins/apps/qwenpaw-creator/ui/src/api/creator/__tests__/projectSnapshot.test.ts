import { describe, expect, it, vi } from "vitest";
import { getProjectSnapshot } from "@/api/creator";

function response(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 304 ? "Not Modified" : "OK",
    headers: new Headers(headers),
    json: vi.fn(async () => body),
  } as unknown as Response;
}

function project(generation: number) {
  return {
    schema_version: 1,
    project_id: "p1",
    generation,
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
    name: "Project",
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

describe("Project snapshot API", () => {
  it("sends If-None-Match and treats 304 plus Project headers as a successful result", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        response(304, undefined, {
          ETag: '"sha256:g7"',
          "X-Project-Generation": "7",
          "X-Project-Sync-Status": "healthy",
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProjectSnapshot("p1", '"sha256:g7"')).resolves.toEqual({
      kind: "not_modified",
      etag: '"sha256:g7"',
      generation: 7,
      syncStatus: "healthy",
    });
    const request = fetchMock.mock.calls[0];
    expect(request[0]).toBe("/api/qwenpaw-creator/projects/p1/project");
    expect(new Headers(request[1]?.headers).get("If-None-Match")).toBe(
      '"sha256:g7"',
    );
  });

  it("returns a validated snapshot envelope and prefers the HTTP entity tag", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response(
          200,
          {
            projectId: "p1",
            generation: 8,
            etag: "sha256:body",
            syncStatus: "healthy",
            project: project(8),
          },
          { ETag: '"sha256:header"' },
        ),
      ),
    );

    const result = await getProjectSnapshot("p1");
    expect(result).toMatchObject({
      kind: "updated",
      projectId: "p1",
      generation: 8,
      etag: '"sha256:header"',
      syncStatus: "healthy",
    });
  });

  it("exposes PROJECT_INVALID as sync state instead of raw Project data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response(409, {
          code: "PROJECT_INVALID",
          syncStatus: "invalid",
          lastGoodGeneration: 8,
          message: "schema validation failed",
        }),
      ),
    );

    await expect(getProjectSnapshot("p1", '"sha256:g8"')).resolves.toEqual({
      kind: "invalid",
      code: "PROJECT_INVALID",
      syncStatus: "invalid",
      lastGoodGeneration: 8,
      message: "schema validation failed",
    });
  });
});
