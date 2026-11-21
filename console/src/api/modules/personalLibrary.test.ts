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

  it("scopes index operations and passes cancellation through", async () => {
    const context = {agentId: "agent-b"};
    const controller = new AbortController();
    await personalLibraryApi.indexStatus(context);
    await personalLibraryApi.rebuildIndex(["doc-b"], context, controller.signal);
    expect(request).toHaveBeenNthCalledWith(1, "/console/personal-library/index", {headers: {"X-Agent-Id": "agent-b"}});
    expect(request).toHaveBeenNthCalledWith(2, "/console/personal-library/index/rebuild", expect.objectContaining({
      method: "POST", headers: {"X-Agent-Id": "agent-b"}, signal: controller.signal,
      body: JSON.stringify({document_ids: ["doc-b"]}),
    }));
  });
});
