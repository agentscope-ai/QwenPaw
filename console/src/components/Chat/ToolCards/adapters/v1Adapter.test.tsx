// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import { adaptCardForV1, withGenericFallback } from "./v1Adapter";
import { ToolCallTurnEndedContext } from "../shared/ToolCallTurnContext";
import type { ToolCallContent } from "../shared/types";

const deferredCard = vi.hoisted(() => ({
  loaded: vi.fn(),
  resolve: undefined as undefined | (() => void),
}));

vi.mock("../cards/ShellCard", async () => {
  deferredCard.loaded();
  await new Promise<void>((resolve) => {
    deferredCard.resolve = resolve;
  });
  return {
    default: ({ content }: { content: ToolCallContent }) => (
      <div data-testid="lazy-result">{String(content.result ?? "waiting")}</div>
    ),
  };
});

it("lazy builtin cards load on render and retain updates received while loading", async () => {
  const { BUILTIN_CARD_REGISTRY } = await import("../lazyRegistry");
  expect(deferredCard.loaded).not.toHaveBeenCalled();
  expect(BUILTIN_CARD_REGISTRY.shell).toBe(BUILTIN_CARD_REGISTRY.bash);
  const Card = adaptCardForV1(BUILTIN_CARD_REGISTRY.shell);
  const { rerender } = render(<Card {...callOnlyProps} />);
  await vi.waitFor(() => expect(deferredCard.loaded).toHaveBeenCalledOnce());
  expect(screen.queryByTestId("lazy-result")).not.toBeInTheDocument();
  rerender(<Card {...withOutputProps("latest output", "done")} />);
  await act(async () => deferredCard.resolve?.());
  expect(await screen.findByTestId("lazy-result")).toHaveTextContent(
    "latest output",
  );
  rerender(<Card {...withOutputProps("next output", "done")} />);
  expect(screen.getByTestId("lazy-result")).toHaveTextContent("next output");
  expect(deferredCard.loaded).toHaveBeenCalledOnce();
});

vi.mock("../cards/GenericToolCard", () => ({
  default: ({ content }: { content: ToolCallContent }) => (
    <div data-testid="generic-result">{String(content.result ?? "")}</div>
  ),
}));

it("preserves explicit plugin renderers and lazily renders unknown tools", async () => {
  const pluginCard = () => <div>plugin override</div>;
  const registry = withGenericFallback({ shell: pluginCard });
  expect(registry.shell).toBe(pluginCard);
  expect(registry.unknown_tool).toBe(registry.other_unknown_tool);
  const UnknownCard = registry.unknown_tool;
  const { rerender } = render(
    <UnknownCard {...withOutputProps("unknown result", "done")} />,
  );
  expect(await screen.findByTestId("generic-result")).toHaveTextContent(
    "unknown result",
  );
  const PluginCard = registry.shell;
  rerender(<PluginCard />);
  expect(screen.getByText("plugin override")).toBeInTheDocument();
});

const Probe = ({
  content,
  isStreaming,
}: {
  content: ToolCallContent;
  isStreaming?: boolean;
}) => (
  <div>
    <span data-testid="status">{content.status}</span>
    <span data-testid="streaming">{String(Boolean(isStreaming))}</span>
    <span data-testid="interrupted">
      {String(Boolean(content.interrupted))}
    </span>
    <span data-testid="result">{String(content.result ?? "")}</span>
    <span data-testid="execStarted">
      {String(Boolean(content.executionStarted))}
    </span>
  </div>
);

const WrappedProbe = adaptCardForV1(Probe);

const callContent = {
  data: {
    call_id: "call-1",
    name: "execute_shell_command",
    arguments: JSON.stringify({ command: "ping 127.0.0.1 -n 31" }),
  },
};

/** A tool call message whose result never arrived. */
const callOnlyProps = {
  data: {
    type: "plugin_call",
    // The call message completes as soon as its arguments are streamed —
    // it says nothing about the execution itself.
    status: "completed",
    content: [callContent],
  },
};

/** A tool call merged with its result message. */
const withOutputProps = (
  output: string,
  state?: string,
  status = "completed",
) => ({
  data: {
    type: "plugin_call_output",
    status,
    content: [
      callContent,
      {
        data: {
          call_id: "call-1",
          name: "execute_shell_command",
          output,
          ...(state ? { state } : {}),
        },
      },
    ],
  },
});

const renderCard = (props: unknown, turnEnded: boolean) =>
  render(
    <ToolCallTurnEndedContext.Provider value={turnEnded}>
      <WrappedProbe {...(props as Record<string, unknown>)} />
    </ToolCallTurnEndedContext.Provider>,
  );

describe("v1Adapter tool status", () => {
  it("keeps a pending call running while its turn streams", () => {
    renderCard(callOnlyProps, false);

    expect(screen.getByTestId("status")).toHaveTextContent("calling");
    expect(screen.getByTestId("streaming")).toHaveTextContent("true");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("false");
    expect(screen.getByTestId("result")).toHaveTextContent("");
  });

  it("does not report execution before the output message arrives", () => {
    // plugin_call completed == arguments generated; the backend has not
    // dispatched the call yet, so lifecycle queries must stay off.
    renderCard(callOnlyProps, false);

    expect(screen.getByTestId("execStarted")).toHaveTextContent("false");
  });

  it("reports execution started once the output slot exists", () => {
    // TOOL_RESULT_START shape: output message merged, still in_progress.
    renderCard(withOutputProps("", undefined, "in_progress"), false);

    expect(screen.getByTestId("status")).toHaveTextContent("calling");
    expect(screen.getByTestId("execStarted")).toHaveTextContent("true");
  });

  it("closes a pending call once its turn ended", () => {
    renderCard(callOnlyProps, true);

    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("streaming")).toHaveTextContent("false");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("true");
    // The reason is rendered by the card shell, never faked as tool output.
    expect(screen.getByTestId("result")).toHaveTextContent("");
  });

  it("reports a completed call as done regardless of turn state", () => {
    renderCard(withOutputProps("pong"), true);

    expect(screen.getByTestId("status")).toHaveTextContent("done");
    expect(screen.getByTestId("streaming")).toHaveTextContent("false");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("false");
    expect(screen.getByTestId("result")).toHaveTextContent("pong");
  });

  it("keeps the persisted interruption output of a restored call", () => {
    renderCard(withOutputProps("partial output", "interrupted"), true);

    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("true");
    expect(screen.getByTestId("result")).toHaveTextContent("partial output");
  });

  it("reports a failed tool as an error but not an interruption", () => {
    renderCard(withOutputProps("boom", "error"), true);

    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("false");
    expect(screen.getByTestId("result")).toHaveTextContent("boom");
  });

  it("keeps streaming output running while its turn streams", () => {
    renderCard(
      withOutputProps("partial output", undefined, "in_progress"),
      false,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("calling");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("false");
  });

  it("closes output that stopped mid-stream when the turn ended", () => {
    renderCard(
      withOutputProps("partial output", undefined, "in_progress"),
      true,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("interrupted")).toHaveTextContent("true");
    expect(screen.getByTestId("result")).toHaveTextContent("partial output");
  });

  it("preserves raw input and output for raw tool display", () => {
    let captured: ToolCallContent | undefined;
    const CaptureCard = ({ content }: { content: ToolCallContent }) => {
      captured = content;
      return null;
    };
    const WrappedCard = adaptCardForV1(CaptureCard);

    render(
      <WrappedCard
        data={{
          id: "message-1",
          status: "completed",
          content: [
            {
              data: {
                name: "read_file",
                call_id: "call-1",
                arguments: '{"path":"notes.txt"}',
              },
            },
            { data: { output: { text: "contents" } } },
          ],
        }}
      />,
    );

    expect(captured).toMatchObject({
      id: "call-1",
      name: "read_file",
      rawInput: '{"path":"notes.txt"}',
      params: { path: "notes.txt" },
      result: { text: "contents" },
      status: "done",
    });
  });
});
