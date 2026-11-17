import { beforeEach, describe, expect, it, vi } from "vitest";

import { creatorRequest } from "@/api/creator/client";

/**
 * The measured duplication this guards against: one Project page issued the
 * execution-authorization lookup five times, the active-review lookup three
 * and the Project document three, while the backend's GIL sat at 96% busy.
 */
describe("creatorRequest in-flight dedupe", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  function installFetch(payload: unknown) {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        urls.push(String(input));
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }),
    );
    return urls;
  }

  it("shares one GET while it is still outstanding", async () => {
    const urls = installFetch({ ok: true });
    const path = "/projects/p-1/execution-authorizations?status=PENDING";

    const [first, second, third] = await Promise.all([
      creatorRequest(path),
      creatorRequest(path),
      creatorRequest(path),
    ]);

    expect(urls).toHaveLength(1);
    expect(second).toEqual(first);
    expect(third).toEqual(first);
  });

  it("issues a fresh request once the previous one settles", async () => {
    const urls = installFetch({ ok: true });

    await creatorRequest("/models/tts-capabilities");
    await creatorRequest("/models/tts-capabilities");

    expect(urls).toHaveLength(2);
  });

  it("never dedupes a different path, a body, or a caller's own signal", async () => {
    const urls = installFetch({ ok: true });

    await Promise.all([
      creatorRequest("/a"),
      creatorRequest("/b"),
      creatorRequest("/a", { method: "POST", body: "{}" }),
      creatorRequest("/a", { signal: new AbortController().signal }),
    ]);

    expect(urls).toHaveLength(4);
  });

  it("shares the failure too, so a 500 cannot stampede the server", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        urls.push(String(input));
        return Promise.resolve(
          new Response(JSON.stringify({ code: "STORAGE_INTEGRITY_ERROR" }), {
            status: 503,
            headers: { "content-type": "application/json" },
          }),
        );
      }),
    );

    const settled = await Promise.allSettled([
      creatorRequest("/media/artifacts/artifact-version-1"),
      creatorRequest("/media/artifacts/artifact-version-1"),
    ]);

    expect(urls).toHaveLength(1);
    expect(settled.every((entry) => entry.status === "rejected")).toBe(true);
  });
});
