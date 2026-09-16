import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { personalLibraryApi } from "./personalLibrary";

describe("personalLibraryApi", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("scopes library reads and writes to the selected agent", async () => {
    const context = { agentId: "agent-b" };
    const file = new File(["guide"], "guide.md", { type: "text/markdown" });

    await personalLibraryApi.list("", context);
    await personalLibraryApi.upload(file, context);
    await personalLibraryApi.copyArtifact(
      { sourcePath: "artifacts/report.pdf", destinationPath: "report.pdf" },
      context,
    );

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/console/personal-library/documents?path=",
      { headers: { "X-Agent-Id": "agent-b" } },
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/console/personal-library/documents/upload",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
        headers: { "X-Agent-Id": "agent-b" },
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/console/personal-library/imports/artifact",
      expect.objectContaining({ headers: { "X-Agent-Id": "agent-b" } }),
    );
  });

  it("builds an authenticated binary download route", () => {
    expect(personalLibraryApi.downloadUrl("doc 1")).toBe(
      "/api/console/personal-library/documents/doc%201/download",
    );
  });
});
