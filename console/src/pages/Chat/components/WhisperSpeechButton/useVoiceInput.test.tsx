import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVoiceInput, type VoiceInputProps } from "./useVoiceInput";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { clearAccessSession } from "@/api/authSession";
import { useUploadLimitStore } from "@/stores/uploadLimitStore";
import { message } from "antd";

const response = (text = "recognized") =>
  new Response(JSON.stringify({ text }), {
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
class Recorder {
  static instances: Recorder[] = [];
  static isTypeSupported = (type: string) => type === "audio/mp4";
  state = "inactive";
  mimeType = "audio/mp4";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    Recorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({
      data: new Blob(["sound"], { type: this.mimeType }),
    });
    this.onstop?.();
  }
}
beforeEach(() => {
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "alice", platform_role: "member" } as never,
  });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [
      { id: "a", enabled: true, access_role: "user" },
      { id: "b", enabled: true, access_role: "user" },
    ] as never,
  });
  useUploadLimitStore.setState({ uploadMaxSizeMb: 10 });
  Recorder.instances = [];
  vi.stubGlobal("MediaRecorder", Recorder);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("records for an Agent user using an explicit mp4 filename and conversation", async () => {
  const stop = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: async () => ({ getTracks: () => [{ stop }] }),
    },
  });
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(response()));
  vi.stubGlobal("fetch", fetch);
  const onTranscription = vi.fn();
  const { result } = renderHook(() =>
    useVoiceInput({ onTranscription, conversationId: "c" }),
  );
  await act(async () => {
    await result.current.toggleRecording();
  });
  expect(result.current.phase).toBe("recording");
  await act(async () => {
    await result.current.toggleRecording();
  });
  expect(onTranscription).toHaveBeenCalledWith("recognized", undefined);
  expect(stop).toHaveBeenCalledOnce();
  const [url, options] = fetch.mock.calls[0];
  expect(url).toContain("/workspace/transcribe");
  expect(options.headers.get("X-Agent-Id")).toBe("a");
  expect(options.body.get("conversation_id")).toBe("c");
  expect(options.body.get("file").name).toBe("recording.mp4");
  expect(options.body.get("file").type).toBe("audio/mp4");
});
const changes = [
  "actor",
  "generation",
  "agent",
  "conversation",
  "local conversation",
  "readonly",
  "unmount",
] as const;
it.each(changes)("closes late microphone after %s changes", async (change) => {
  const pending = deferred<MediaStream>();
  const stop = vi.fn();
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("navigator", {
    mediaDevices: { getUserMedia: () => pending.promise },
  });
  let props: VoiceInputProps = {
    onTranscription: vi.fn(),
    conversationId: "c",
    contextKey: "local-1",
  };
  const view = renderHook(() => useVoiceInput(props));
  act(() => {
    void view.result.current.toggleRecording();
  });
  act(() => {
    if (change === "actor")
      useAuthStore.setState({
        user: { id: "bob", platform_role: "member" } as never,
      });
    if (change === "generation") clearAccessSession();
    if (change === "agent") useAgentStore.setState({ selectedAgent: "b" });
    if (change === "conversation") props = { ...props, conversationId: "d" };
    if (change === "local conversation")
      props = { ...props, contextKey: "local-2" };
    if (change === "readonly") props = { ...props, disabled: true };
    if (change === "unmount") view.unmount();
    else view.rerender();
  });
  await act(async () =>
    pending.resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream),
  );
  expect(stop).toHaveBeenCalledOnce();
  expect(Recorder.instances).toHaveLength(0);
  expect(fetch).not.toHaveBeenCalled();
});
it.each(changes)(
  "aborts pending uploaded audio and ignores its result after %s changes",
  async (change) => {
    const pending = deferred<Response>();
    const fetch = vi.fn(() => pending.promise);
    vi.stubGlobal("fetch", fetch);
    const onTranscription = vi.fn();
    let props: VoiceInputProps = {
      onTranscription,
      conversationId: "c",
      contextKey: "local-1",
    };
    const view = renderHook(() => useVoiceInput(props));
    act(() =>
      view.result.current.upload(
        new File(["sound"], "sample.wav", { type: "audio/wav" }),
      ),
    );
    act(() => {
      if (change === "actor")
        useAuthStore.setState({
          user: { id: "bob", platform_role: "member" } as never,
        });
      if (change === "generation") clearAccessSession();
      if (change === "agent") useAgentStore.setState({ selectedAgent: "b" });
      if (change === "conversation") props = { ...props, conversationId: "d" };
      if (change === "local conversation")
        props = { ...props, contextKey: "local-2" };
      if (change === "readonly") props = { ...props, disabled: true };
      if (change === "unmount") view.unmount();
      else view.rerender();
    });
    expect((fetch.mock.calls[0] as any)[1].signal.aborted).toBe(true);
    await act(async () => pending.resolve(response()));
    expect(onTranscription).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledOnce();
  },
);
it("cancels recording before onstop and never submits old audio under the next identity", async () => {
  const stop = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: async () => ({ getTracks: () => [{ stop }] }),
    },
  });
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() =>
    useVoiceInput({ onTranscription: vi.fn() }),
  );
  await act(async () => {
    await result.current.toggleRecording();
  });
  const lateStop = Recorder.instances[0].onstop;
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () => lateStop?.());
  expect(stop).toHaveBeenCalledOnce();
  expect(fetch).not.toHaveBeenCalled();
  expect(Recorder.instances[0].state).toBe("inactive");
});
it("returns only the captured connected sender and discards replacement senders", async () => {
  const first = document.createElement("textarea");
  const second = document.createElement("textarea");
  document.body.append(first, second);
  const pending = deferred<Response>();
  const fetch = vi.fn(() => pending.promise);
  vi.stubGlobal("fetch", fetch);
  let sender = second;
  const onTranscription = vi.fn();
  const { result } = renderHook(() =>
    useVoiceInput({ onTranscription, getSender: () => sender }),
  );
  act(() => result.current.upload(new File(["x"], "x.wav")));
  sender = first;
  await act(async () => pending.resolve(response()));
  expect(onTranscription).not.toHaveBeenCalled();
  first.remove();
  second.remove();
});
it("explicitly cancels a request without returning text or showing an error", async () => {
  const pending = deferred<Response>();
  const fetch = vi.fn(() => pending.promise);
  vi.stubGlobal("fetch", fetch);
  const error = vi.spyOn(message, "error");
  const onTranscription = vi.fn();
  const { result } = renderHook(() => useVoiceInput({ onTranscription }));
  act(() => result.current.upload(new File(["x"], "x.wav")));
  act(() => result.current.cancel());
  await act(async () => pending.resolve(response()));
  expect(onTranscription).not.toHaveBeenCalled();
  expect(error).not.toHaveBeenCalled();
});
it.each(["empty", "too large"])(
  "rejects %s audio before the request",
  async (kind) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const error = vi.spyOn(message, "error");
    useUploadLimitStore.setState({ uploadMaxSizeMb: 0.000001 });
    const { result } = renderHook(() =>
      useVoiceInput({ onTranscription: vi.fn() }),
    );
    act(() =>
      result.current.upload(
        new File([kind === "empty" ? "" : "12345"], "x.wav"),
      ),
    );
    await waitFor(() => expect(error).toHaveBeenCalled());
    expect(fetch).not.toHaveBeenCalled();
  },
);
it("does not expose a raw upstream error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "UPSTREAM_FAILURE",
            message: "private-key https://private",
          },
        }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  const error = vi.spyOn(message, "error");
  const onTranscription = vi.fn();
  const { result } = renderHook(() => useVoiceInput({ onTranscription }));
  act(() => result.current.upload(new File(["x"], "x.wav")));
  await waitFor(() => expect(error).toHaveBeenCalled());
  expect(JSON.stringify(error.mock.calls)).not.toMatch(/private-key|https:/);
  expect(onTranscription).not.toHaveBeenCalled();
});

it("returns to idle if the sender is replaced while microphone permission is pending", async () => {
  const first = document.createElement("textarea");
  const second = document.createElement("textarea");
  document.body.append(first, second);
  let sender = first;
  const pending = deferred<MediaStream>();
  const stop = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: { getUserMedia: () => pending.promise },
  });
  const { result } = renderHook(() =>
    useVoiceInput({ onTranscription: vi.fn(), getSender: () => sender }),
  );
  act(() => {
    void result.current.toggleRecording();
  });
  sender = second;
  await act(async () =>
    pending.resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream),
  );
  expect(stop).toHaveBeenCalledOnce();
  expect(result.current.phase).toBe("idle");
  first.remove();
  second.remove();
});
