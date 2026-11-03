import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreatorMessage, CreatorSessionView } from "@/contracts/creator";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorEditBufferStore } from "@/store/creatorEditBufferStore";

const store = () => useCreatorSessionStore.getState();

/** Stub fetch with a manually resolvable Response. */
function stubPending() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(() => promise),
  );
  return { resolve };
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 400 ? "Failed" : "OK",
    json: async () => body,
  } as Response;
}

const seqs = { lastMessageSeq: 0, lastConsumedMessageSeq: 0, lastEventSeq: 0 };
const session = (projectId: string): CreatorSessionView => ({
  id: `session-${projectId}`,
  projectId,
  status: "IDLE",
  ...seqs,
});

const message = (projectId: string, messageSeq = 1): CreatorMessage => ({
  messageId: `message-${projectId}-${messageSeq}`,
  messageSeq,
  role: "user",
  content: [{ type: "text", text: projectId }],
  metadata: {},
  createdAt: "2026-07-23T00:00:00Z",
});

function bind(projectId: string, conversationId: string) {
  useCreatorSessionStore.setState({
    projectId,
    session: session(projectId),
    activeConversationId: conversationId,
    messages: [],
    queuedUi: [],
  });
}

describe("Creator Session async project/conversation isolation", () => {
  beforeEach(() => {
    store().reset();
    useCreatorEditBufferStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it("drops an old send acceptance after switching projects", async () => {
    const pending = stubPending();
    bind("p1", "conversation-p1");

    const send = store().sendMessage({ message: "old project message" });
    expect(store().queuedUi).toHaveLength(1);

    store().reset();
    bind("p2", "conversation-p2");
    useCreatorSessionStore.setState({ messages: [message("p2")] });
    pending.resolve(
      response(
        {
          messageSeq: 1,
          eventSeq: 1,
          classification: "mutation_instruction",
          appendState: "queued_until_message_boundary",
          creatorSessionId: "session-p1",
          conversationId: "conversation-p1",
        },
        202,
      ),
    );
    await send;

    expect(store()).toMatchObject({
      projectId: "p2",
      activeConversationId: "conversation-p2",
      queuedUi: [],
      messages: [message("p2")],
    });
  });

  it("drops an old send failure after switching conversations", async () => {
    const pending = stubPending();
    bind("p1", "conversation-old");

    const send = store().sendMessage({ message: "old conversation message" });
    useCreatorSessionStore.setState({
      activeConversationId: "conversation-new",
      queuedUi: [],
    });
    pending.resolve(
      response(
        {
          code: "MODEL_REQUEST_FAILED",
          message: "provider leaked internal details",
        },
        500,
      ),
    );

    await expect(send).rejects.toThrow("provider leaked internal details");
    expect(store()).toMatchObject({
      activeConversationId: "conversation-new",
      queuedUi: [],
    });
  });

  it("retries a failed send verbatim under its original clientMessageId", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("network down"))),
    );
    bind("p1", "conversation-p1");
    // Attachments and structured selections must survive the retry — a
    // plain-text reconstruction would send selections=[] and drop refs
    // (CR 2026-09-11).
    const edits = useCreatorEditBufferStore.getState();
    edits.recordPatch({
      projectId: "p1",
      projectBefore: null,
      generation: 1,
      operations: [
        { op: "replace", path: "/settings/name", before: "old", value: "new" },
      ],
    });
    const userEdits = edits.consumeContext("p1")!;
    const request = {
      message: "指令 A",
      assetVersionRefs: ["asset-version:av1"],
      context: {
        selections: [{ field: "prompt", path: "/a", text: "选区" }],
        userEdits,
      },
    };

    await expect(store().sendMessage(request)).rejects.toThrow("network down");
    const failed = store().queuedUi[0];
    expect(failed).toMatchObject({ state: "failed", request });
    expect(edits.consumeContext("p1")).toEqual(userEdits);
    // A newer edit belongs to the next message, even when the old card retries.
    const later = {
      ...userEdits.edits[0],
      at: "2099-01-01T00:00:00.000Z",
      after: "later",
    };
    useCreatorEditBufferStore.setState({
      entries: [...userEdits.edits, later],
    });

    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: unknown, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body)));
        return Promise.resolve(
          response({
            messageSeq: 1,
            eventSeq: 1,
            classification: "mutation_instruction",
            appendState: "queued_until_message_boundary",
            creatorSessionId: "session-p1",
            conversationId: "conversation-p1",
          }),
        );
      }),
    );
    await store().retryQueuedMessage(failed.clientMessageId);

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      clientMessageId: failed.clientMessageId,
      assetVersionRefs: ["asset-version:av1"],
      context: request.context,
    });
    expect(store().queuedUi).toMatchObject([{ state: "queued" }]);
    expect(useCreatorEditBufferStore.getState().entries).toEqual([later]);
  });

  it("keeps a failed request in its original conversation when switching and retrying", async () => {
    bind("p1", "conversation-old");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("offline"))),
    );
    await expect(
      store().sendMessage({ message: "old instruction" }),
    ).rejects.toThrow("offline");
    const failed = store().queuedUi[0];
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      Promise.resolve(
        response(
          init?.method === "POST"
            ? {
                appendState: "queued_until_message_boundary",
                messageSeq: 1,
                eventSeq: 1,
              }
            : { items: [] },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    await store().setConversation("conversation-new");
    await store().retryQueuedMessage(failed.clientMessageId);
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(0);
    expect(store().queuedUi[0]).toMatchObject({
      state: "failed",
      conversationId: "conversation-old",
    });
    await store().setConversation("conversation-old");
    await store().retryQueuedMessage(failed.clientMessageId);
    const [, init] = fetchMock.mock.calls.find(
      ([, options]) => options?.method === "POST",
    )!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      conversationId: "conversation-old",
      clientMessageId: failed.clientMessageId,
      message: "old instruction",
    });
  });

  it("records an in-flight failure for recovery after returning to that conversation", async () => {
    bind("p1", "conversation-old");
    const pending = stubPending();
    const send = store().sendMessage({ message: "old instruction" });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response({ items: [] }))),
    );
    await store().setConversation("conversation-new");
    pending.resolve(response({ message: "offline" }, 500));
    await expect(send).rejects.toThrow();
    await store().setConversation("conversation-old");
    expect(store().queuedUi[0]).toMatchObject({
      state: "failed",
      text: "old instruction",
    });
  });

  it("does not merge an old pagination response into a new project", async () => {
    const pending = stubPending();
    bind("p1", "conversation-p1");
    // Older-history paging needs a loaded oldest message to anchor `before`.
    useCreatorSessionStore.setState({ messages: [message("p1", 5)] });

    const load = store().loadOlderMessages();
    store().reset();
    bind("p2", "conversation-p2");
    useCreatorSessionStore.setState({ messages: [message("p2")] });
    pending.resolve(response({ items: [message("p1", 2)], nextBefore: null }));
    await load;

    expect(store()).toMatchObject({
      projectId: "p2",
      loadingOlder: false,
      messages: [message("p2")],
    });
  });

  it("does not activate a conversation created for a previous project", async () => {
    const pending = stubPending();
    bind("p1", "conversation-p1");

    const create = store().newConversation();
    store().reset();
    bind("p2", "conversation-p2");
    pending.resolve(
      response({
        conversationId: "created-for-p1",
        creatorSessionId: "session-p1",
        title: "旧项目新对话",
        createdAt: "2026-07-23T00:00:00Z",
      }),
    );
    expect(await create).toBe("created-for-p1");

    expect(store()).toMatchObject({
      projectId: "p2",
      activeConversationId: "conversation-p2",
      conversations: [],
    });
  });
});
