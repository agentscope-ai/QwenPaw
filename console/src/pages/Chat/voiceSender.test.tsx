import { createRef } from "react";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { findVoiceSender } from "./voiceSender";
import WhisperSpeechButton from "./components/WhisperSpeechButton";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { setTextareaValue } from "./utils";
vi.mock("@agentscope-ai/icons", () => ({
  SparkMicLine: () => <span>mic</span>,
}));
beforeEach(() => {
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "a", platform_role: "member" } as never,
  });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [{ id: "a", enabled: true, access_role: "user" }] as never,
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("uploads from nested SDK sender-prefix and appends only to its own current draft without submitting", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ text: "recognized" }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  const root = createRef<HTMLDivElement>();
  const submit = vi.fn();
  const getSender = (anchor?: HTMLElement | null) =>
    findVoiceSender(root.current, anchor ?? null);
  const onTranscription = (text: string, sender?: HTMLTextAreaElement) => {
    if (sender) setTextareaValue(sender, `${sender.value} ${text}`);
  };
  const view = render(
    <div ref={root} onSubmit={submit}>
      {["first", "second"].map((id) => (
        <div key={id} data-sender-root="true" className="ant-sender">
          <div className="ant-sender-content">
            <textarea aria-label={id} defaultValue={`${id} draft`} />
            <div className="ant-sender-content-bottom">
              <div className="ant-sender-prefix">
                <div className="ant-flex">
                  <WhisperSpeechButton
                    getSender={getSender}
                    onTranscription={onTranscription}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>,
  );
  fireEvent.change(view.getAllByTestId("voice-upload-input")[1], {
    target: {
      files: [new File(["sound"], "sample.wav", { type: "audio/wav" })],
    },
  });
  await waitFor(() =>
    expect((view.getByLabelText("second") as HTMLTextAreaElement).value).toBe(
      "second draft recognized",
    ),
  );
  expect((view.getByLabelText("first") as HTMLTextAreaElement).value).toBe(
    "first draft",
  );
  expect(submit).not.toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][0]).toContain("/workspace/transcribe");
});
it("rejects another Chat or a sender root outside the owning Chat", () => {
  const outer = document.createElement("div");
  outer.setAttribute("data-sender-root", "true");
  outer.className = "sender";
  outer.innerHTML =
    '<textarea></textarea><div id="chat"><span id="anchor"></span></div>';
  const root = outer.querySelector<HTMLElement>("#chat")!;
  const anchor = outer.querySelector<HTMLElement>("#anchor")!;
  expect(findVoiceSender(root, anchor)).toBeNull();
  expect(findVoiceSender(document.createElement("div"), anchor)).toBeNull();
});
