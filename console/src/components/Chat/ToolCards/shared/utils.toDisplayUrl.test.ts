// Regression coverage for the toDisplayUrl() twin living in the tool-card
// shared utils.
//
// Why this file exists: the console has TWO functions named toDisplayUrl.
//   1. src/pages/Chat/utils.ts:185               — covered by pages/Chat/utils.test.ts
//   2. src/components/Chat/ToolCards/shared/utils.ts:16 — THIS one, zero coverage
// PR #7069 added the data-URL branch to (1) together with its own regression
// tests, but (2) was left untested: there is no utils.test.ts next to it, and
// the only consumer test (cards/RunToolBatchCard.test.tsx) replaces the whole
// module via vi.mock("../shared/utils", ...), stubbing toDisplayUrl to the
// identity function — so the real implementation never executes there.
//
// Scope note: this is DEFECT-PREVENTION coverage, not a claim that any open
// bug is being blocked. Both twins already carry the data: branch today
// ((2) since 84b61ca3, (1) since c6261762); these cases pin (2) so that a
// future divergence between the two implementations cannot pass unnoticed.

import { beforeEach, describe, expect, it, vi } from "vitest";

// toDisplayUrl falls through to chatApi.filePreviewUrl for backend-relative
// paths, so the API module has to be mocked the same way pages/Chat/utils.test.ts does.
vi.mock("@/api/modules/chat", () => ({
  chatApi: {
    filePreviewUrl: vi.fn((p: string) => `http://localhost:8000${p}`),
  },
}));

import { chatApi } from "@/api/modules/chat";
import { toDisplayUrl } from "./utils";

describe("toDisplayUrl (tool card shared utils)", () => {
  beforeEach(() => {
    vi.mocked(chatApi.filePreviewUrl).mockClear();
  });

  it("returns http and https URLs untouched", () => {
    expect(toDisplayUrl("http://cdn.com/img.png")).toBe(
      "http://cdn.com/img.png",
    );
    expect(toDisplayUrl("https://cdn.com/file")).toBe("https://cdn.com/file");
    expect(chatApi.filePreviewUrl).not.toHaveBeenCalled();
  });

  it("returns data URLs untouched so base64 media keeps rendering", () => {
    const dataUrl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB";

    expect(toDisplayUrl(dataUrl)).toBe(dataUrl);
  });

  it("does not route data URLs through the file preview endpoint", () => {
    const dataUrl = "data:image/png;base64,AAA=";

    expect(toDisplayUrl(dataUrl)).not.toContain("/files/preview");
    expect(chatApi.filePreviewUrl).not.toHaveBeenCalled();
  });

  it("returns an empty string when there is no URL to display", () => {
    expect(toDisplayUrl("")).toBe("");
    expect(chatApi.filePreviewUrl).not.toHaveBeenCalled();
  });

  it("strips the file:// prefix before resolving through the preview endpoint", () => {
    expect(toDisplayUrl("file:///uploads/img.png")).toBe(
      "http://localhost:8000/uploads/img.png",
    );
    expect(chatApi.filePreviewUrl).toHaveBeenCalledWith("/uploads/img.png");
  });

  it("resolves an already-rooted backend path through the preview endpoint", () => {
    expect(toDisplayUrl("/uploads/img.png")).toBe(
      "http://localhost:8000/uploads/img.png",
    );
    expect(chatApi.filePreviewUrl).toHaveBeenCalledWith("/uploads/img.png");
  });

  it("roots a relative backend path before resolving it", () => {
    expect(toDisplayUrl("uploads/img.png")).toBe(
      "http://localhost:8000/uploads/img.png",
    );
    expect(chatApi.filePreviewUrl).toHaveBeenCalledWith("/uploads/img.png");
  });

  it("keeps a non-empty URL that resolves to a falsy preview result distinguishable", () => {
    // Guards the `if (!url)` early return from being widened to a generic
    // falsy check that would also swallow legitimate inputs.
    vi.mocked(chatApi.filePreviewUrl).mockReturnValueOnce("");

    expect(toDisplayUrl("/uploads/missing.png")).toBe("");
    expect(chatApi.filePreviewUrl).toHaveBeenCalledWith("/uploads/missing.png");
  });
});
