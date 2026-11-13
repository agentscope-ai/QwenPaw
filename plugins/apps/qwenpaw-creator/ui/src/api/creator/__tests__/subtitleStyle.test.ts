import { describe, expect, it } from "vitest";

import { setSubtitleStyle } from "@/api/creator";
import { installMockFetch } from "@/test/mockFetch";

const RESULT = {
  ok: true,
  generation: 7,
  subtitleTemplate: "variety_pop",
  subtitleStyle: null,
  styleLine: "综艺花字：特粗无衬线大字",
  syncedPrompts: 12,
  redrawnDocuments: 12,
  skippedNonTemplate: 0,
};

describe("setSubtitleStyle", () => {
  it("patches the subtitle style route and returns what the sync reached", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/subtitles/style",
        method: "PATCH",
        response: { ok: true, status: 200, json: RESULT },
      },
    ]);

    const outcome = await setSubtitleStyle("p1", {
      subtitleTemplate: "variety_pop",
    });

    expect(outcome.redrawnDocuments).toBe(12);
    // The refusal counter has to survive the round trip: without it the UI can
    // only ever claim a full success.
    expect(outcome.skippedNonTemplate).toBe(0);
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ subtitleTemplate: "variety_pop" });
  });

  it("sends only the keys the caller set, so an untouched control cannot reset the project", async () => {
    const { calls } = installMockFetch([
      {
        match: "/subtitles/style",
        method: "PATCH",
        response: { ok: true, status: 200, json: RESULT },
      },
    ]);

    await setSubtitleStyle("p1", {
      animation: { entrance: "slide", loop: false },
      elementIds: ["caption-1"],
    });

    expect(calls[0].body).toEqual({
      animation: { entrance: "slide", loop: false },
      elementIds: ["caption-1"],
    });
  });

  it("reports captions whose own design beat the pack", async () => {
    installMockFetch([
      {
        match: "/subtitles/style",
        method: "PATCH",
        response: {
          ok: true,
          status: 200,
          json: {
            ...RESULT,
            syncedPrompts: 0,
            redrawnDocuments: 0,
            skippedNonTemplate: 2,
          },
        },
      },
    ]);

    const outcome = await setSubtitleStyle("p1", {
      animation: { entrance: "pop" },
      elementIds: ["cap-1", "cap-2"],
    });

    expect(outcome).toMatchObject({
      syncedPrompts: 0,
      redrawnDocuments: 0,
      skippedNonTemplate: 2,
    });
  });

  it("keeps an explicit null so the UI can go back to smart recommend", async () => {
    const { calls } = installMockFetch([
      {
        match: "/subtitles/style",
        method: "PATCH",
        response: { ok: true, status: 200, json: RESULT },
      },
    ]);

    await setSubtitleStyle("p1", {
      subtitleTemplate: null,
      subtitleStyle: null,
    });

    expect(calls[0].body).toEqual({
      subtitleTemplate: null,
      subtitleStyle: null,
    });
  });
});
