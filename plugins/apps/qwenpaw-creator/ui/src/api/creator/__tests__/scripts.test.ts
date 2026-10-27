import { describe, expect, it } from "vitest";
import { importTimelineScript } from "@/api/creator";
import { installMockFetch } from "@/test/mockFetch";

const RESULT = {
  resultKind: "script_import",
  projectId: "p1",
  timelineId: "timeline:main",
  slotId: "script:timeline:main",
  artifactVersionId: "script-1",
  fileId: "file-script-1",
  checksum: "a".repeat(64),
  blockCount: 3,
  characterCount: 42,
  generation: 4,
  etag: "etag-4",
  replayed: false,
  reviewId: null,
  changedPointers: ["/assets/artifact_slots_by_id/script:timeline:main"],
  summary: "剧本正文（3 块 / 42 字）已直接登记为该集剧本版本。",
};

describe("importTimelineScript (剧本直登)", () => {
  it("uploads a script file as multipart against the timeline route", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/timelines/timeline%3Amain/script-import",
        method: "POST",
        response: { ok: true, status: 201, json: RESULT },
      },
    ]);
    const file = new File(["## 场 1\n\n开场。"], "我的剧本.md", {
      type: "text/markdown",
    });

    const outcome = await importTimelineScript("p1", "timeline:main", { file });

    expect(outcome.artifactVersionId).toBe("script-1");
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    // FormData wraps the uploaded File, so assert its identity by name.
    const uploaded = (calls[0].body as Record<string, File>).file;
    expect(uploaded.name).toBe("我的剧本.md");
    expect(uploaded.type).toBe("text/markdown");
  });

  it("sends pasted text as a JSON body without the script bytes in a query", async () => {
    const { calls } = installMockFetch([
      {
        match: "/script-import",
        method: "POST",
        response: {
          ok: true,
          status: 201,
          json: { ...RESULT, replayed: true },
        },
      },
    ]);

    const outcome = await importTimelineScript("p1", "timeline:main", {
      content: "## 场 1\n\n开场。",
      name: "粘贴剧本",
    });

    expect(outcome.replayed).toBe(true);
    expect(calls[0].body).toEqual({
      content: "## 场 1\n\n开场。",
      name: "粘贴剧本",
    });
    expect(calls[0].headers["content-type"]).toBe("application/json");
  });

  it("sends a per-request Idempotency-Key so re-picking old content is a new edit", async () => {
    const { calls } = installMockFetch([
      {
        match: "/script-import",
        method: "POST",
        response: { ok: true, status: 201, json: RESULT },
      },
    ]);

    // Two separate imports (the A -> B -> A flow) each carry a fresh key, so
    // the backend mints a distinct edit transaction and never collides with a
    // previously committed one for the same content.
    await importTimelineScript("p1", "timeline:main", { content: "A" });
    await importTimelineScript("p1", "timeline:main", { content: "B" });
    const [first, second] = calls.map((c) => c.headers["idempotency-key"]);
    expect(first).toMatch(/^script-import-/);
    expect(second).toMatch(/^script-import-/);
    expect(first).not.toBe(second);

    // An explicit key is passed through verbatim, so a network retry of the
    // same request reuses it and the backend dedupes the retry.
    await importTimelineScript(
      "p1",
      "timeline:main",
      { content: "A" },
      "script-import-fixed",
    );
    expect(calls[2].headers["idempotency-key"]).toBe("script-import-fixed");
  });
});
