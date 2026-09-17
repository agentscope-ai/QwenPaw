import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../request", () => ({ request: vi.fn() }));
import { request } from "../request";
import { modelCatalogApi, createSelectionScope } from "./modelCatalog";

beforeEach(() => vi.mocked(request).mockReset());
it("writes only the current conversation model without Agent scope", async () => {
  vi.mocked(request).mockResolvedValue({
    active_llm: { provider_id: "p", model: "m" },
  });
  await modelCatalogApi.select("chat-a", { provider_id: "p", model: "m" });
  expect(request).toHaveBeenCalledWith("/chats/chat-a/model", {
    method: "PUT",
    body: '{"provider_id":"p","model":"m"}',
  });
});
it("invalidates responses and draft models when identity or conversation changes", () => {
  const scope = createSelectionScope();
  const old = scope.enter("alice", "agent", "draft");
  scope.setDraft(old, { provider_id: "p", model: "m" });
  expect(scope.draft(old)?.model).toBe("m");
  const next = scope.enter("bob", "agent", "draft");
  expect(scope.current(old)).toBe(false);
  expect(scope.draft(next)).toBeUndefined();
  scope.enter("bob", "agent", "chat-b");
  expect(scope.current(next)).toBe(false);
});
