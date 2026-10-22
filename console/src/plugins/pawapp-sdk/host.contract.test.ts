/**
 * host.contract.test.ts - contract coverage for plugins/pawapp-sdk/host.ts.
 *
 * host.ts had no test file before this one: a repo-wide grep for
 * "pawapp-sdk/host" across *.test.* returns zero hits. The module is only
 * reached indirectly through plugins/pawapp-sdk/index.ts, which leaves most
 * of its capability wrappers unexercised.
 *
 * What is asserted here is the observable contract of the PawApp host SDK:
 * the route each capability calls, the HTTP verb and body it sends, when a
 * host hook on window.QwenPaw is preferred over an HTTP fallback, and how a
 * failed chat stream is mapped onto PawChatStreamError.
 *
 * Two environment facts drive the setup (both measured in this repo, not
 * assumed):
 * 1. jsdom does not define window.QwenPaw, so every test installs at least an
 *    empty namespace. Production installs it in hostExternals.ts,
 *    moduleRegistry.ts and hostSdk/install.ts. The few tests that remove it
 *    again pin what happens when the host namespace is missing.
 * 2. A Response body can only be read once, so hostFetch is stubbed with
 *    mockImplementation (a fresh Response per call) rather than
 *    mockResolvedValue (one shared, already-consumed body).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hostFetch } from "../hostSdk/fetch";
import { setActivePawAppId } from "./context";
import {
  PawChatStreamError,
  chat,
  chatSessions,
  chatStream,
  createHostNamespace,
  getChatHistory,
  hostNamespace,
  notify,
  storage,
  toast,
} from "./host";
import type { PawChatStreamEvent } from "./types";

vi.mock("../hostSdk/fetch", () => ({
  hostFetch: vi.fn(),
}));

const mockedFetch = vi.mocked(hostFetch);

const APP_ID = "probe-app";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function textResponse(text: string, status = 200): Response {
  return new Response(text, { status });
}

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(`${frame}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

/** Resolve the next hostFetch call to a freshly built JSON response. */
function respondWith(body: unknown, status = 200): void {
  mockedFetch.mockImplementation(() =>
    Promise.resolve(jsonResponse(body, status)),
  );
}

function callPath(index = 0): string {
  return mockedFetch.mock.calls[index]?.[0] as string;
}

function callInit(index = 0): RequestInit {
  return mockedFetch.mock.calls[index]?.[1] as RequestInit;
}

function callBody(index = 0): Record<string, unknown> {
  const raw = callInit(index).body as string;
  return JSON.parse(raw) as Record<string, unknown>;
}

/** Await a promise that must reject and hand back the thrown value. */
async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("expected the promise to reject");
}

async function drainStream(
  stream: AsyncGenerator<PawChatStreamEvent>,
): Promise<{ events: PawChatStreamEvent[]; error: unknown }> {
  const events: PawChatStreamEvent[] = [];
  try {
    for await (const event of stream) {
      events.push(event);
    }
    return { events, error: undefined };
  } catch (error) {
    return { events, error };
  }
}

function installHost(hooks: Record<string, unknown> = {}): void {
  (window as unknown as Record<string, unknown>).QwenPaw = { host: hooks };
}

function dropHostNamespace(): void {
  delete (window as unknown as Record<string, unknown>).QwenPaw;
}

beforeEach(() => {
  (window as unknown as Record<string, unknown>).QwenPaw = {};
  setActivePawAppId(APP_ID);
  mockedFetch.mockReset();
  respondWith({});
});

afterEach(() => {
  mockedFetch.mockReset();
  setActivePawAppId(null);
  dropHostNamespace();
});

describe("pawapp host chat()", () => {
  it("posts to the app-scoped chat route with the agent id in the query", async () => {
    respondWith({ text: "hello" });

    await expect(chat("hi")).resolves.toBe("hello");

    expect(callPath()).toBe(`/${APP_ID}/chat?agent_id=default`);
    expect(callInit().method).toBe("POST");
    expect(callInit().headers).toEqual({
      "Content-Type": "application/json",
    });
    expect(callBody()).toEqual({ message: "hi" });
  });

  it("prefers an explicit agent id over the host-selected one", async () => {
    installHost({ getSelectedAgentId: () => "hook-agent" });
    respondWith({ text: "ok" });

    await chat("hi", { agentId: "option-agent" });

    expect(callPath()).toBe(`/${APP_ID}/chat?agent_id=option-agent`);
  });

  it("falls back to the agent selected in the host UI", async () => {
    installHost({ getSelectedAgentId: () => "hook-agent" });
    respondWith({ text: "ok" });

    await chat("hi");

    expect(callPath()).toBe(`/${APP_ID}/chat?agent_id=hook-agent`);
  });

  it("sends the current host session when the caller does not name one", async () => {
    installHost({ getCurrentSessionId: () => "host-session" });
    respondWith({ text: "ok" });

    await chat("hi");

    expect(callBody().session_id).toBe("host-session");
  });

  it("sends an explicit session id and skill", async () => {
    respondWith({ text: "ok" });

    await chat("hi", { sessionId: "ses-1", skill: "review" });

    expect(callBody()).toEqual({
      message: "hi",
      session_id: "ses-1",
      skill: "review",
    });
  });

  it("omits the session id when the caller passes null", async () => {
    installHost({ getCurrentSessionId: () => "host-session" });
    respondWith({ text: "ok" });

    await chat("hi", { sessionId: null });

    expect(callBody()).toEqual({ message: "hi" });
  });

  it("form-encodes an agent id containing a space in the query string", async () => {
    installHost({ getSelectedAgentId: () => "a g" });
    respondWith({ text: "ok" });

    await chat("hi");

    // URLSearchParams encodes a space as "+", not "%20".
    expect(callPath()).toBe(`/${APP_ID}/chat?agent_id=a+g`);
  });

  it.each([
    [{ text: "from-text", reply: "from-reply" }, "from-text"],
    [{ reply: "from-reply" }, "from-reply"],
    [{}, ""],
  ])(
    "returns text, then reply, then an empty string for %j",
    async (payload, expected) => {
      respondWith(payload);

      await expect(chat("hi")).resolves.toBe(expected);
    },
  );

  it("reports the status and status text when the response is not ok", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(
        new Response("", { status: 503, statusText: "Unavailable" }),
      ),
    );

    const error = await rejectionOf(chat("hi"));

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("Chat failed: 503 Unavailable");
  });

  it("needs the host namespace to be installed to resolve an agent", async () => {
    dropHostNamespace();
    respondWith({ text: "ok" });

    const error = await rejectionOf(chat("hi"));

    expect(error).toBeInstanceOf(TypeError);
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("builds a doubled-slash route when no PawApp id is active", async () => {
    setActivePawAppId(null);
    respondWith({ text: "ok" });

    await chat("hi");

    expect(callPath()).toBe("//chat?agent_id=default");
  });
});

describe("pawapp host chatStream()", () => {
  it("yields decoded envelope events in order", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(
        sseResponse([
          'data: {"object":"message","text":"first"}',
          'data: {"object":"content","delta":true}',
        ]),
      ),
    );

    const { events, error } = await drainStream(chatStream("hi"));

    expect(error).toBeUndefined();
    expect(events).toEqual([
      { object: "message", text: "first" },
      { object: "content", delta: true },
    ]);
  });

  it("posts to the app-scoped stream route asking for an event stream", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(sseResponse(['data: {"text":"ok"}'])),
    );

    await drainStream(chatStream("hi", { sessionId: "ses-2", skill: "sum" }));

    expect(callPath()).toBe(`/${APP_ID}/chat/stream?agent_id=default`);
    expect(callInit().method).toBe("POST");
    expect(callInit().headers).toMatchObject({ Accept: "text/event-stream" });
    expect(callBody()).toEqual({
      message: "hi",
      session_id: "ses-2",
      skill: "sum",
    });
  });

  it("rejects a frame that is not valid JSON and keeps the parse error", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(sseResponse(["data: not-json"])),
    );

    const { error } = await drainStream(chatStream("hi"));

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe(
      "PawApp chat stream returned invalid JSON",
    );
    expect((error as Error & { cause?: unknown }).cause).toBeInstanceOf(
      SyntaxError,
    );
  });

  it("maps a legacy error frame carrying a string detail", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(sseResponse(['data: {"type":"error","error":"boom"}'])),
    );

    const { error } = await drainStream(chatStream("hi"));

    expect(error).toBeInstanceOf(PawChatStreamError);
    const streamError = error as PawChatStreamError;
    expect(streamError.name).toBe("PawChatStreamError");
    expect(streamError.message).toBe("boom");
    expect(streamError.code).toBe("CHAT_STREAM_ERROR");
    expect(streamError.detail).toBe("boom");
    expect(streamError.event).toEqual({ type: "error", error: "boom" });
  });

  it("maps a failed response frame with a structured detail", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(
        sseResponse([
          'data: {"object":"response","status":"failed","error":{"message":"quota","code":"QUOTA"}}',
        ]),
      ),
    );

    const { error } = await drainStream(chatStream("hi"));
    const streamError = error as PawChatStreamError;

    expect(streamError.message).toBe("quota");
    expect(streamError.code).toBe("QUOTA");
  });

  it("treats the failed status case-insensitively", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(
        sseResponse([
          'data: {"object":"response","status":"FAILED","error":{"message":"upper"}}',
        ]),
      ),
    );

    const { error } = await drainStream(chatStream("hi"));

    expect((error as PawChatStreamError).message).toBe("upper");
  });

  it("passes a completed response frame through untouched", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(
        sseResponse([
          'data: {"object":"response","status":"completed","text":"fine"}',
        ]),
      ),
    );

    const { events, error } = await drainStream(chatStream("hi"));

    expect(error).toBeUndefined();
    expect(events).toEqual([
      { object: "response", status: "completed", text: "fine" },
    ]);
  });

  it.each([
    ['{"object":"response","status":"failed"}', "payload without error field"],
    ['{"type":"error","error":[1,2]}', "array detail"],
    ['{"type":"error","error":42}', "numeric detail"],
    ['{"type":"error","error":null}', "null detail"],
    ['{"type":"error","error":{"code":7}}', "detail with a non-string code"],
    [
      '{"type":"error","error":{"message":"","code":""}}',
      "blank message and code",
    ],
  ])("falls back to the generic chat failure for %s (%s)", async (frame) => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(sseResponse([`data: ${frame}`])),
    );

    const { error } = await drainStream(chatStream("hi"));
    const streamError = error as PawChatStreamError;

    expect(streamError).toBeInstanceOf(PawChatStreamError);
    expect(streamError.message).toBe("Chat failed");
    expect(streamError.code).toBe("CHAT_STREAM_ERROR");
  });

  it("uses the payload itself as the detail when no error field is present", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(
        sseResponse([
          'data: {"type":"error","message":"from-payload","code":"CP"}',
        ]),
      ),
    );

    const { error } = await drainStream(chatStream("hi"));
    const streamError = error as PawChatStreamError;

    expect(streamError.message).toBe("from-payload");
    expect(streamError.code).toBe("CP");
    expect(streamError.detail).toEqual({
      type: "error",
      message: "from-payload",
      code: "CP",
    });
  });
});

describe("pawapp host getChatHistory()", () => {
  it("reads the transcript of the effective session", async () => {
    respondWith({
      session_id: "server-session",
      messages: [{ id: "m1", type: "text", content: [] }],
    });

    const history = await getChatHistory({ sessionId: "asked-for" });

    expect(callPath()).toBe(
      `/${APP_ID}/chat/history?agent_id=default&session_id=asked-for`,
    );
    expect(callInit().method).toBe("GET");
    expect(history).toEqual({
      sessionId: "server-session",
      messages: [{ id: "m1", type: "text", content: [] }],
    });
  });

  it("keeps the requested session id when the server omits one", async () => {
    respondWith({ messages: [] });

    await expect(getChatHistory({ sessionId: "asked-for" })).resolves.toEqual({
      sessionId: "asked-for",
      messages: [],
    });
  });

  it("reports an empty session id when neither side names one", async () => {
    respondWith({});

    await expect(getChatHistory()).resolves.toEqual({
      sessionId: "",
      messages: [],
    });
  });

  it("coerces a messages field that is not a list to an empty list", async () => {
    respondWith({ session_id: "s", messages: "not-a-list" });

    await expect(getChatHistory()).resolves.toEqual({
      sessionId: "s",
      messages: [],
    });
  });
});

describe("pawapp host chatSessions", () => {
  it("normalizes listed rows and treats only true as archived or pinned", async () => {
    respondWith({
      sessions: [
        {
          id: "c1",
          session_id: "ss1",
          name: "",
          created_at: "",
          updated_at: "",
          archived: "yes",
          pinned: true,
        },
      ],
    });

    await expect(chatSessions.list()).resolves.toEqual([
      {
        id: "c1",
        sessionId: "ss1",
        name: "New analysis",
        createdAt: "",
        updatedAt: "",
        archived: false,
        pinned: true,
      },
    ]);
    expect(callPath()).toBe(`/${APP_ID}/chat/sessions?agent_id=default`);
    expect(callInit().method).toBe("GET");
  });

  it("lists an empty catalogue when the response has no sessions", async () => {
    respondWith({});

    await expect(chatSessions.list()).resolves.toEqual([]);
  });

  it("fills every normalized field with its empty default when a row is bare", async () => {
    respondWith({ sessions: [{}] });

    await expect(chatSessions.list()).resolves.toEqual([
      {
        id: "",
        sessionId: "",
        name: "New analysis",
        createdAt: "",
        updatedAt: "",
        archived: false,
        pinned: false,
      },
    ]);
  });

  it("scopes the listing to the agent id given by the caller", async () => {
    respondWith({ sessions: [] });

    await chatSessions.list({ agentId: "agent-x" });

    expect(callPath()).toBe(`/${APP_ID}/chat/sessions?agent_id=agent-x`);
  });

  it("creates a dialogue with the default name when none is given", async () => {
    respondWith({ id: "c2", session_id: "ss2" });

    await chatSessions.create();

    expect(callPath()).toBe(`/${APP_ID}/chat/sessions?agent_id=default`);
    expect(callInit().method).toBe("POST");
    expect(callBody()).toEqual({ name: "New analysis" });
  });

  it("sends a whitespace-only name as given instead of the default", async () => {
    respondWith({ id: "c7" });

    // A whitespace string is truthy, so the "||" default does not apply.
    await chatSessions.create({ name: "   " });

    expect(callBody()).toEqual({ name: "   " });
  });

  it("creates a dialogue with the requested name", async () => {
    respondWith({ id: "c3" });

    await chatSessions.create({ name: "Quarterly review" });

    expect(callBody()).toEqual({ name: "Quarterly review" });
  });

  it("renames a dialogue through PATCH on the percent-encoded id", async () => {
    respondWith({ id: "c4" });

    await chatSessions.rename("a b", "New name");

    expect(callPath()).toBe(`/${APP_ID}/chat/sessions/a%20b?agent_id=default`);
    expect(callInit().method).toBe("PATCH");
    expect(callBody()).toEqual({ name: "New name" });
  });

  it("archives a dialogue with an empty POST body", async () => {
    respondWith({ id: "c5", archived: true });

    await expect(chatSessions.archive("a b")).resolves.toMatchObject({
      archived: true,
    });
    expect(callPath()).toBe(
      `/${APP_ID}/chat/sessions/a%20b/archive?agent_id=default`,
    );
    expect(callInit().method).toBe("POST");
  });

  it("pins and unpins a dialogue with the flag in the body", async () => {
    respondWith({ id: "c6", pinned: true });

    await chatSessions.pin("c6", true);
    expect(callPath()).toBe(`/${APP_ID}/chat/sessions/c6/pin?agent_id=default`);
    expect(callBody()).toEqual({ pinned: true });

    await chatSessions.pin("c6", false);
    expect(callBody(1)).toEqual({ pinned: false });
  });

  it("deletes a dialogue and resolves without a value", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(new Response(null, { status: 204 })),
    );

    await expect(chatSessions.delete("a b")).resolves.toBeUndefined();
    expect(callPath()).toBe(`/${APP_ID}/chat/sessions/a%20b?agent_id=default`);
    expect(callInit().method).toBe("DELETE");
  });
});

describe("pawapp host storage", () => {
  it("reads back a stored value", async () => {
    respondWith({ value: 7 });

    await expect(storage.get("count", 0)).resolves.toBe(7);
    expect(callPath()).toBe(`/${APP_ID}/storage/count`);
    expect(callInit().method).toBe("GET");
  });

  it("percent-encodes a key with Chinese characters, a space and a slash", async () => {
    respondWith({ value: "v" });

    await storage.get("键 a/b");

    expect(callPath()).toBe(`/${APP_ID}/storage/%E9%94%AE%20a%2Fb`);
  });

  it("returns the default value when the read fails", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(textResponse("nope", 404)),
    );

    await expect(storage.get("count", "fallback")).resolves.toBe("fallback");
  });

  it("returns the default value when the payload carries no value", async () => {
    respondWith({});

    await expect(storage.get("count", "fallback")).resolves.toBe("fallback");
  });

  it("writes a value as a JSON PUT body", async () => {
    respondWith({});

    await storage.set("count", { nested: true });

    expect(callPath()).toBe(`/${APP_ID}/storage/count`);
    expect(callInit().method).toBe("PUT");
    expect(callInit().headers).toEqual({
      "Content-Type": "application/json",
    });
    expect(callBody()).toEqual({ value: { nested: true } });
  });

  it("deletes a key", async () => {
    respondWith({});

    await storage.delete("count");

    expect(callPath()).toBe(`/${APP_ID}/storage/count`);
    expect(callInit().method).toBe("DELETE");
  });

  it("lists stored keys", async () => {
    respondWith({ keys: ["a", "b"] });

    await expect(storage.keys()).resolves.toEqual(["a", "b"]);
    expect(callPath()).toBe(`/${APP_ID}/storage`);
    expect(callInit().method).toBe("GET");
  });

  it("lists no keys when the request fails", async () => {
    mockedFetch.mockImplementation(() =>
      Promise.resolve(textResponse("", 500)),
    );

    await expect(storage.keys()).resolves.toEqual([]);
  });

  it("lists no keys when the payload has no keys field", async () => {
    respondWith({});

    await expect(storage.keys()).resolves.toEqual([]);
  });
});

describe("pawapp host toast() and notify()", () => {
  it("shows a toast through the host hook without any HTTP call", async () => {
    const hostToast = vi.fn();
    installHost({ toast: hostToast });

    await toast("saved", "success");

    expect(hostToast).toHaveBeenCalledWith("saved", "success");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("falls back to the backend toast route when no host namespace exists", async () => {
    (window as unknown as Record<string, unknown>).QwenPaw = {};
    respondWith({});

    await toast("saved", "warning");

    expect(callPath()).toBe(`/${APP_ID}/toast`);
    expect(callInit().method).toBe("POST");
    expect(callBody()).toEqual({ message: "saved", kind: "warning" });
  });

  it("falls back when the host namespace has no toast function", async () => {
    installHost({});
    respondWith({});

    await toast("saved", "error");

    expect(callPath()).toBe(`/${APP_ID}/toast`);
    expect(callBody()).toEqual({ message: "saved", kind: "error" });
  });

  it("defaults the toast kind to info", async () => {
    respondWith({});

    await toast("saved");

    expect(callBody()).toEqual({ message: "saved", kind: "info" });
  });

  it("notifies with a title and a body", async () => {
    respondWith({});

    await notify("Done", "3 files updated");

    expect(callPath()).toBe(`/${APP_ID}/notify`);
    expect(callInit().method).toBe("POST");
    expect(callBody()).toEqual({ title: "Done", body: "3 files updated" });
  });

  it("notifies with a title only", async () => {
    respondWith({});

    await notify("Done");

    expect(callBody()).toEqual({ title: "Done" });
  });
});

describe("pawapp createHostNamespace()", () => {
  const scopedId = "my-app";

  function scoped() {
    return createHostNamespace(() => scopedId);
  }

  it("exposes the documented host capability set", () => {
    expect(Object.keys(scoped()).sort()).toEqual([
      "chat",
      "chatSessions",
      "chatStream",
      "getChatHistory",
      "getCurrentSessionId",
      "getSelectedAgentId",
      "notify",
      "storage",
      "toast",
    ]);
  });

  it("routes chat through the permanently scoped app id", async () => {
    respondWith({ text: "scoped" });

    await expect(scoped().chat("hi")).resolves.toBe("scoped");

    expect(callPath()).toBe(`/${scopedId}/chat?agent_id=default`);
  });

  it.each([
    [{ text: "t", reply: "r" }, "t"],
    [{ reply: "r" }, "r"],
    [{}, ""],
  ])(
    "prefers text over reply over an empty string for a scoped chat with %j",
    async (payload, expected) => {
      respondWith(payload);

      await expect(scoped().chat("hi")).resolves.toBe(expected);
    },
  );

  it("rejects an invalid app id when a capability is used, not when it is built", async () => {
    const invalid = createHostNamespace(() => "BAD_APP");
    respondWith({ text: "never" });

    const error = await rejectionOf(invalid.chat("hi"));

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("Invalid PawApp id: BAD_APP");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("reads scoped storage and falls back to the default on failure", async () => {
    respondWith({ value: "V" });
    await expect(scoped().storage.get("k", "D")).resolves.toBe("V");
    expect(callPath()).toBe(`/${scopedId}/storage/k`);

    mockedFetch.mockImplementation(() =>
      Promise.resolve(textResponse("", 500)),
    );
    await expect(scoped().storage.get("k", "D2")).resolves.toBe("D2");

    respondWith({});
    await expect(scoped().storage.get("k", "D3")).resolves.toBe("D3");
  });

  it("writes, deletes and lists scoped storage", async () => {
    respondWith({});

    await scoped().storage.set("k", { a: 1 });
    expect(callPath()).toBe(`/${scopedId}/storage/k`);
    expect(callInit().method).toBe("PUT");
    expect(callBody()).toEqual({ value: { a: 1 } });

    await scoped().storage.delete("k");
    expect(callPath(1)).toBe(`/${scopedId}/storage/k`);
    expect(callInit(1).method).toBe("DELETE");

    respondWith({ keys: ["k1"] });
    await expect(scoped().storage.keys()).resolves.toEqual(["k1"]);
    expect(callPath(2)).toBe(`/${scopedId}/storage`);

    respondWith({});
    await expect(scoped().storage.keys()).resolves.toEqual([]);
  });

  it("reads the agent and session from the host hooks with fallbacks", () => {
    (window as unknown as Record<string, unknown>).QwenPaw = {};
    expect(scoped().getSelectedAgentId()).toBe("default");
    expect(scoped().getCurrentSessionId()).toBeNull();

    installHost({
      getSelectedAgentId: () => "agent-9",
      getCurrentSessionId: () => "session-9",
    });
    expect(scoped().getSelectedAgentId()).toBe("agent-9");
    expect(scoped().getCurrentSessionId()).toBe("session-9");
  });

  it("prefers the host toast hook and otherwise posts to the scoped route", async () => {
    const hostToast = vi.fn();
    installHost({ toast: hostToast });

    await scoped().toast("m", "warning");
    expect(hostToast).toHaveBeenCalledWith("m", "warning");
    expect(mockedFetch).not.toHaveBeenCalled();

    (window as unknown as Record<string, unknown>).QwenPaw = {};
    respondWith({});
    await scoped().toast("m2");
    expect(callPath()).toBe(`/${scopedId}/toast`);
    expect(callBody()).toEqual({ message: "m2", kind: "info" });
  });

  it("posts a scoped notification", async () => {
    respondWith({});

    await scoped().notify("t", "b");

    expect(callPath()).toBe(`/${scopedId}/notify`);
    expect(callBody()).toEqual({ title: "t", body: "b" });
  });

  it("delegates history, sessions and streaming to the scoped app id", async () => {
    respondWith({ session_id: "srv", messages: [] });
    await expect(scoped().getChatHistory()).resolves.toEqual({
      sessionId: "srv",
      messages: [],
    });
    expect(callPath()).toBe(`/${scopedId}/chat/history?agent_id=default`);

    respondWith({ sessions: [{ id: "c1", session_id: "ss" }] });
    await expect(scoped().chatSessions.list()).resolves.toEqual([
      {
        id: "c1",
        sessionId: "ss",
        name: "New analysis",
        createdAt: "",
        updatedAt: "",
        archived: false,
        pinned: false,
      },
    ]);
    expect(callPath(1)).toBe(`/${scopedId}/chat/sessions?agent_id=default`);

    mockedFetch.mockImplementation(() =>
      Promise.resolve(sseResponse(['data: {"text":"streamed"}'])),
    );
    const { events } = await drainStream(scoped().chatStream("hi"));
    expect(events).toEqual([{ text: "streamed" }]);
    expect(callPath(2)).toBe(`/${scopedId}/chat/stream?agent_id=default`);
  });

  it("omits the session id for a scoped chat started with null", async () => {
    installHost({ getCurrentSessionId: () => "host-session" });
    respondWith({ text: "ok" });

    await scoped().chat("hi", { sessionId: null });

    expect(callBody()).toEqual({ message: "hi" });
  });
});

describe("pawapp hostNamespace export", () => {
  it("exposes the module-level capabilities themselves", () => {
    expect(hostNamespace.chat).toBe(chat);
    expect(hostNamespace.chatStream).toBe(chatStream);
    expect(hostNamespace.getChatHistory).toBe(getChatHistory);
    expect(hostNamespace.chatSessions).toBe(chatSessions);
    expect(hostNamespace.storage).toBe(storage);
    expect(hostNamespace.toast).toBe(toast);
    expect(hostNamespace.notify).toBe(notify);
  });

  it("falls back to a default agent and a null session", () => {
    (window as unknown as Record<string, unknown>).QwenPaw = {};

    expect(hostNamespace.getSelectedAgentId()).toBe("default");
    expect(hostNamespace.getCurrentSessionId()).toBeNull();
  });

  it("reads both identifiers from the host hooks when present", () => {
    installHost({
      getSelectedAgentId: () => "agent-1",
      getCurrentSessionId: () => "session-1",
    });

    expect(hostNamespace.getSelectedAgentId()).toBe("agent-1");
    expect(hostNamespace.getCurrentSessionId()).toBe("session-1");
  });

  it("needs the host namespace object to read either identifier", () => {
    dropHostNamespace();

    expect(() => hostNamespace.getSelectedAgentId()).toThrow(TypeError);
    expect(() => hostNamespace.getCurrentSessionId()).toThrow(TypeError);
  });
});
