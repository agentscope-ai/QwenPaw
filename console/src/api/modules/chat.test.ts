import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { chatApi } from "./chat";
import { isConversationReadOnly } from "../types/chat";

// chat.ts uses both fetch (uploadFile) and the request wrapper (others) — mock both
vi.mock("../request", () => ({ request: vi.fn() }));
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ""),
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));

import { request } from "../request";
import { getApiToken } from "../config";

// ---------------------------------------------------------------------------
// filePreviewUrl — pure function, highest ROI
// ---------------------------------------------------------------------------
describe("chatApi.filePreviewUrl", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns empty string for empty input", () => {
    expect(chatApi.filePreviewUrl("")).toBe("");
  });

  it("returns http URL as-is", () => {
    expect(chatApi.filePreviewUrl("http://cdn.com/img.png")).toBe(
      "http://cdn.com/img.png",
    );
  });

  it("returns https URL as-is", () => {
    expect(chatApi.filePreviewUrl("https://cdn.com/img.png")).toBe(
      "https://cdn.com/img.png",
    );
  });

  it("prepends /api/files/preview/ for relative paths", () => {
    const result = chatApi.filePreviewUrl("img.png");
    expect(result).toBe("/api/files/preview/img.png");
  });

  it("strips leading / from path", () => {
    const result = chatApi.filePreviewUrl("/img.png");
    expect(result).toBe("/api/files/preview/img.png");
  });

  it("appends ?token= param when token is present", () => {
    vi.mocked(getApiToken).mockReturnValue("my-token");
    const result = chatApi.filePreviewUrl("img.png");
    expect(result).toContain("?token=my-token");
  });

  it("URL-encodes token with special characters", () => {
    vi.mocked(getApiToken).mockReturnValue("tok en+1");
    const result = chatApi.filePreviewUrl("img.png");
    expect(result).toContain("token=tok%20en%2B1");
  });

  it("does not append query param when token is empty", () => {
    vi.mocked(getApiToken).mockReturnValue("");
    const result = chatApi.filePreviewUrl("img.png");
    expect(result).not.toContain("?token");
  });
});

describe("isConversationReadOnly", () => {
  it("derives viewer history as read-only from the backend access contract", () => {
    expect(
      isConversationReadOnly({ access_role: "viewer", read_only: true }),
    ).toBe(true);
    expect(
      isConversationReadOnly({ access_role: "owner", read_only: false }),
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// uploadFile — raw fetch, includes error handling logic
// ---------------------------------------------------------------------------
describe("chatApi.uploadFile", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns url and file_name on successful upload", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({ url: "/uploads/img.png", file_name: "img.png" }),
    } as unknown as Response);

    const file = new File(["content"], "img.png", { type: "image/png" });
    const result = await chatApi.uploadFile(file);
    expect(result).toEqual({ url: "/uploads/img.png", file_name: "img.png" });
  });

  it("sends POST to /api/console/upload", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ url: "", file_name: "" }),
    } as unknown as Response);

    await chatApi.uploadFile(new File([""], "f.txt"));
    expect(fetch).toHaveBeenCalledWith(
      "/api/console/upload",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("binds uploads to an existing conversation", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ url: "", file_name: "" }),
    } as unknown as Response);

    await chatApi.uploadFile(new File([""], "f.txt"), "chat-1");
    expect(fetch).toHaveBeenCalledWith(
      "/api/console/upload?conversation_id=chat-1",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("throws error with status code on upload failure", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      statusText: "Payload Too Large",
      text: () => Promise.resolve("File too large"),
    } as unknown as Response);

    await expect(chatApi.uploadFile(new File([""], "big.bin"))).rejects.toThrow(
      "Upload failed: 413 Payload Too Large - File too large",
    );
  });

  it("throws error without dash when upload fails with empty body", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: () => Promise.resolve(""),
    } as unknown as Response);

    const err = await chatApi
      .uploadFile(new File([""], "f.bin"))
      .catch((e) => e);
    expect(err.message).toBe("Upload failed: 500 Internal Server Error");
  });
});

describe("chatApi.filePreviewUrl", () => {
  afterEach(() => vi.clearAllMocks());

  it("keeps protected attachment endpoints instead of wrapping them as file paths", () => {
    expect(
      chatApi.filePreviewUrl(
        "/api/console/attachments/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      ),
    ).toBe(
      "/api/console/attachments/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
  });

  it("appends the session token to protected attachment endpoints", () => {
    vi.mocked(getApiToken).mockReturnValue("attachment token");

    expect(
      chatApi.filePreviewUrl(
        "/api/console/attachments/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      ),
    ).toBe(
      "/api/console/attachments/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa?token=attachment%20token",
    );
  });
});

// ---------------------------------------------------------------------------
// listChats — query string construction
// ---------------------------------------------------------------------------
describe("chatApi.listChats", () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue([]));
  afterEach(() => vi.clearAllMocks());

  it("calls /chats with no params", async () => {
    await chatApi.listChats();
    expect(request).toHaveBeenCalledWith("/chats");
  });

  it("builds query string with user_id", async () => {
    await chatApi.listChats({ user_id: "u1" });
    expect(request).toHaveBeenCalledWith("/chats?user_id=u1");
  });

  it("builds query string with channel", async () => {
    await chatApi.listChats({ channel: "console" });
    expect(request).toHaveBeenCalledWith("/chats?channel=console");
  });

  it("builds query string with conversation scope", async () => {
    await chatApi.listChats({ scope: "owned" });
    expect(request).toHaveBeenCalledWith("/chats?scope=owned");
  });

  it("both params appear in query when both are provided", async () => {
    await chatApi.listChats({ user_id: "u1", channel: "dingtalk" });
    expect(request).toHaveBeenCalledWith(expect.stringContaining("user_id=u1"));
    expect(request).toHaveBeenCalledWith(
      expect.stringContaining("channel=dingtalk"),
    );
  });
});

// ---------------------------------------------------------------------------
// Other methods — verify path and HTTP method
// ---------------------------------------------------------------------------
describe("chatApi CRUD", () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue(undefined));
  afterEach(() => vi.clearAllMocks());

  it("getChat encodes chatId and sends GET", async () => {
    await chatApi.getChat("chat/1");
    expect(request).toHaveBeenCalledWith(
      "/chats/chat%2F1",
      expect.objectContaining({ signal: undefined }),
    );
  });

  it("getChatStatus uses the lightweight endpoint and frozen agent scope", async () => {
    await chatApi.getChatStatus("chat/1", { agentId: "agent-a" });
    expect(request).toHaveBeenCalledWith(
      "/chats/chat%2F1/status",
      expect.objectContaining({
        signal: undefined,
        headers: { "X-Agent-Id": "agent-a" },
      }),
    );
  });

  it("updateChat sends PUT to the correct path", async () => {
    await chatApi.updateChat("chat-1", { name: "New Name" });
    expect(request).toHaveBeenCalledWith(
      "/chats/chat-1",
      expect.objectContaining({ method: "PUT" }),
    );
  });

  it("deleteChat sends DELETE to the correct path", async () => {
    await chatApi.deleteChat("chat-1");
    expect(request).toHaveBeenCalledWith(
      "/chats/chat-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("stopChat encodes chatId and appends query param", async () => {
    await chatApi.stopChat("chat/1");
    expect(request).toHaveBeenCalledWith(
      "/console/chat/stop?chat_id=chat%2F1",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("batchDeleteChats sends POST with list of ids", async () => {
    await chatApi.batchDeleteChats(["id1", "id2"]);
    expect(request).toHaveBeenCalledWith(
      "/chats/batch-delete",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(["id1", "id2"]),
      }),
    );
  });

  it("manages viewer sharing through owner-only member routes", async () => {
    await chatApi.listConversationMembers("chat/1");
    expect(request).toHaveBeenCalledWith("/chats/chat%2F1/members");

    await chatApi.addConversationViewer("chat/1", "user/1");
    expect(request).toHaveBeenCalledWith(
      "/chats/chat%2F1/members",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ user_id: "user/1" }),
      }),
    );

    await chatApi.removeConversationViewer("chat/1", "user/1");
    expect(request).toHaveBeenCalledWith(
      "/chats/chat%2F1/members/user%2F1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("chatApi.listAttachments", () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue([]));
  afterEach(() => vi.clearAllMocks());

  it("lists temporary attachments for the selected Agent", async () => {
    await chatApi.listAttachments({ lifecycle: "temporary" });

    expect(request).toHaveBeenCalledWith(
      "/console/attachments?lifecycle=temporary",
    );
  });
});
