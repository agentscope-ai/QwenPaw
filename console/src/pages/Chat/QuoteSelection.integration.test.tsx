import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRef } from "react";
import type { IAgentScopeRuntimeWebUIOptions } from "@agentscope-ai/chat";
import useChatController from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/hooks/useChatController";
import { ConfigProvider } from "antd";
import ComposedProvider from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/ChatAnywhere/ComposedProvider";
import SdkInput from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/Input";
import { HostResponseCard } from "./HostBubbles";
import { LongTextPasteInput } from "./LongTextPaste";
import { QuoteSelection } from "./QuoteSelection";
import { useChatInputDraft } from "./chatInputDraft";
import defaultConfig from "./OptionsPanel/defaultConfig";
import i18n from "../../i18n";

vi.mock("@agentscope-ai/design", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ConfigProvider: (await import("antd")).ConfigProvider,
}));
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

function Composer() {
  const { handleSubmit, handleCancel } = useChatController();
  return <SdkInput onCancel={handleCancel} onSubmit={handleSubmit} />;
}
const emptyResponse = () =>
  Promise.resolve(
    new Response(
      "data: " +
        JSON.stringify({
          object: "response",
          id: "turn",
          status: "completed",
          output: [],
        }) +
        "\n\n",
      { headers: { "Content-Type": "text/event-stream" } },
    ),
  );

function Chat({
  scopeKey = "agent-a:chat-a",
  submit = emptyResponse,
  enabled = true,
}: {
  scopeKey?: string;
  submit?: NonNullable<IAgentScopeRuntimeWebUIOptions["api"]>["fetch"];
  enabled?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [agent, session] = scopeKey.split(":");
  useChatInputDraft(true, agent, session);
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <div ref={containerRef}>
        <ComposedProvider
          cards={{}}
          options={{
            api: { fetch: submit },
            session: {},
            sender: {
              ...defaultConfig.sender,
              attachments: undefined,
              components: { input: LongTextPasteInput },
            },
          }}
        >
          <div data-testid="user">User text</div>
          <HostResponseCard
            id="response"
            data={{
              id: "response",
              status: "completed",
              output: [
                {
                  id: "answer",
                  type: "message",
                  role: "assistant",
                  status: "completed",
                  content: [
                    {
                      type: "text",
                      text: "First **answer** paragraph.\n\nSecond paragraph.\n\n```python\nif ready:\n    run()\n```\n\nNext example.\n\n```javascript\nconst ready = true;\n```",
                    },
                  ],
                },
                {
                  id: "system",
                  type: "message",
                  role: "system",
                  status: "completed",
                  content: [{ type: "text", text: "System notice" }],
                },
              ],
            }}
            isLast
          />
          <Composer />
        </ComposedProvider>
        <QuoteSelection
          containerRef={containerRef}
          scopeKey={scopeKey}
          enabled={enabled}
        />
      </div>
    </ConfigProvider>
  );
}

async function select(element: Element) {
  await act(async () => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  });
}
beforeEach(async () => {
  vi.restoreAllMocks();
  localStorage.clear();
  await i18n.changeLanguage("en");
  window.getSelection()?.removeAllRanges();
  // jsdom has no layout engine; selection and SDK rendering are real.
  Range.prototype.getBoundingClientRect = () => new DOMRect(40, 100, 120, 20);
});

describe("quote selection with the installed SDK renderer and sender", () => {
  it("keeps inserted quotes in their conversation draft across chat and agent switches", async () => {
    const view = render(<Chat />);
    await select((await screen.findByText("answer")).closest("p")!);
    fireEvent.click(screen.getByRole("button", { name: "Quote to follow-up" }));
    const expected = "> First answer paragraph.\n\n";
    expect(screen.getByRole("textbox")).toHaveValue(expected);
    for (const scopeKey of ["agent-a:chat-b", "agent-b:chat-a"]) {
      view.rerender(<Chat scopeKey={scopeKey} />);
      await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
    }
    view.rerender(<Chat />);
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveValue(expected),
    );
  });

  it("appends repeated quotes to the latest draft without replacing earlier text", async () => {
    render(<Chat />);
    const textarea = screen.getByRole("textbox");
    await select((await screen.findByText("answer")).closest("p")!);
    fireEvent.change(textarea, { target: { value: "Keep latest edits" } });
    fireEvent.click(screen.getByRole("button", { name: "Quote to follow-up" }));
    await select(screen.getByText("Second paragraph.").closest("p")!);
    fireEvent.click(screen.getByRole("button", { name: "Quote to follow-up" }));
    expect(textarea).toHaveValue(
      "Keep latest edits\n\n> First answer paragraph.\n\n> Second paragraph.\n\n",
    );
  });

  it("appends selected assistant text to the existing draft and submits it normally", async () => {
    const submit =
      vi.fn<
        NonNullable<NonNullable<IAgentScopeRuntimeWebUIOptions["api"]>["fetch"]>
      >(emptyResponse);
    render(<Chat submit={submit} />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "My follow-up" } });
    await select((await screen.findByText("answer")).closest("p")!);
    const quote = await screen.findByRole("button", {
      name: "Quote to follow-up",
    });
    fireEvent.pointerDown(quote);
    fireEvent.click(quote);
    const expected = "My follow-up\n\n> First answer paragraph.\n\n";
    await waitFor(() => expect(textarea).toHaveValue(expected));
    expect(textarea).toHaveFocus();
    expect(
      screen.queryByRole("button", { name: "Quote to follow-up" }),
    ).toBeNull();
    fireEvent.keyDown(textarea, { key: "Enter" });
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0][0].input[0]).toMatchObject({
      role: "user",
      content: [{ type: "text", text: expected }],
    });
  });
  it("quotes prose across multiple code blocks without copying their headers or controls", async () => {
    const { container } = render(<Chat />);
    await screen.findByText("Next example.");
    await act(async () => {
      const range = document.createRange();
      range.setStartBefore(screen.getByText("answer").closest("p")!);
      range.setEndAfter(container.querySelectorAll("pre code")[1]);
      window.getSelection()!.removeAllRanges();
      window.getSelection()!.addRange(range);
      // jsdom has no layout: Chromium/browser coverage verifies block newlines
      // and CSS user-select:none excludes the code toolbar from native selection.
      vi.spyOn(window.getSelection()!, "toString").mockReturnValue(
        "First answer paragraph.\n\nSecond paragraph.\n\nif ready:\n    run()\nNext example.\n\nconst ready = true;",
      );
      document.dispatchEvent(new Event("selectionchange"));
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Quote to follow-up" }),
    );
    expect(screen.getByRole("textbox")).toHaveValue(
      "> First answer paragraph.\n> \n> Second paragraph.\n> \n> if ready:\n>     run()\n> Next example.\n> \n> const ready = true;\n\n",
    );
  });

  it("preserves code line breaks and indentation through the keyboard shortcut", async () => {
    const { container } = render(<Chat />);
    await waitFor(() =>
      expect(container.querySelector("pre code")).not.toBeNull(),
    );
    await select(container.querySelector("pre code")!);
    for (const modifier of ["ctrlKey", "metaKey"]) {
      fireEvent.keyDown(document, {
        key: "q",
        code: "KeyQ",
        altKey: true,
        shiftKey: true,
        [modifier]: true,
      });
      expect(screen.getByRole("textbox")).toHaveValue("");
    }
    fireEvent.keyDown(document, {
      key: "Œ",
      code: "KeyQ",
      altKey: true,
      shiftKey: true,
    });
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveValue(
        "> if ready:\n>     run()\n\n",
      ),
    );
  });
  it.each(["agent-a:chat-b", "agent-b:chat-a"])(
    "discards pending selection when switching to %s",
    async (scopeKey) => {
      const view = render(<Chat />);
      await select((await screen.findByText("answer")).closest("p")!);
      expect(
        screen.getByRole("button", { name: "Quote to follow-up" }),
      ).toBeInTheDocument();
      view.rerender(<Chat scopeKey={scopeKey} />);
      expect(
        screen.queryByRole("button", { name: "Quote to follow-up" }),
      ).toBeNull();
      fireEvent.keyDown(document, { key: "q", altKey: true, shiftKey: true });
      expect(screen.getByRole("textbox")).toHaveValue("");
    },
  );
  it("ignores user messages, system notices, code controls, and cross-message selections", async () => {
    const { container } = render(<Chat />);
    for (const element of [
      screen.getByTestId("user"),
      await screen.findByText("System notice"),
      container.querySelector("header")!,
    ]) {
      await select(element);
      expect(
        screen.queryByRole("button", { name: "Quote to follow-up" }),
      ).toBeNull();
    }
    await act(async () => {
      const range = document.createRange();
      range.setStartBefore(screen.getByTestId("user"));
      range.setEndAfter(screen.getByText("answer"));
      window.getSelection()!.removeAllRanges();
      window.getSelection()!.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
    });
    expect(
      screen.queryByRole("button", { name: "Quote to follow-up" }),
    ).toBeNull();
  });
  it("dismisses on Escape and while the session is loading", async () => {
    const view = render(<Chat />);
    await select((await screen.findByText("answer")).closest("p")!);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("button", { name: "Quote to follow-up" }),
    ).toBeNull();
    view.rerender(<Chat enabled={false} />);
    await select(screen.getByText("answer").closest("p")!);
    expect(
      screen.queryByRole("button", { name: "Quote to follow-up" }),
    ).toBeNull();
  });
});
