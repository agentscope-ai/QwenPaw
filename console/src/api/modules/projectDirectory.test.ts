import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ""),
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));

import { projectDirectoryApi } from "./projectDirectory";
import { request } from "../request";

describe("projectDirectoryApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("get calls GET /workspace/project-directory", async () => {
    const info = { path: "/p", name: "p", is_workspace_default: false };
    vi.mocked(request).mockResolvedValue(info);
    const result = await projectDirectoryApi.get();
    expect(request).toHaveBeenCalledWith("/workspace/project-directory");
    expect(result).toEqual(info);
  });

  it("set(null) sends PUT with path null body", async () => {
    await projectDirectoryApi.set(null);
    expect(request).toHaveBeenCalledWith("/workspace/project-directory", {
      method: "PUT",
      body: JSON.stringify({ path: null }),
    });
  });

  it("create sends POST with name body", async () => {
    await projectDirectoryApi.create("my-proj");
    expect(request).toHaveBeenCalledWith(
      "/workspace/project-directory/create",
      {
        method: "POST",
        body: JSON.stringify({ name: "my-proj" }),
      },
    );
  });

  it("list calls GET /workspace/project-directory/list", async () => {
    await projectDirectoryApi.list();
    expect(request).toHaveBeenCalledWith("/workspace/project-directory/list");
  });

  it("importLocal sends POST with path and name when provided", async () => {
    await projectDirectoryApi.importLocal("/src/old", "renamed");
    expect(request).toHaveBeenCalledWith(
      "/workspace/project-directory/import-local",
      {
        method: "POST",
        body: JSON.stringify({ path: "/src/old", name: "renamed" }),
      },
    );
  });

  it("importLocal sends undefined name when not provided", async () => {
    await projectDirectoryApi.importLocal("/src/old");
    expect(request).toHaveBeenCalledWith(
      "/workspace/project-directory/import-local",
      {
        method: "POST",
        body: JSON.stringify({ path: "/src/old", name: undefined }),
      },
    );
  });

  it("browseDirs URL-encodes path and appends show_hidden when set", async () => {
    await projectDirectoryApi.browseDirs("/ho me", true);
    expect(request).toHaveBeenCalledWith(
      `/workspace/project-directory/browse-dirs?path=${encodeURIComponent(
        "/ho me",
      )}&show_hidden=true`,
    );
  });

  it("browseDirs defaults path to ~ when omitted", async () => {
    await projectDirectoryApi.browseDirs();
    expect(request).toHaveBeenCalledWith(
      `/workspace/project-directory/browse-dirs?path=${encodeURIComponent(
        "~",
      )}`,
    );
  });

  it("uploadZip returns json on success and posts FormData to upload-zip", async () => {
    const json = { path: "/p", name: "p" };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(json),
    } as unknown as Response);

    const file = new File(["data"], "proj.zip", { type: "application/zip" });
    const result = await projectDirectoryApi.uploadZip(file, "proj");

    expect(result).toEqual(json);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      `/api/workspace/project-directory/upload-zip?name=${encodeURIComponent(
        "proj",
      )}`,
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("uploadZip throws when response not ok, propagating text", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      text: () => Promise.resolve("File too large"),
    } as unknown as Response);

    const file = new File(["data"], "big.zip");
    await expect(projectDirectoryApi.uploadZip(file, "big")).rejects.toThrow(
      "File too large",
    );
  });

  it("cloneStream posts JSON with auth headers and returns the Response", async () => {
    const rawResponse = { ok: true, status: 200 } as unknown as Response;
    global.fetch = vi.fn().mockResolvedValue(rawResponse);

    const result = await projectDirectoryApi.cloneStream(
      "https://git.example/x.git",
      "x",
    );

    expect(result).toBe(rawResponse);
    expect(fetch).toHaveBeenCalledWith(
      "/api/workspace/project-directory/clone",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: "https://git.example/x.git",
          name: "x",
        }),
      },
    );
  });

  it("cloneStream sends undefined name when not provided", async () => {
    global.fetch = vi.fn().mockResolvedValue({} as Response);

    await projectDirectoryApi.cloneStream("https://git.example/y.git");

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspace/project-directory/clone",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: "https://git.example/y.git",
          name: undefined,
        }),
      },
    );
  });
});
