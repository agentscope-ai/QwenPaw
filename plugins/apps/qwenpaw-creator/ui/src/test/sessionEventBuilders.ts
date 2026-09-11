import type {
  CreatorEvent,
  CreatorMessage,
  CreatorSessionView,
} from "@/contracts/creator";

/** Minimal durable Creator event; only seq/type/data vary per test. */
export function ev(
  seq: number,
  type: string,
  data: Record<string, unknown> = {},
): CreatorEvent {
  return {
    eventId: `ev-${seq}`,
    seq,
    type,
    projectId: "p1",
    creatorSessionId: "s1",
    at: "now",
    data,
  };
}

/** Minimal durable conversation message DTO. */
export function msg(
  overrides: Partial<CreatorMessage> & {
    messageId: string;
    messageSeq: number;
  },
): CreatorMessage {
  return {
    role: "user",
    content: [{ type: "text", text: "消息" }],
    source: "user",
    metadata: {},
    createdAt: "now",
    ...overrides,
  };
}

export function sessionView(
  overrides: Partial<CreatorSessionView> = {},
): CreatorSessionView {
  return {
    id: "s1",
    projectId: "p1",
    status: "RUNNING",
    lastMessageSeq: 0,
    lastConsumedMessageSeq: 0,
    lastEventSeq: 0,
    ...overrides,
  };
}

/** Mock routes for a full Creator Session bootstrap (conversation c1). */
export function bootstrapRoutes(
  options: {
    messages?: CreatorMessage[];
    session?: Partial<CreatorSessionView>;
  } = {},
) {
  const session = sessionView({ status: "RUNNING", ...options.session });
  return [
    {
      match: "/conversations/c1/messages",
      response: { json: { items: options.messages ?? [] } },
    },
    {
      match: "/conversations",
      response: {
        json: {
          items: [
            {
              conversationId: "c1",
              title: "默认对话",
              isDefault: true,
              createdAt: "now",
            },
          ],
        },
      },
    },
    {
      match: "/session",
      response: {
        json: {
          session,
          agentStatusBar: {
            progress: {
              phase: "timeline_edit",
              label: "执行中",
              sourceEventSeq: session.lastEventSeq,
              updatedAt: "now",
            },
            badges: [],
          },
        },
      },
    },
  ];
}

/** Named SSE sources captured by the test EventSource stub. */
export function testEventSources(): Array<{
  url: string;
  emit: (type: string, value: unknown) => void;
}> {
  return (
    globalThis as unknown as {
      __testEventSources: Array<{
        url: string;
        emit: (type: string, value: unknown) => void;
      }>;
    }
  ).__testEventSources;
}
