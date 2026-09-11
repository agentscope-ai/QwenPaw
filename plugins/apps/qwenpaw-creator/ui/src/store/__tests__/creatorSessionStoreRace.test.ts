import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreatorMessage, CreatorSessionView } from "@/contracts/creator";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";

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
