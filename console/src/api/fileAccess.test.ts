import { beforeEach, expect, it, vi } from "vitest";
import { protectedFileApiPath, readFileResponse } from "./fileAccess";
import { request } from "./request";

vi.mock("./request", () => ({ request: vi.fn() }));
vi.mock("./config", () => ({ getApiUrl: (path: string) => `/api${path}` }));
beforeEach(() => vi.clearAllMocks());

it("refreshes protected file requests through the common client with explicit agent scope", async () => {
  vi.mocked(request).mockResolvedValue("PDF");
  await expect(
    readFileResponse(
      "/api/console/artifacts/id/download?token=expired",
      { agentId: "own-agent" },
      (response) => response.text(),
      { headers: { "X-Chat-Id": "own-chat" } },
    ),
  ).resolves.toBe("PDF");
  expect(request).toHaveBeenCalledWith(
    "/console/artifacts/id/download",
    expect.objectContaining({
      headers: { "X-Agent-Id": "own-agent", "X-Chat-Id": "own-chat" },
      readResponse: expect.any(Function),
    }),
  );
});

it("never treats an external lookalike as an authenticated file API", async () => {
  const url =
    "https://untrusted.invalid/api/console/artifacts/id/download?token=x";
  expect(protectedFileApiPath(url)).toBeNull();
  const fetchMock = vi.fn().mockResolvedValue(new Response("external"));
  vi.stubGlobal("fetch", fetchMock);
  try {
    await readFileResponse(
      url,
      { agentId: "private-agent" },
      (response) => response.text(),
      { headers: { Authorization: "private" } },
    );
    expect(request).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(url, {
      signal: undefined,
      credentials: "omit",
    });
  } finally {
    vi.unstubAllGlobals();
  }
});

it.each([
  "console/attachments/file-id",
  "console/personal-library/documents/document-id/download",
  "workspace/file-download?path=report.pdf",
])(
  "authenticates explicit Agent file URLs using their original scope: %s",
  async (resource) => {
    vi.mocked(request).mockResolvedValue("owned-file");
    const separator = resource.includes("?") ? "&" : "?";
    const url = `/api/agents/original-agent/${resource}${separator}token=expired`;
    const expected = `/agents/original-agent/${resource}`;
    expect(protectedFileApiPath(url)).toBe(expected);
    await expect(
      readFileResponse(url, { agentId: "newly-selected-agent" }, (response) =>
        response.text(),
      ),
    ).resolves.toBe("owned-file");
    expect(request).toHaveBeenCalledWith(
      expected,
      expect.objectContaining({
        headers: { "X-Agent-Id": "original-agent" },
      }),
    );
    expect(protectedFileApiPath(`https://untrusted.invalid${url}`)).toBeNull();
  },
);
