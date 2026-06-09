import { describe, it, expect, vi, afterEach } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: vi.fn() }));
vi.mock("../request", () => ({ request: vi.fn() }));
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));
vi.mock("../../stores/codeFileCacheStore", () => ({
  useCodeFileCacheStore: {
    getState: () => ({ get: () => null, set: vi.fn(), invalidate: vi.fn() }),
  },
}));
vi.mock("../../utils/downloadFileFromUrl", () => ({
  downloadFileFromUrl: vi.fn(),
}));

import { request } from "../request";
import { workspaceApi } from "./workspace";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";

describe("workspaceApi.listFiles", () => {
  afterEach(() => vi.clearAllMocks());

  it("calls /workspace/files and transforms modified_time", async () => {
    vi.mocked(request).mockResolvedValue([
      { filename: "note.md", modified_time: "2024-01-15T10:00:00Z" },
    ]);

    const result = await workspaceApi.listFiles();

    expect(request).toHaveBeenCalledWith("/workspace/files");
    expect(result[0]).toHaveProperty("updated_at");
    expect(result[0].updated_at).toBe(
      new Date("2024-01-15T10:00:00Z").getTime(),
    );
  });
});

describe("workspaceApi.loadFile", () => {
  afterEach(() => vi.clearAllMocks());

  it("calls /workspace/files/<encoded> with filename", async () => {
    vi.mocked(request).mockResolvedValue({ content: "hello" });
    await workspaceApi.loadFile("my file.md");
    expect(request).toHaveBeenCalledWith("/workspace/files/my%20file.md");
  });
});

describe("workspaceApi.saveFile", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends PUT with content body to encoded path", async () => {
    vi.mocked(request).mockResolvedValue({});
    await workspaceApi.saveFile("doc.md", "# Title");
    expect(request).toHaveBeenCalledWith("/workspace/files/doc.md", {
      method: "PUT",
      body: JSON.stringify({ content: "# Title" }),
    });
  });
});

describe("workspaceApi.downloadWorkspace", () => {
  afterEach(() => vi.clearAllMocks());

  it("calls downloadFileFromUrl with correct URL and options", async () => {
    vi.mocked(downloadFileFromUrl).mockResolvedValue(undefined);
    await workspaceApi.downloadWorkspace();
    expect(downloadFileFromUrl).toHaveBeenCalledWith(
      "/api/workspace/download",
      expect.stringContaining("qwenpaw_workspace_"),
      expect.objectContaining({
        errorMessage: "Workspace download failed",
        preferResponseFilename: true,
      }),
    );
  });
});

describe("workspaceApi.uploadFile", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("sends POST with FormData to /workspace/upload", async () => {
    const mockFile = new File(["content"], "test.txt", { type: "text/plain" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, message: "ok" }),
      } as unknown as Response),
    );

    const result = await workspaceApi.uploadFile(mockFile);

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspace/upload",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual({ success: true, message: "ok" });
  });

  it("throws on upload failure", async () => {
    const mockFile = new File(["x"], "bad.txt");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 413,
        statusText: "Payload Too Large",
        text: () => Promise.resolve("File too big"),
      } as unknown as Response),
    );

    await expect(workspaceApi.uploadFile(mockFile)).rejects.toThrow(
      "Upload failed: 413 Payload Too Large - File too big",
    );
  });
});

describe("workspaceApi.listDailyMemory", () => {
  afterEach(() => vi.clearAllMocks());

  it("strips .md suffix to produce date field", async () => {
    vi.mocked(request).mockResolvedValue([
      { filename: "2024-06-01.md", modified_time: "2024-06-01T12:00:00Z" },
    ]);

    const result = await workspaceApi.listDailyMemory();

    expect(request).toHaveBeenCalledWith("/workspace/memory");
    expect(result[0].date).toBe("2024-06-01");
  });
});

describe("workspaceApi.loadDailyMemory", () => {
  afterEach(() => vi.clearAllMocks());

  it("calls /workspace/memory/<date>.md", async () => {
    vi.mocked(request).mockResolvedValue({ content: "memory" });
    await workspaceApi.loadDailyMemory("2024-06-01");
    expect(request).toHaveBeenCalledWith("/workspace/memory/2024-06-01.md");
  });
});

describe("workspaceApi.saveDailyMemory", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends PUT to /workspace/memory/<date>.md with content", async () => {
    vi.mocked(request).mockResolvedValue({});
    await workspaceApi.saveDailyMemory("2024-06-01", "today");
    expect(request).toHaveBeenCalledWith("/workspace/memory/2024-06-01.md", {
      method: "PUT",
      body: JSON.stringify({ content: "today" }),
    });
  });
});

describe("workspaceApi.getSystemPromptFiles", () => {
  afterEach(() => vi.clearAllMocks());

  it("calls /workspace/system-prompt-files", async () => {
    vi.mocked(request).mockResolvedValue(["file1.md"]);
    const result = await workspaceApi.getSystemPromptFiles();
    expect(request).toHaveBeenCalledWith("/workspace/system-prompt-files");
    expect(result).toEqual(["file1.md"]);
  });
});

describe("workspaceApi.setSystemPromptFiles", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends PUT with JSON array of filenames", async () => {
    vi.mocked(request).mockResolvedValue(["a.md", "b.md"]);
    await workspaceApi.setSystemPromptFiles(["a.md", "b.md"]);
    expect(request).toHaveBeenCalledWith("/workspace/system-prompt-files", {
      method: "PUT",
      body: JSON.stringify(["a.md", "b.md"]),
    });
  });
});
