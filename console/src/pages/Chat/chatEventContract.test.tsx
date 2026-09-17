/** 固定丰富对话事件在历史恢复与现有 Host/ToolCards 渲染器中的契约。 */
import { readFileSync } from "node:fs";
import path from "node:path";
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Request/Card",
  () => ({ default: () => <div data-testid="request-card" /> }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Actions",
  () => ({ default: () => <div data-testid="response-actions" /> }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder",
  () => ({
    default: {
      mergeToolMessages: (messages: ContractMessage[]) => messages,
      maybeGenerating: () => false,
    },
  }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereOptionsContext",
  () => ({
    useChatAnywhereOptions: (
      selector: (options: Record<string, unknown>) => unknown,
    ) => selector({ api: {}, welcome: {} }),
  }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Reasoning",
  () => ({
    default: ({ data }: { data: ContractMessage }) => (
      <div>{`reasoning:${data.contract_event_type}`}</div>
    ),
  }),
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Tool",
  async () => {
    const { ToolResponseStatusContext } = await import(
      "../../components/Chat/ToolCards/shared/ToolResponseContext"
    );
    const Status = () => (
      <span data-testid="tool-status">
        {React.useContext(ToolResponseStatusContext)}
      </span>
    );
    return {
      default: ({
        data,
        isApproval,
      }: {
        data: ContractMessage;
        isApproval?: boolean;
      }) => (
        <div>
          {`${isApproval ? "approval" : "tool"}:${data.contract_event_type}`}
          <Status />
        </div>
      ),
    };
  },
);
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Error",
  () => ({
    default: ({ data }: { data: ContractMessage }) => (
      <div>{`error:${data.contract_event_type ?? "error"}`}</div>
    ),
  }),
);
vi.mock("@agentscope-ai/chat/lib/DefaultCards/Images", () => ({
  default: () => <div>media:image</div>,
}));
vi.mock("@agentscope-ai/chat/lib/DefaultCards/Videos", () => ({
  default: () => <div>media:video</div>,
}));
vi.mock("@agentscope-ai/chat/lib/DefaultCards/Files", () => ({
  default: () => <div>media:file</div>,
}));
vi.mock("@agentscope-ai/chat/lib/DefaultCards/Audios", () => ({
  default: () => <div>media:audio</div>,
}));
vi.mock("@agentscope-ai/chat", () => ({
  Bubble: { Spin: () => <div>loading</div> },
  Markdown: ({ content }: { content: string }) => <div>{content}</div>,
}));
vi.mock("antd", async (importOriginal) => ({
  ...(await importOriginal<typeof import("antd")>()),
  Avatar: () => null,
  Flex: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
}));
vi.mock("../../components/RenderableCodeBlock", () => ({
  renderableCodeComponents: {},
}));
vi.mock("../../plugins/registry/useChatExtensions", () => ({
  useChatScalarSnapshot: () => ({}),
  useChatListSnapshot: () =>
    new Proxy({}, { get: () => [] }) as Record<string, unknown[]>,
}));
vi.mock("../../plugins/registry/PluginSlotBoundary", () => ({
  PluginSlotBoundary: ({ children }: React.PropsWithChildren) => children,
}));
vi.mock("../../api/modules/chat", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../api/modules/chat")
  >();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      filePreviewUrl: (value: string) => value,
    },
  };
});

import { HostResponseCard } from "./HostBubbles";
import { __test__ } from "./sessionApi";

interface ContractEvent {
  sequence_no: number;
  event_id: string;
  type: string;
  message_id?: string;
  tool_call_id?: string;
  approval_id?: string;
  wire: Record<string, unknown>;
}

interface ContractMessage {
  id?: string;
  type?: string;
  role?: string;
  status?: string;
  content?: Array<Record<string, unknown>>;
  contract_event_type?: string;
  [key: string]: unknown;
}

interface ContractFixture {
  events: ContractEvent[];
}

const fixturePath = path.resolve(
  process.cwd(),
  "../tests/parity/fixtures/chat_run_event_contract.json",
);
const toolCardRegistryPath = path.resolve(
  process.cwd(),
  "src/components/Chat/ToolCards/cards/index.ts",
);
const fixture = JSON.parse(
  readFileSync(fixturePath, "utf-8"),
) as ContractFixture;

const REQUIRED_EVENT_TYPES = [
  "reasoning",
  "assistant_delta",
  "tool_start",
  "approval_required",
  "approval_decided",
  "tool_output",
  "skill",
  "plugin",
  "mcp",
  "command",
  "image",
  "file",
  "progress",
  "error",
  "final",
];

function historyMessages(): ContractMessage[] {
  return fixture.events.map((event) => {
    const wire = event.wire;
    if (wire.object === "content") {
      return {
        id: event.message_id,
        type: "message",
        role: "assistant",
        status: "in_progress",
        content: [{ ...wire, object: undefined }],
        contract_event_type: event.type,
      };
    }
    if (wire.object === "approval_required") {
      return {
        id: event.event_id,
        type: "mcp_approval_request",
        role: "assistant",
        status: "in_progress",
        content: [{ type: "data", data: wire.data }],
        contract_event_type: event.type,
      };
    }
    if (wire.object === "approval_decided") {
      return {
        id: event.event_id,
        type: "plugin_call_output",
        role: "tool",
        status: "completed",
        content: [
          {
            type: "data",
            data: {
              ...(wire.data as Record<string, unknown>),
              call_id: event.tool_call_id,
              name: "approval_decision",
              output: "approved",
            },
          },
        ],
        contract_event_type: event.type,
      };
    }
    if (wire.object === "error") {
      return {
        id: event.event_id,
        type: "error",
        role: "assistant",
        status: "failed",
        content: [],
        contract_event_type: event.type,
      };
    }
    const message = wire as ContractMessage;
    const normalizedType =
      event.type === "mcp"
        ? "mcp_call"
        : event.type === "progress" || event.type === "final"
        ? "message"
        : message.type;
    return {
      ...message,
      type: normalizedType,
      contract_event_type: event.type,
    };
  });
}

describe("rich chat event contract", () => {
  it("contains every required canonical event in sequence", () => {
    expect(fixture.events.map((event) => event.type)).toEqual(
      REQUIRED_EVENT_TYPES,
    );
    expect(fixture.events.map((event) => event.sequence_no)).toEqual(
      REQUIRED_EVENT_TYPES.map((_, index) => index + 1),
    );
  });

  it("history conversion keeps the full process instead of final-only", () => {
    const cards = __test__.convertMessages(historyMessages() as never[]);
    const responseCard = cards[0]?.cards?.[0];
    const output = responseCard?.data?.output as ContractMessage[];

    expect(output.map((message) => message.contract_event_type)).toEqual(
      REQUIRED_EVENT_TYPES,
    );
    expect(output).toHaveLength(REQUIRED_EVENT_TYPES.length);
    expect(output).not.toEqual([
      expect.objectContaining({ contract_event_type: "final" }),
    ]);
  });

  it("reuses HostResponseCard and current rich render surfaces", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    render(
      <HostResponseCard
        data={{
          id: "response-rich-contract-001",
          object: "response",
          status: "completed",
          created_at: 0,
          output: historyMessages(),
        }}
      />,
    );

    expect(screen.getByText("reasoning:reasoning")).toBeInTheDocument();
    expect(screen.getByText("tool:tool_start")).toBeInTheDocument();
    expect(screen.getByText("approval:approval_required")).toBeInTheDocument();
    expect(screen.getByText("tool:approval_decided")).toBeInTheDocument();
    expect(screen.getByText("tool:tool_output")).toBeInTheDocument();
    expect(screen.getByText("tool:skill")).toBeInTheDocument();
    expect(screen.getByText("tool:plugin")).toBeInTheDocument();
    expect(screen.getByText("tool:mcp")).toBeInTheDocument();
    expect(screen.getByText("tool:command")).toBeInTheDocument();
    expect(screen.getByText("media:image")).toBeInTheDocument();
    expect(screen.getByText("media:file")).toBeInTheDocument();
    expect(screen.getByText("进度 50%")).toBeInTheDocument();
    expect(screen.getByText("error:error")).toBeInTheDocument();
    expect(screen.getByText("处理完成。")).toBeInTheDocument();
    expect(screen.getByTestId("response-actions")).toBeInTheDocument();
    expect(
      consoleError.mock.calls.some((args) =>
        args.some(
          (value) => typeof value === "string" && value.includes("same key"),
        ),
      ),
    ).toBe(false);
    consoleError.mockRestore();
  });

  it("keeps specialized ToolCards for the fixture tool and skill calls", () => {
    const registrySource = readFileSync(toolCardRegistryPath, "utf-8");
    expect(registrySource).toMatch(/read_file:\s*ReadFileCard/);
    expect(registrySource).toMatch(/materialize_skill:\s*MaterializeSkillCard/);
    expect(registrySource).toMatch(/execute_shell_command:\s*ShellCard/);
  });

  it("stops orphan tool calls when their response ends, including history and cancellation", () => {
    const data = {
      id: "interrupted-profile-read",
      object: "response",
      status: "in_progress",
      created_at: 0,
      output: [
        {
          id: "profile-call",
          type: "plugin_call",
          role: "assistant",
          // Delivery completed is NOT proof of tool completion.
          status: "completed",
          content: [
            {
              type: "data",
              data: {
                name: "read_file",
                call_id: "call-profile",
                arguments: '{"file_path":"PROFILE.md"}',
              },
            },
          ],
        },
      ],
    };
    const { rerender } = render(<HostResponseCard data={data} />);
    expect(screen.getByTestId("tool-status")).toHaveTextContent("in_progress");

    for (const status of ["completed", "canceled", "failed"]) {
      rerender(<HostResponseCard data={{ ...data, status }} />);
      expect(screen.getByTestId("tool-status")).toHaveTextContent(status);
    }

    rerender(<HostResponseCard data={{ ...data, status: "in_progress" }} />);
    expect(screen.getByTestId("tool-status")).toHaveTextContent("in_progress");
  });

  it("keeps only the current response active when restoring a running conversation", () => {
    const call = {
      role: "assistant",
      type: "plugin_call",
      status: "completed",
      content: [],
    };
    const messages = [
      { role: "user", content: "previous" },
      call,
      { role: "user", content: "current" },
      { ...call },
    ];
    const cards = __test__.convertMessages(messages, true);
    expect(cards[1].cards?.[0].data.status).toBe("completed");
    expect(cards[3].cards?.[0].data.status).toBe("in_progress");
    const idle = __test__.convertMessages(messages);
    expect(idle[3].cards?.[0].data.status).toBe("completed");
  });
});
