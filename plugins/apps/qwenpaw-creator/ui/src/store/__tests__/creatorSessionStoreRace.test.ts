import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreatorMessage, CreatorSessionView } from "@/contracts/creator";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 400 ? "Failed" : "OK",
    json: async () => body,
  } as Response;
}

function session(projectId: string): CreatorSessionView {
  return {
    id: `session-${projectId}`,
    projectId,
    status: "IDLE",
    lastMessageSeq: 0,
    lastConsumedMessageSeq: 0,
    lastEventSeq: 0,
  };
}

function message(projectId: string, messageSeq = 1): CreatorMessage {
  return {
    messageId: `message-${projectId}-${messageSeq}`,
    messageSeq,
    role: "user",
    content: [{ type: "text", text: projectId }],
    metadata: {},
    createdAt: "2026-07-23T00:00:00Z",
  };
}

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
    useCreatorSessionStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it("drops an old send acceptance after switching projects", async () => {
    const pendingResponse = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pendingResponse.promise),
    );
    bind("p1", "conversation-p1");

    const send = useCreatorSessionStore
      .getState()
      .sendMessage({ message: "old project message" });
    expect(useCreatorSessionStore.getState().queuedUi).toHaveLength(1);

    useCreatorSessionStore.getState().reset();
    bind("p2", "conversation-p2");
    useCreatorSessionStore.setState({ messages: [message("p2")] });
    pendingResponse.resolve(
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

    expect(useCreatorSessionStore.getState()).toMatchObject({
      projectId: "p2",
      activeConversationId: "conversation-p2",
      queuedUi: [],
      messages: [message("p2")],
    });
  });

  it("drops an old send failure after switching conversations", async () => {
    const pendingResponse = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pendingResponse.promise),
    );
    bind("p1", "conversation-old");

    const send = useCreatorSessionStore
      .getState()
      .sendMessage({ message: "old conversation message" });
    useCreatorSessionStore.setState({
      activeConversationId: "conversation-new",
      queuedUi: [],
    });
    pendingResponse.resolve(
      response(
        {
          code: "MODEL_REQUEST_FAILED",
          message: "provider leaked internal details",
        },
        500,
      ),
    );

    await expect(send).rejects.toThrow("provider leaked internal details");
    expect(useCreatorSessionStore.getState()).toMatchObject({
      activeConversationId: "conversation-new",
      queuedUi: [],
    });
  });

  it("does not merge an old pagination response into a new project", async () => {
    const pendingResponse = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pendingResponse.promise),
    );
    bind("p1", "conversation-p1");

    const load = useCreatorSessionStore.getState().loadOlderMessages();
    useCreatorSessionStore.getState().reset();
    bind("p2", "conversation-p2");
    useCreatorSessionStore.setState({ messages: [message("p2")] });
    pendingResponse.resolve(
      response({ items: [message("p1", 2)], nextAfter: null }),
    );
    await load;

    expect(useCreatorSessionStore.getState()).toMatchObject({
      projectId: "p2",
      loadingOlder: false,
      messages: [message("p2")],
    });
  });

  it("does not activate a conversation created for a previous project", async () => {
    const pendingResponse = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pendingResponse.promise),
    );
    bind("p1", "conversation-p1");

    const create = useCreatorSessionStore.getState().newConversation();
    useCreatorSessionStore.getState().reset();
    bind("p2", "conversation-p2");
    pendingResponse.resolve(
      response({
        conversationId: "created-for-p1",
        creatorSessionId: "session-p1",
        title: "旧项目新对话",
        createdAt: "2026-07-23T00:00:00Z",
      }),
    );
    expect(await create).toBe("created-for-p1");

    expect(useCreatorSessionStore.getState()).toMatchObject({
      projectId: "p2",
      activeConversationId: "conversation-p2",
      conversations: [],
    });
  });
});
