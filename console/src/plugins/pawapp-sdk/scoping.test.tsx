import React from "react";
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeRegistry } from "../registry/store";
import { hostFetch } from "../hostSdk/fetch";
import { apiNamespace, forApp } from "./index";
import { PawApiError } from "./api";
import { PawChatStreamError } from "./host";
import { createUiNamespace } from "./ui";
import { setActivePawAppId } from "./context";

vi.mock("../hostSdk/fetch", () => ({
  hostFetch: vi.fn(),
}));

const mockedFetch = vi.mocked(hostFetch);

beforeEach(() => {
  Object.defineProperty(window, "QwenPaw", {
    configurable: true,
    writable: true,
    value: {
      host: {
        getSelectedAgentId: () => "default",
        getCurrentSessionId: () => null,
      },
    },
  });
});

afterEach(() => {
  setActivePawAppId(null);
  mockedFetch.mockReset();
  routeRegistry.__resetForTests();
});

describe("app-scoped PawApp SDK", () => {
  it("prefixes every request with the permanent app id", async () => {
    mockedFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "content-type": "application/json" },
      }),
    );
    const paw = forApp("reviewer");

    await paw.api.patch(
      "/records/1",
      { title: "Ready" },
      {
        query: { revision: 4 },
      },
    );

    expect(mockedFetch).toHaveBeenCalledWith(
      "/reviewer/records/1?revision=4",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("keeps embedded query strings compatible on the legacy dynamic API", async () => {
    setActivePawAppId("legacy_app");
    mockedFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await apiNamespace.get("/records?revision=4", {
      query: { view: "open" },
    });

    expect(mockedFetch).toHaveBeenCalledWith(
      "/legacy_app/records?revision=4&view=open",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("routes chat through the selected host agent and session", async () => {
    window.QwenPaw.host.getSelectedAgentId = () => "analyst";
    window.QwenPaw.host.getCurrentSessionId = () => "session-7";
    mockedFetch.mockResolvedValue(
      new Response(JSON.stringify({ text: "done" }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(forApp("analysis-app").chat("compare revenue")).resolves.toBe(
      "done",
    );

    expect(mockedFetch).toHaveBeenCalledWith(
      "/analysis-app/chat?agent_id=analyst",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          message: "compare revenue",
          session_id: "session-7",
        }),
      }),
    );
  });

  it("allows an app to route chat through its managed agent", async () => {
    mockedFetch.mockResolvedValue(
      new Response(JSON.stringify({ text: "managed" }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await forApp("datapaw").chat("compare revenue", {
      agentId: "datapaw",
      sessionId: "datapaw-session",
      skill: "bi-metric-analysis",
    });

    expect(mockedFetch).toHaveBeenCalledWith(
      "/datapaw/chat?agent_id=datapaw",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          message: "compare revenue",
          session_id: "datapaw-session",
          skill: "bi-metric-analysis",
        }),
      }),
    );
  });

  it("streams decoded chat envelopes through the managed agent", async () => {
    const encoder = new TextEncoder();
    mockedFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                'data: {"object":"content","type":"text","delta":true,"text":"Hel"}\n\n' +
                  'data: {"object":"content","type":"text","delta":true,"text":"lo"}\n\n',
              ),
            );
            controller.close();
          },
        }),
        { headers: { "content-type": "text/event-stream" } },
      ),
    );

    const events = [];
    for await (const event of forApp("datapaw").chatStream("compare revenue", {
      agentId: "datapaw",
      sessionId: "datapaw-session",
    })) {
      events.push(event);
    }

    expect(mockedFetch).toHaveBeenCalledWith(
      "/datapaw/chat/stream?agent_id=datapaw",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Accept: "text/event-stream" }),
        body: JSON.stringify({
          message: "compare revenue",
          session_id: "datapaw-session",
        }),
      }),
    );
    expect(events.map((event) => event.text)).toEqual(["Hel", "lo"]);
  });

  it("rejects failed response envelopes with their structured error code", async () => {
    const encoder = new TextEncoder();
    mockedFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                'data: {"object":"response","type":"response","status":"failed","error":{"code":"UNAUTHORIZED_MODEL_ACCESS","message":"Unauthorized access to model \'qwen3-max\'"}}\n\n',
              ),
            );
            controller.close();
          },
        }),
        { headers: { "content-type": "text/event-stream" } },
      ),
    );

    const next = forApp("datapaw")
      .chatStream("compare revenue", { agentId: "datapaw" })
      .next();

    await expect(next).rejects.toBeInstanceOf(PawChatStreamError);
    await expect(next).rejects.toMatchObject({
      name: "PawChatStreamError",
      code: "UNAUTHORIZED_MODEL_ACCESS",
      message: "Unauthorized access to model 'qwen3-max'",
      detail: {
        code: "UNAUTHORIZED_MODEL_ACCESS",
        message: "Unauthorized access to model 'qwen3-max'",
      },
    });
  });

  it("keeps legacy chat error events compatible", async () => {
    const encoder = new TextEncoder();
    mockedFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                'data: {"type":"error","error":{"code":"MODEL_NOT_CONFIGURED","message":"Configure a model"}}\n\n',
              ),
            );
            controller.close();
          },
        }),
        { headers: { "content-type": "text/event-stream" } },
      ),
    );

    const next = forApp("datapaw").chatStream("compare revenue").next();
    await expect(next).rejects.toMatchObject({
      name: "PawChatStreamError",
      code: "MODEL_NOT_CONFIGURED",
      message: "Configure a model",
    });
  });

  it("restores history from the same managed agent and session", async () => {
    mockedFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "pawapp:datapaw",
          messages: [
            {
              id: "message-1",
              type: "message",
              role: "user",
              content: [{ type: "text", text: "compare revenue" }],
            },
          ],
        }),
        { headers: { "content-type": "application/json" } },
      ),
    );

    await expect(
      forApp("datapaw").getChatHistory({
        agentId: "datapaw",
        sessionId: "pawapp:datapaw",
      }),
    ).resolves.toEqual({
      sessionId: "pawapp:datapaw",
      messages: [
        {
          id: "message-1",
          type: "message",
          role: "user",
          content: [{ type: "text", text: "compare revenue" }],
        },
      ],
    });

    expect(mockedFetch).toHaveBeenCalledWith(
      "/datapaw/chat/history?agent_id=datapaw&session_id=pawapp%3Adatapaw",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("manages app-scoped dialogue sessions through the host catalog", async () => {
    const session = {
      id: "chat-1",
      session_id: "pawapp:datapaw:dialogue:1",
      name: "March GAAP",
      created_at: "2026-08-11T00:00:00Z",
      updated_at: "2026-08-11T00:01:00Z",
      archived: false,
    };
    mockedFetch
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ sessions: [session] }), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(session), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...session, name: "Renamed" }), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...session, pinned: true }), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          headers: { "content-type": "application/json" },
        }),
      );

    const sessions = forApp("datapaw").chatSessions;
    await expect(sessions.list({ agentId: "datapaw" })).resolves.toEqual([
      {
        id: "chat-1",
        sessionId: "pawapp:datapaw:dialogue:1",
        name: "March GAAP",
        createdAt: "2026-08-11T00:00:00Z",
        updatedAt: "2026-08-11T00:01:00Z",
        archived: false,
        pinned: false,
      },
    ]);
    await sessions.create({ agentId: "datapaw", name: "March GAAP" });
    await sessions.rename("chat-1", "Renamed", { agentId: "datapaw" });
    await expect(
      sessions.pin("chat-1", true, { agentId: "datapaw" }),
    ).resolves.toMatchObject({ pinned: true });
    await sessions.delete("chat-1", { agentId: "datapaw" });

    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "/datapaw/chat/sessions?agent_id=datapaw",
      expect.objectContaining({ method: "GET" }),
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "/datapaw/chat/sessions?agent_id=datapaw",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "March GAAP" }),
      }),
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      3,
      "/datapaw/chat/sessions/chat-1?agent_id=datapaw",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ name: "Renamed" }),
      }),
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      4,
      "/datapaw/chat/sessions/chat-1/pin?agent_id=datapaw",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ pinned: true }),
      }),
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      5,
      "/datapaw/chat/sessions/chat-1?agent_id=datapaw",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("reads authenticated GET SSE with event names and multiline data", async () => {
    const encoder = new TextEncoder();
    mockedFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                ": ready\r\nevent: task_status\r\nid: 7\r\n" +
                  'data: {"step":1,\r\ndata: "state":"running"}\r\n\r\n',
              ),
            );
            controller.close();
          },
        }),
        { headers: { "content-type": "text/event-stream" } },
      ),
    );

    const events = [];
    for await (const event of forApp("datapaw").api.events(
      "/tasks/session-1/events",
      { method: "GET", query: { user_id: "default" } },
    )) {
      events.push(event);
    }

    expect(mockedFetch).toHaveBeenCalledWith(
      "/datapaw/tasks/session-1/events?user_id=default",
      expect.objectContaining({
        method: "GET",
        headers: { Accept: "text/event-stream" },
        body: undefined,
      }),
    );
    expect(events).toEqual([
      {
        event: "task_status",
        id: "7",
        data: '{"step":1,\n"state":"running"}',
      },
    ]);
  });

  it("rejects request bodies on GET SSE subscriptions", async () => {
    const iterator = forApp("datapaw").api.events("/events", {
      method: "GET",
      body: { invalid: true },
    });
    await expect(iterator.next()).rejects.toThrow("cannot include a body");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("scopes dependency checks and lifecycle actions to the app", async () => {
    mockedFetch.mockImplementation(
      async () =>
        new Response(JSON.stringify({ id: "graph-store", health: "healthy" }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const paw = forApp("analysis-app");

    await paw.dependencies.check("graph-store");
    await paw.dependencies.action("local-worker", "start", {
      idempotencyKey: "start-once",
    });

    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "/analysis-app/dependencies/graph-store/actions/check",
      expect.objectContaining({ method: "POST" }),
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "/analysis-app/dependencies/local-worker/actions/start",
      expect.objectContaining({
        method: "POST",
        headers: { "Idempotency-Key": "start-once" },
      }),
    );
  });

  it("preserves structured host errors for app-specific recovery", async () => {
    mockedFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "MODEL_NOT_CONFIGURED",
            message: "No active model configured; pick one in the UI",
            action: { label: "Configure a model", path: "/models" },
          },
        }),
        {
          status: 503,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const request = forApp("analysis-app").chat("compare revenue");
    await expect(request).rejects.toBeInstanceOf(PawApiError);
    await expect(request).rejects.toMatchObject({
      status: 503,
      code: "MODEL_NOT_CONFIGURED",
      detail: expect.objectContaining({
        action: { label: "Configure a model", path: "/models" },
      }),
    });
  });

  it("rejects page routes outside the app and disposes mounted UIs", () => {
    const ui = createUiNamespace("analysis-app");
    expect(() =>
      ui.registerPage({
        label: "Bad",
        component: () => null,
        path: "/apps/other",
      }),
    ).toThrow("must stay under /apps/analysis-app");

    const cleanup = vi.fn();
    const mount = vi.fn(() => cleanup);
    const registration = ui.registerPage({ label: "Analysis", mount });
    const route = routeRegistry.snapshot()[0];
    const rendered = render(React.createElement(route.Component));

    expect(mount).toHaveBeenCalledOnce();
    rendered.unmount();
    expect(cleanup).toHaveBeenCalledOnce();
    registration.dispose();
    expect(routeRegistry.snapshot()).toEqual([]);
  });

  it.each(["/../other/secret", "/%2e%2e/other", "/%252e%252e/other"])(
    "rejects backend scope traversal in %s",
    async (path) => {
      await expect(forApp("analysis-app").api.get(path)).rejects.toThrow(
        "dot segments",
      );
      expect(mockedFetch).not.toHaveBeenCalled();
    },
  );

  it("applies the same scope validation to long-running tasks", async () => {
    const task = forApp("analysis-app").api.task("/%2e%2e/other", {});

    await expect(task.result).rejects.toThrow("dot segments");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("rejects encoded page traversal", () => {
    const ui = createUiNamespace("analysis-app");
    expect(() =>
      ui.registerPage({
        label: "Bad",
        component: () => null,
        path: "/apps/analysis-app/%2e%2e/other",
      }),
    ).toThrow("dot segments");
  });

  it("supports native request bodies without forcing a JSON content type", async () => {
    mockedFetch.mockResolvedValue(new Response(null, { status: 204 }));
    const body = new FormData();
    body.set("file", new Blob(["content"]), "example.txt");

    await forApp("analysis-app").api.request("/imports", {
      method: "POST",
      rawBody: body,
    });

    expect(mockedFetch).toHaveBeenCalledWith(
      "/analysis-app/imports",
      expect.objectContaining({ method: "POST", body, headers: {} }),
    );
  });

  it("rejects ambiguous JSON and raw request bodies", async () => {
    await expect(
      forApp("analysis-app").api.request("/imports", {
        method: "POST",
        body: { mode: "replace" },
        rawBody: "content",
      }),
    ).rejects.toThrow("both body and rawBody");
    expect(mockedFetch).not.toHaveBeenCalled();
  });
});
