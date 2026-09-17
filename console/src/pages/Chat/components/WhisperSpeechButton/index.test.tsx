import {
  act,
  cleanup,
  render,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WhisperSpeechButton, { type WhisperSpeechButtonRef } from "./index";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";

vi.mock("@agentscope-ai/icons", () => ({
  SparkMicLine: () => <span>mic</span>,
}));

beforeEach(() => {
  useAuthStore.setState({ mode: "legacy", phase: "disabled", user: null });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [{ id: "a", enabled: true, access_role: "user" }] as never,
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("closes a late microphone stream after unmount without creating a recorder or uploading", async () => {
  let finish!: (s: MediaStream) => void;
  const stop = vi.fn();
  const Recorder = vi.fn();
  const fetch = vi.fn();
  Object.assign(Recorder, { isTypeSupported: () => true });
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: () =>
        new Promise<MediaStream>((r) => {
          finish = r;
        }),
    },
  });
  const ref = createRef<WhisperSpeechButtonRef>();
  const view = render(
    <WhisperSpeechButton ref={ref} onTranscription={vi.fn()} />,
  );
  act(() => ref.current!.toggleRecording());
  view.unmount();
  await act(async () =>
    finish({ getTracks: () => [{ stop }] } as unknown as MediaStream),
  );
  expect(stop).toHaveBeenCalledOnce();
  expect(Recorder).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});
it("cannot start recording through the imperative shortcut when disabled", () => {
  const getUserMedia = vi.fn();
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  const ref = createRef<WhisperSpeechButtonRef>();
  render(<WhisperSpeechButton ref={ref} disabled onTranscription={vi.fn()} />);
  act(() => ref.current!.toggleRecording());
  expect(getUserMedia).not.toHaveBeenCalled();
});

it("binds an upload to the sender containing the clicked voice control", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ text: "words" }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  const onTranscription = vi.fn();
  const getSender = (anchor?: HTMLElement | null) =>
    anchor?.closest(".sender")?.querySelector("textarea") ?? null;
  const view = render(
    <>
      <div className="sender">
        <textarea aria-label="first" />
        <WhisperSpeechButton
          getSender={getSender}
          onTranscription={onTranscription}
        />
      </div>
      <div className="sender">
        <textarea aria-label="second" />
        <WhisperSpeechButton
          getSender={getSender}
          onTranscription={onTranscription}
        />
      </div>
    </>,
  );
  fireEvent.change(view.getAllByTestId("voice-upload-input")[1], {
    target: { files: [new File(["audio"], "sample.wav")] },
  });
  await waitFor(() =>
    expect(onTranscription).toHaveBeenCalledWith(
      "words",
      view.getByLabelText("second"),
    ),
  );
  expect(fetch).toHaveBeenCalledOnce();
});
