import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDurableNamespaces } from "./durable";
import { assertContract } from "./contracts";
import type { PawHostNamespace } from "./types";
import { hostFetch } from "../hostSdk/fetch";

vi.mock("../hostSdk/fetch", () => ({ hostFetch: vi.fn() }));
const fetchMock = vi.mocked(hostFetch);
const task = {
  schema_version: 1,
  task_id: "task-one",
  submission_id: "submission-one",
  scope: {
    principal_id: "alice",
    workspace_id: "sales",
    app_id: "neutral-app",
  },
  action_id: "inspect",
  descriptor_digest: "digest",
  origin: {
    engagement: "direct",
    origin_ref: "chat",
    app_session_ref: "app-chat",
  },
  status: "succeeded",
  created_at: 1,
  updated_at: 2,
  result_data: { value: 42 },
};
let selected = "sales";
const sdk = createDurableNamespaces(() => "neutral-app", {
  getSelectedAgentId: () => selected,
} as PawHostNamespace);
const respond = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200 });
beforeEach(() => {
  selected = "sales";
  fetchMock.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("durable App SDK", () => {
  it("pins scope during dispatch and preserves caller intent IDs on retry", async () => {
    fetchMock.mockImplementation(async () => {
      selected = "marketing";
      return respond({ state: "accepted", task });
    });
    const first = await sdk.tasks.dispatch(
      "inspect",
      {},
      { requestId: "intent-one" },
    );
    expect(first.state).toBe("accepted");
    await sdk.tasks.dispatch(
      "inspect",
      {},
      { workspaceId: "sales", requestId: "intent-one" },
    );
    for (const [url, init] of fetchMock.mock.calls) {
      expect(url).toBe(
        "/pawapps/neutral-app/workspaces/sales/actions/inspect/direct-tasks",
      );
      expect(init?.headers).toMatchObject({ "X-Agent-Id": "sales" });
      expect(JSON.parse(String(init?.body)).request_id).toBe("intent-one");
    }
  });

  it("rejects malformed and cross-scope task responses", async () => {
    fetchMock.mockResolvedValueOnce(
      respond({ task: { ...task, scope: { ...task.scope, app_id: "other" } } }),
    );
    await expect(sdk.tasks.get("task-one")).rejects.toThrow(
      "task_scope_mismatch",
    );
    fetchMock.mockResolvedValueOnce(
      respond({ task: { ...task, status: "invented" } }),
    );
    await expect(sdk.tasks.get("task-one")).rejects.toThrow(
      "invalid_TaskHandle",
    );
    fetchMock.mockResolvedValueOnce(
      respond({ task: { ...task, task_id: "other" } }),
    );
    await expect(sdk.tasks.get("task-one")).rejects.toThrow(
      "task_identity_mismatch",
    );
  });

  it("stops waiting on abort without moving to a new workspace", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    fetchMock.mockImplementation(async () => {
      selected = "marketing";
      return respond({ task: { ...task, status: "running" } });
    });
    const waiting = sdk.tasks.wait("task-one", { signal: controller.signal });
    const rejected = expect(waiting).rejects.toThrow("stop");
    await vi.advanceTimersByTimeAsync(1001);
    controller.abort(new Error("stop"));
    await rejected;
    expect(
      fetchMock.mock.calls.every(([url]) => url.includes("/workspaces/sales/")),
    ).toBe(true);
  });

  it("validates bounded models and permits older handles without new optional fields", () => {
    expect(assertContract("TaskHandle", task).task_id).toBe("task-one");
    expect(() =>
      assertContract("TaskHandle", { ...task, task_id: "" }),
    ).toThrow();
    expect(() =>
      assertContract("TaskHandle", { ...task, unexpected: true }),
    ).toThrow();
    expect(() =>
      assertContract("TaskHandle", { ...task, event_sequence: -1 }),
    ).toThrow();
    expect(() =>
      assertContract("TaskHandle", { ...task, result_data: [] }),
    ).toThrow();
  });

  it("fails closed on unsupported setup navigation", async () => {
    fetchMock.mockResolvedValueOnce(
      respond({ request: { scope: task.scope } }),
    );
    await expect(sdk.setup.get("setup-one")).rejects.toThrow(
      "invalid_SetupRequest",
    );
  });
});
