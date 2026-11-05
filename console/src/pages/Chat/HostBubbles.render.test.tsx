import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import ComposedProvider from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/ChatAnywhere/ComposedProvider";
import {
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
} from "@agentscope-ai/chat";
import {
  DeferredHistoryContent,
  HostRequestCard,
  HostResponseCard,
} from "./HostBubbles";
import * as assistantMarkdown from "./AssistantMarkdown";
import { ChatScalar, ChatList } from "../../plugins/registry/slotKeys";
import {
  setAssistantMessageDisplayPreference,
  setShowThinkingPreference,
} from "../../utils/chatDisplayPreference";

const extensions = vi.hoisted(() => ({
  scalar: {} as Record<string, unknown>,
  lists: {} as Record<string, unknown[]>,
}));
vi.mock("../../plugins/registry/useChatExtensions", () => ({
  useChatScalarSnapshot: () => extensions.scalar,
  useChatListSnapshot: () =>
    new Proxy(extensions.lists, {
      get: (target, key: string) => target[key] ?? [],
    }),
}));
vi.mock("../../components/RenderableCodeBlock", () => ({
  renderableCodeComponents: {},
}));
vi.mock("../../features/files-workspace/ResponseArtifactList", () => ({
  default: () => null,
}));
vi.mock("../../components/Chat/MediaDownload", () => ({
  DownloadableAudios: () => null,
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
// Keep the real vendor Request/Card and SDK contexts. Only visual leaves are
// stubbed: the shared test design alias omits vendor ConfigProvider internals.
vi.mock("@agentscope-ai/icons", async (importOriginal) => {
  const icons = await importOriginal<Record<string, unknown>>();
  const placeholder = () => <span />;
  return new Proxy(icons, {
    has: (target, key) =>
      Reflect.has(target, key) || String(key).startsWith("Spark"),
    get: (target, key) =>
      Reflect.get(target, key) ??
      (String(key).startsWith("Spark") ? placeholder : undefined),
  });
});
vi.mock("@agentscope-ai/chat/lib/Bubble", () => ({
  default: Object.assign(
    ({ cards }: { cards?: Array<{ data: { content?: string } }> }) => (
      <div>
        {cards?.map((card, index) => (
          <span key={index}>{card.data.content}</span>
        ))}
      </div>
    ),
    {
      Spin: () => <span>loading</span>,
      Interrupted: () => <span>interrupted</span>,
    },
  ),
}));
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Request/Actions",
  () => ({ default: () => <span>request-actions</span> }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Reasoning",
  () => ({
    default: ({ data }: { data: { content: Array<{ text?: string }> } }) => (
      <span>{data.content[0]?.text ?? "reasoning content"}</span>
    ),
  }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Tool",
  () => ({ default: () => <span>tool content</span> }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Actions",
  () => ({
    default: ({ messageId }: { messageId: string }) => (
      <span data-testid="response-actions">{messageId}</span>
    ),
  }),
);
vi.mock("./LazyAccordion", () => ({
  default: ({
    renderChildren,
    defaultOpen,
  }: {
    renderChildren: () => ReactNode;
    defaultOpen: boolean;
  }) => (
    <section data-testid="steps" data-open={String(defaultOpen)}>
      {renderChildren()}
    </section>
  ),
}));

function provider(children: ReactNode) {
  return (
    <ComposedProvider
      options={{
        api: {},
        session: {
          currentSessionId: undefined,
          api: {
            getSessionList: async () => [],
            getSession: async (id) => ({ id, name: id, messages: [] }),
            createSession: async (draft) => {
              const session = {
                id: "fixture-session",
                name: draft.name || "",
                messages: [],
              };
              return { sessions: [session], session };
            },
            updateSession: async () => [],
            removeSession: async () => [],
          },
        },
      }}
      cards={{}}
    >
      {children}
    </ComposedProvider>
  );
}

beforeEach(() => {
  extensions.scalar = {};
  extensions.lists = {};
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("merged host bubbles behavior", () => {
  it("bounds mounted reasoning steps inside a large assistant response", () => {
    const output = Array.from({ length: 200 }, (_, index) => ({
      id: `reason-${index}`,
      object: "message",
      type: "reasoning",
      role: "assistant",
      status: "completed",
      content: [{ type: "text", text: `bounded-reason-${index}` }],
    }));
    const view = render(
      provider(
        <HostResponseCard
          id="bounded"
          data={
            {
              id: "bounded",
              object: "response",
              status: "completed",
              output,
            } as never
          }
        />,
      ),
    );
    expect(view.getAllByText(/^bounded-reason-/)).toHaveLength(32);
    expect(view.queryByText("bounded-reason-199")).toBeNull();
  });

  it.each(["⟦ internal summary ⟧", "<!-- ⟦ internal summary ⟧ -->"])(
    "hides historical headline %s without mutating stored content",
    (headline) => {
      vi.stubGlobal("IntersectionObserver", undefined);
      const original = `Visible reply\n\n${headline}`;
      const content = [{ type: "text" as const, text: original }];
      const markdown = vi
        .spyOn(assistantMarkdown, "AssistantMarkdown")
        .mockImplementation(({ content: text }) => <span>{text}</span>);
      try {
        setAssistantMessageDisplayPreference("expanded");
        render(
          provider(
            <HostResponseCard
              id="headline-history"
              data={{
                id: "response",
                status: AgentScopeRuntimeRunStatus.Completed,
                output: [
                  {
                    id: "reply",
                    role: "assistant",
                    type: AgentScopeRuntimeMessageType.MESSAGE,
                    status: AgentScopeRuntimeRunStatus.Completed,
                    metadata: { qwenpaw_history: true },
                    content,
                  },
                ],
              }}
            />,
          ),
        );
        expect(screen.getByText("Visible reply")).toBeInTheDocument();
        expect(screen.queryByText(/internal summary/)).toBeNull();
        expect(content[0].text).toBe(original);
      } finally {
        markdown.mockRestore();
      }
    },
  );

  it("defers historical content until it approaches the viewport", () => {
    let notify: IntersectionObserverCallback | undefined;
    const disconnect = vi.fn();
    const observe = vi.fn();
    class IntersectionObserverStub {
      constructor(callback: IntersectionObserverCallback) {
        notify = callback;
      }

      disconnect = disconnect;
      observe = observe;
      unobserve = vi.fn();
      takeRecords = () => [];
      root = null;
      rootMargin = "300px 0px";
      thresholds = [0];
    }
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);

    render(
      <DeferredHistoryContent enabled>
        <span>historical markdown</span>
      </DeferredHistoryContent>,
    );

    expect(screen.queryByText("historical markdown")).not.toBeInTheDocument();
    expect(observe).toHaveBeenCalledTimes(1);
    act(() => {
      notify?.(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });
    expect(screen.getByText("historical markdown")).toBeInTheDocument();
    expect(disconnect).toHaveBeenCalled();
  });

  it.each([
    [undefined, AgentScopeRuntimeRunStatus.InProgress, true],
    [null, AgentScopeRuntimeRunStatus.InProgress, true],
    [undefined, AgentScopeRuntimeRunStatus.Completed, false],
    [
      AgentScopeRuntimeRunStatus.Completed,
      AgentScopeRuntimeRunStatus.InProgress,
      false,
    ],
  ])(
    "uses message status when text status is %s (message %s)",
    async (status, messageStatus, isStreaming) => {
      const markdown = vi
        .spyOn(assistantMarkdown, "AssistantMarkdown")
        .mockImplementation(() => <></>);
      try {
        setAssistantMessageDisplayPreference("expanded");
        render(
          provider(
            <HostResponseCard
              id="sdk-message"
              data={{
                id: "response",
                status: messageStatus,
                output: [
                  {
                    id: "text-message",
                    type: AgentScopeRuntimeMessageType.MESSAGE,
                    role: "assistant",
                    status: messageStatus,
                    content: [
                      { type: "text", text: "```openui-lang\nroot =", status },
                    ],
                  },
                ],
              }}
              isLast
            />,
          ),
        );
        await act(async () => {});
        const props = markdown.mock.calls[markdown.mock.calls.length - 1][0];
        expect({
          isStreaming: props.isStreaming,
          cursor: props.cursor,
        }).toEqual({
          isStreaming,
          // Preserve the existing vendor cursor behavior for users without plugins.
          cursor: false,
        });
      } finally {
        markdown.mockRestore();
      }
    },
  );

  it("delegates oversized history to the shared Markdown renderer", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const content = Array.from(
      { length: 3000 },
      (_, index) => `## Finding ${index}\n\n${"x".repeat(32)}\n\n`,
    ).join("");
    const markdown = vi
      .spyOn(assistantMarkdown, "AssistantMarkdown")
      .mockImplementation(({ content: chunk }) => (
        <span data-testid="history-markdown-chunk">{chunk}</span>
      ));
    try {
      setAssistantMessageDisplayPreference("expanded");
      render(
        provider(
          <HostResponseCard
            id="history-message"
            data={{
              id: "history-response",
              status: AgentScopeRuntimeRunStatus.Completed,
              output: [
                {
                  id: "large-history-message",
                  type: AgentScopeRuntimeMessageType.MESSAGE,
                  role: "assistant",
                  status: AgentScopeRuntimeRunStatus.Completed,
                  metadata: { qwenpaw_history: true },
                  content: [{ type: "text", text: content }],
                },
              ],
            }}
          />,
        ),
      );

      expect(screen.getAllByTestId("history-markdown-chunk")).toHaveLength(1);
      expect(screen.getByTestId("history-markdown-chunk").textContent).toBe(
        content,
      );
    } finally {
      markdown.mockRestore();
    }
  });

  it("delegates response actions without injecting regenerate", async () => {
    setAssistantMessageDisplayPreference("expanded");
    const output = [
      {
        id: "reason",
        type: AgentScopeRuntimeMessageType.REASONING,
        role: "assistant",
        status: AgentScopeRuntimeRunStatus.Completed,
        content: [],
      },
      {
        id: "tool",
        type: AgentScopeRuntimeMessageType.FUNCTION_CALL,
        role: "assistant",
        status: AgentScopeRuntimeRunStatus.Completed,
        content: [],
      },
    ];
    render(
      provider(
        <HostResponseCard
          id="sdk-message-id"
          data={{
            id: "runtime-response-id",
            status: AgentScopeRuntimeRunStatus.Completed,
            output,
          }}
          isLast
        />,
      ),
    );
    expect(screen.getByText("reasoning content")).toBeInTheDocument();
    expect(screen.getByText("tool content")).toBeInTheDocument();
    expect(screen.queryByTestId("steps")).not.toBeInTheDocument();
    await act(async () => {
      setShowThinkingPreference(false);
    });
    expect(screen.queryByText("reasoning content")).not.toBeInTheDocument();
    await act(async () => {
      setAssistantMessageDisplayPreference("process-collapsed");
    });
    expect(screen.getByTestId("steps")).toHaveAttribute("data-open", "false");
    expect(screen.getByTestId("response-actions")).toHaveTextContent(
      "sdk-message-id",
    );
    expect(
      screen.queryByRole("button", { name: "chat.regenerate" }),
    ).not.toBeInTheDocument();
  });

  it("renders every text block in a multi-block reasoning message", () => {
    setAssistantMessageDisplayPreference("expanded");
    render(
      provider(
        <HostResponseCard
          id="multi-reasoning"
          data={{
            id: "response",
            status: AgentScopeRuntimeRunStatus.Completed,
            output: [
              {
                id: "reasoning",
                role: "assistant",
                type: AgentScopeRuntimeMessageType.REASONING,
                status: AgentScopeRuntimeRunStatus.Completed,
                content: [
                  { type: "text", text: "reasoning first" },
                  { type: "text", text: "reasoning last" },
                ],
              },
            ],
          }}
        />,
      ),
    );
    expect(
      screen.getByText("reasoning first reasoning last"),
    ).toHaveTextContent("reasoning first reasoning last");
  });

  it("retains the original request card's content and ordered prepend/append fallback", () => {
    extensions.lists[ChatList.requestPrepend] = [
      {
        pluginId: "test",
        item: {
          id: "late",
          order: 20,
          render: () => <span>prepend-late</span>,
        },
      },
      {
        pluginId: "test",
        item: {
          id: "early",
          order: 10,
          render: () => <span>prepend-early</span>,
        },
      },
    ];
    extensions.lists[ChatList.requestAppend] = [
      {
        pluginId: "test",
        item: { id: "append", render: () => <span>append-content</span> },
      },
    ];
    extensions.scalar[ChatScalar.requestRender] = {
      pluginId: "test",
      value: ({ fallback }: { fallback: () => ReactNode }) => (
        <div data-testid="plugin-request">{fallback()}</div>
      ),
    };
    const { container } = render(
      provider(
        <HostRequestCard
          data={{
            input: [
              {
                role: "user",
                content: [{ type: "text", text: "original request content" }],
              },
            ],
          }}
        />,
      ),
    );
    expect(screen.getByTestId("plugin-request")).toBeInTheDocument();
    expect(container.textContent).toMatch(
      /prepend-early[\s\S]*prepend-late[\s\S]*original request content[\s\S]*append-content[\s\S]*request-actions/,
    );
  });
});
