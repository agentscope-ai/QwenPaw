import { beforeEach, expect, it, vi } from "vitest";
import { request } from "@/api/request";
import {
  loadSessionModel,
  resetSessionModel,
  saveSessionModel,
  migratePendingModel,
  readPendingModel,
  withPendingModel,
} from "./sessionModel";
vi.mock("@/api/request", () => ({ request: vi.fn() }));
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});
it("persists existing-session selection without changing agent defaults", async () => {
  vi.mocked(request).mockResolvedValue({
    provider_id: "p",
    model: "m",
    effective_max_input_length: 32000,
  });
  const scope = { sessionId: "s", chatId: "chat-a" };
  await saveSessionModel("agent", scope, { provider_id: "p", model: "m" });
  expect(request).toHaveBeenCalledWith(
    "/chats/chat-a/model",
    expect.objectContaining({
      method: "PUT",
      headers: { "X-Agent-Id": "agent" },
    }),
  );
  expect((await loadSessionModel("agent", scope)).active_llm?.model).toBe("m");
  expect(request).toHaveBeenLastCalledWith(
    "/chats/chat-a/thinking",
    expect.anything(),
  );
});
it("carries new-session model selection through first-send allocation", async () => {
  vi.mocked(request).mockResolvedValue({ provider_id: "p", model: "m" });
  await saveSessionModel(
    "a",
    { sessionId: "new" },
    { provider_id: "p", model: "m" },
  );
  expect(readPendingModel("b", "new")).toBeNull();
  migratePendingModel("a", "new", "created");
  expect(readPendingModel("a", "new")).toBeNull();
  expect(
    withPendingModel({ request_context: { other: true } }, "a", "created"),
  ).toEqual({
    request_context: {
      other: true,
      session_model: { provider_id: "p", model: "m" },
    },
  });
});

it("keeps the submitted model visible until the allocated chat acknowledges it", async () => {
  const selected = { provider_id: "dashscope", model: "deepseek-v4.1-flash" };
  const inherited = { provider_id: "dashscope", model: "glm-5.3" };
  vi.mocked(request).mockResolvedValueOnce(selected);
  await saveSessionModel("agent", { sessionId: "new" }, selected);
  migratePendingModel("agent", "new", "created");
  const scope = { sessionId: "created", chatId: "created" };
  vi.mocked(request)
    .mockResolvedValueOnce(inherited)
    .mockResolvedValueOnce(selected);
  expect((await loadSessionModel("agent", scope)).active_llm).toEqual(selected);
  expect(readPendingModel("agent", "created")).toEqual(selected);
  expect(withPendingModel({}, "agent", "created")).toEqual({
    request_context: { session_model: selected },
  });
  vi.mocked(request).mockResolvedValueOnce({
    ...selected,
    model_source: "session",
  });
  expect((await loadSessionModel("agent", scope)).active_llm).toEqual(selected);
  expect(readPendingModel("agent", "created")).toBeNull();
  expect(withPendingModel({}, "agent", "created")).toEqual({});
});

it.each(["replace", "reset"])(
  "retires the migrated choice after a successful %s",
  async (operation) => {
    const selected = { provider_id: "dashscope", model: "deepseek-v4.1-flash" };
    vi.mocked(request).mockResolvedValue(selected);
    await saveSessionModel("agent", { sessionId: "new" }, selected);
    migratePendingModel("agent", "new", "created");
    const scope = { sessionId: "created", chatId: "created" };
    if (operation === "reset") await resetSessionModel("agent", scope);
    else
      await saveSessionModel("agent", scope, {
        provider_id: "dashscope",
        model: "glm-5.3",
      });
    expect(withPendingModel({}, "agent", "created")).toEqual({});
  },
);
