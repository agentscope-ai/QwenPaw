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
  it("returns a validated snapshot envelope, then honours If-None-Match with a 304", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
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
      )
      .mockResolvedValueOnce(
        response(304, undefined, {
          ETag: '"sha256:header"',
          "X-Project-Generation": "8",
          "X-Project-Sync-Status": "healthy",
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    // The HTTP entity tag wins over the body etag.
    await expect(getProjectSnapshot("p1")).resolves.toMatchObject({
      kind: "updated",
      projectId: "p1",
      generation: 8,
      etag: '"sha256:header"',
      syncStatus: "healthy",
    });
    await expect(getProjectSnapshot("p1", '"sha256:header"')).resolves.toEqual({
      kind: "not_modified",
      etag: '"sha256:header"',
      generation: 8,
      syncStatus: "healthy",
    });
    const request = fetchMock.mock.calls[1];
    expect(request[0]).toBe("/api/qwenpaw-creator/projects/p1/project");
    expect(new Headers(request[1]?.headers).get("If-None-Match")).toBe(
      '"sha256:header"',
    );
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
