import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ComposedProvider from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/ChatAnywhere/ComposedProvider";
import SdkInput from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/Input";
import type { IAgentScopeRuntimeWebUIOptions } from "@agentscope-ai/chat";
import { LongTextPasteInput, LongTextPasteProvider } from "./LongTextPaste";
import defaultConfig from "./OptionsPanel/defaultConfig";
import i18n from "../../i18n";
import type { ComponentProps } from "react";
import { ConfigProvider } from "antd";

vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const design = await importOriginal<Record<string, unknown>>();
  const { ConfigProvider } = await import("antd");
  return { ...design, ConfigProvider };
});

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

// jsdom has no native clipboard constructors; the installed SDK is not mocked.
class TestDataTransfer {
  files: File[] = [];
  items = {
    add: (file: File) => this.files.push(file),
    [Symbol.iterator]: () => {
      const items = this.files.map((file) => ({
        kind: "file",
        getAsFile: () => file,
      }));
      return items[Symbol.iterator]();
    },
  };
  getData = () => "";
}

class TestClipboardEvent extends Event {
  clipboardData: DataTransfer | null;
  constructor(type: string, init: ClipboardEventInit = {}) {
    super(type, init);
    this.clipboardData = init.clipboardData ?? null;
  }
}

type UploadRequest = NonNullable<
  NonNullable<
    NonNullable<IAgentScopeRuntimeWebUIOptions["sender"]>["attachments"]
  >["customRequest"]
>;

function Composer({
  upload,
  submit = vi.fn(),
  attachments = true,
  scopeKey = "session-a",
}: {
  upload: UploadRequest;
  submit?: ComponentProps<typeof SdkInput>["onSubmit"];
  attachments?: boolean;
  scopeKey?: string;
}) {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <LongTextPasteProvider enabled={attachments} scopeKey={scopeKey}>
        <ComposedProvider
          cards={{}}
          options={{
            api: {},
            session: {},
            sender: {
              ...defaultConfig.sender,
              attachments: attachments ? { customRequest: upload } : undefined,
              components: {
                input: LongTextPasteInput,
              },
            },
          }}
        >
          <SdkInput onCancel={vi.fn()} onSubmit={submit} />
        </ComposedProvider>
      </LongTextPasteProvider>
    </ConfigProvider>
  );
}

async function selectDraft(start: number, end = start) {
  const editor = screen.getByRole("textbox") as HTMLTextAreaElement;
  await act(async () => {
    editor.focus();
  });
  await act(async () => {
    editor.setSelectionRange(start, end);
  });
  return editor;
}

async function pasteText(text: string) {
  await act(async () => {
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const draft = textarea.value;
    const nativePaste = fireEvent.paste(textarea, {
      clipboardData: {
        files: [],
        items: [],
        getData: (format: string) =>
          format === "text/plain" || format === "text" ? text : "",
      },
    });
    // jsdom dispatches paste but does not perform the browser's default edit.
    if (nativePaste) {
      fireEvent.change(textarea, {
        target: { value: `${draft.slice(0, start)}${text}${draft.slice(end)}` },
      });
      textarea.setSelectionRange(start + text.length, start + text.length);
    }
  });
}

async function setup(draft: string, upload = vi.fn<UploadRequest>()) {
  const submit = vi.fn();
  const view = render(<Composer upload={upload} submit={submit} />);
  const textarea = view.container.querySelector("textarea")!;
  fireEvent.change(textarea, { target: { value: draft } });
  await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(draft));
  await selectDraft(draft.length);
  return { ...view, textarea, upload, submit };
}

function readFile(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(file);
  });
}

describe("long-text paste with the installed SDK", () => {
  beforeEach(async () => {
    vi.stubGlobal("DataTransfer", TestDataTransfer);
    vi.stubGlobal("ClipboardEvent", TestClipboardEvent);
    await i18n.changeLanguage("en");
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps a 6000-character draft when a 5000-character paste crosses the old limit", async () => {
    const draft = "a".repeat(6000);
    const pasted = "b".repeat(5000);
    const { textarea, upload } = await setup(draft);
    await pasteText(pasted);
    await waitFor(() => expect(textarea).toHaveValue(draft + pasted));
    expect(upload).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("pastes exactly 10000 characters without a dialog", async () => {
    const { textarea } = await setup("draft");
    await pasteText("b".repeat(10000));
    await waitFor(() => expect(textarea.value).toHaveLength(10005));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("pastes into an empty composer without truncation", async () => {
    const { textarea, upload } = await setup("");
    const pasted = "b".repeat(10001);
    await pasteText(pasted);
    fireEvent.click(
      await screen.findByRole("button", { name: "Paste as text" }),
    );
    await waitFor(() => expect(textarea).toHaveValue(pasted));
    expect(upload).not.toHaveBeenCalled();
  });

  it("keeps pasted text when a pending send clears the draft during the choice", async () => {
    const { textarea, upload } = await setup("submitted draft");
    const pasted = "b".repeat(10001);
    await pasteText(pasted);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.change(textarea, { target: { value: "" } });
    await waitFor(() => expect(textarea).toHaveValue(""));
    fireEvent.click(screen.getByRole("button", { name: "Paste as text" }));
    await waitFor(() => expect(textarea).toHaveValue(pasted));
    expect(upload).not.toHaveBeenCalled();
  });

  it("replaces only the selection with complete editable plain text and submits it", async () => {
    const { textarea, upload, submit } = await setup("before REPLACE after");
    await selectDraft(7, 14);
    const pasted = "line\n".repeat(2500);
    await pasteText(pasted);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(textarea).toHaveValue("before REPLACE after");
    fireEvent.click(screen.getByRole("button", { name: "Paste as text" }));
    const expected = `before ${pasted} after`;
    await waitFor(() => expect(textarea).toHaveValue(expected));
    expect(upload).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0][0].query).toBe(expected);
  });

  it("uploads only each pasted section, preserving the selected draft and later edits", async () => {
    const upload = vi.fn<UploadRequest>();
    const { textarea } = await setup("keep this draft", upload);
    await selectDraft(5, 9);
    const first = "first".repeat(2200);
    await pasteText(first);
    fireEvent.click(
      await screen.findByRole("button", { name: "Attach as file" }),
    );
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(await readFile(upload.mock.calls[0][0].file as File)).toBe(first);
    expect(textarea).toHaveValue("keep this draft");
    await selectDraft(15);
    await pasteText(" edited");
    await waitFor(() => expect(textarea).toHaveValue("keep this draft edited"));
    await act(
      async () => upload.mock.calls[0][0].onSuccess?.({ url: "/first.txt" }),
    );
    expect(textarea).toHaveValue("keep this draft edited");

    const second = "second".repeat(2000);
    await selectDraft(textarea.value.length);
    await pasteText(second);
    fireEvent.click(
      await screen.findByRole("button", { name: "Attach as file" }),
    );
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(await readFile(upload.mock.calls[1][0].file as File)).toBe(second);
    expect(textarea).toHaveValue("keep this draft edited");
  });

  it("preserves the draft and the source attachment when uploading fails", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
    const { textarea, upload, submit } = await setup("keep this draft");
    const pasted = "attachment".repeat(1100);
    await pasteText(pasted);
    fireEvent.click(
      await screen.findByRole("button", { name: "Attach as file" }),
    );
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    await act(
      async () => upload.mock.calls[0][0].onError?.(new Error("Upload failed")),
    );
    expect(textarea).toHaveValue("keep this draft");
    expect(await readFile(upload.mock.calls[0][0].file as File)).toBe(pasted);
    expect(screen.getByText(/prompt-\d+\.txt/)).toBeInTheDocument();
    expect(submit).not.toHaveBeenCalled();
    errorLog.mockRestore();
  });

  it("cancels without modifying the draft or uploading", async () => {
    const { textarea, upload } = await setup("keep this draft");
    await pasteText("b".repeat(10001));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(textarea).toHaveValue("keep this draft");
    expect(upload).not.toHaveBeenCalled();
  });

  it("discards a pending choice when the conversation changes", async () => {
    const { rerender, textarea, upload } = await setup("keep this draft");
    await pasteText("b".repeat(10001));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    rerender(<Composer upload={upload} scopeKey="session-b" />);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(textarea).toHaveValue("keep this draft");
    expect(upload).not.toHaveBeenCalled();
  });

  it("uses plain text when the backend has no attachment support", async () => {
    const { rerender, textarea, upload } = await setup("draft");
    rerender(<Composer upload={upload} attachments={false} />);
    await selectDraft(5);
    const pasted = "b".repeat(10001);
    await pasteText(pasted);
    await waitFor(() => expect(textarea).toHaveValue(`draft${pasted}`));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("keeps native file paste on the existing attachment path", async () => {
    const { textarea, upload } = await setup("draft");
    const file = new File(["file content"], "notes.txt", {
      type: "text/plain",
    });
    fireEvent.paste(screen.getByRole("textbox"), {
      clipboardData: {
        files: [file],
        items: [],
        getData: () => "b".repeat(10001),
      },
    });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload.mock.calls[0][0].file).toBe(file);
    expect(textarea).toHaveValue("draft");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
