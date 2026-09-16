import { describe, expect, it, vi } from "vitest";
import { copyProject } from "@/api/creator";

function response(status: number, body?: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: new Headers(),
    json: vi.fn(async () => body),
  } as unknown as Response;
}

describe("Project API", () => {
  it("uses the caller-stable idempotency key for copy retries", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init: RequestInit = {}) =>
        response(201, { projectId: "copy-1" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await copyProject("source-1", "copy-operation-1");
    await copyProject("source-1", "copy-operation-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init.headers).get("Idempotency-Key")).toBe(
        "copy-operation-1",
      );
    }
  });
});
