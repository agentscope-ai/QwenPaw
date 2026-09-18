import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deriveRealtimeVoiceStatus,
  useRealtimeVoice,
} from "./useRealtimeVoice";

interface ClientCallbacks {
  onEvent: (event: Record<string, unknown>) => void;
  onAudio: (audio: ArrayBuffer, sampleRate: number) => void;
  onClose: (event: CloseEvent) => void;
}

const mocks = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  createSession: vi.fn(),
  endSession: vi.fn(async () => ({ released: true })),
  sendAudio: vi.fn(() => true),
  clientClose: vi.fn(),
  clientStop: vi.fn(),
  clientCommitPending: vi.fn(() => true),
  clientSetAdmissionMode: vi.fn(() => true),
  captureSetMuted: vi.fn(),
  captureStart: vi.fn(),
  captureStop: vi.fn(async () => undefined),
  playbackClose: vi.fn(async () => undefined),
  playbackEnqueue: vi.fn(async () => undefined),
  playbackInterrupt: vi.fn(),
  playbackFeedback: vi.fn(),
  playbackBegin: vi.fn(),
  playbackSeal: vi.fn(),
  captureAudio: null as ((audio: ArrayBuffer) => void) | null,
  clientCallbacks: null as ClientCallbacks | null,
  deviceChange: null as (() => void) | null,
}));

vi.mock("../../api/modules/realtimeVoice", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../api/modules/realtimeVoice")
  >();
  return {
    ...actual,
    realtimeVoiceApi: {
      ...actual.realtimeVoiceApi,
      getCapabilities: mocks.getCapabilities,
      createSession: mocks.createSession,
      endSession: mocks.endSession,
    },
  };
});

vi.mock("./client", () => ({
  RealtimeVoiceClient: class {
    constructor(_bootstrap: unknown, callbacks: ClientCallbacks) {
      mocks.clientCallbacks = callbacks;
    }

    connect = vi.fn(async () => undefined);
    close = mocks.clientClose;
    stop = mocks.clientStop;
    commitPending = mocks.clientCommitPending;
    setAdmissionMode = mocks.clientSetAdmissionMode;
    interrupt = vi.fn();
    sendAudio = mocks.sendAudio;
    playbackFeedback = mocks.playbackFeedback;
  },
}));

vi.mock("./audioCapture", () => ({
  RealtimeAudioCapture: class {
    setMuted = mocks.captureSetMuted;
    stop = mocks.captureStop;
    start = mocks.captureStart;
  },
}));

vi.mock("./audioPlayback", () => ({
  RealtimeAudioPlayback: class {
    unlock = vi.fn(async () => undefined);
    enqueue = mocks.playbackEnqueue;
    interrupt = mocks.playbackInterrupt;
    close = mocks.playbackClose;
    begin = mocks.playbackBegin;
    seal = mocks.playbackSeal;
    isActive = () => true;
  },
}));

const capabilities = {
  protocol_version: 2,
  agent_id: "default",
  providers: [
    {
      id: "dashscope",
      label: "DashScope",
      models: [
        {
          id: "realtime-model",
          name: "Realtime Model",
          region: "beijing",
          realtime_model: "qwen-audio-3.0-realtime-flash",
          endpoint: null,
          voice: "Cherry",
          language: "zh",
          vad: {
            mode: "server_vad",
            threshold: 0.2,
            silence_duration_ms: 800,
          },
          continuation_grace_ms: 1200,
          max_history_turns: 20,
          max_session_seconds: 3600,
        },
      ],
      regions: [{ id: "beijing", label: "Beijing" }],
      vad_modes: ["server_vad"],
      speech_models: [
        { id: "qwen-audio-3.0-realtime-flash", label: "Qwen Audio" },
      ],
      media: {
        encoding: "pcm_s16le",
        input_sample_rate: 16000,
        output_sample_rate: 24000,
        channels: 1,
      },
      endpoint_override: { scheme: "wss", optional: true },
      supports_context_items: true,
      supports_manual_response: true,
      supports_output_cancel: true,
    },
  ],
  active_model: {
    provider_id: "dashscope",
    model: "realtime-model",
  },
  effective_model: {
    provider_id: "dashscope",
    model: "realtime-model",
    region: "beijing",
    realtime_model: "qwen-audio-3.0-realtime-flash",
    endpoint: null,
    voice: "Cherry",
    language: "zh",
    vad_mode: "server_vad",
    vad_threshold: 0.2,
    vad_silence_duration_ms: 800,
    continuation_grace_ms: 1200,
    max_history_turns: 20,
    max_session_seconds: 3600,
  },
  active_router_model: null,
  effective_router_model: {
    provider_id: "dashscope",
    model: "qwen3.7-plus",
  },
  credential_configured: true,
  configuration_error: null,
};

const bootstrap = {
  session_id: "live-1",
  agent_id: "default",
  chat_id: "chat-1",
  generation: 1,
  protocol_version: 2,
  media: capabilities.providers[0].media,
  ws_url: "/api/realtime-voice/sessions/live-1/stream",
  token: "token",
  expires_at: "2099-01-01T00:00:00Z",
  admission_mode: "queue" as const,
};

describe("useRealtimeVoice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.captureAudio = null;
    mocks.clientCallbacks = null;
    mocks.deviceChange = null;
    window.localStorage.clear();
    mocks.getCapabilities.mockResolvedValue(capabilities);
    mocks.createSession.mockResolvedValue(bootstrap);
    mocks.captureStart.mockImplementation(
      async (onAudio: (audio: ArrayBuffer) => void) => {
        mocks.captureAudio = onAudio;
      },
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: vi.fn(async () => []),
        addEventListener: vi.fn((type: string, listener: () => void) => {
          if (type === "devicechange") mocks.deviceChange = listener;
        }),
        removeEventListener: vi.fn(),
      },
    });
  });

  it("derives display status from independent voice lifecycle dimensions", () => {
    expect(
      deriveRealtimeVoiceStatus({
        connection: "ready",
        input: "listening",
        agent: "working",
        output: "idle",
      }),
    ).toBe("agent_working");
    expect(
      deriveRealtimeVoiceStatus({
        connection: "ready",
        input: "listening",
        agent: "working",
        output: "speaking",
      }),
    ).toBe("assistant_speaking");
  });

  it("buffers microphone frames until the upstream session is ready", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());

    await act(async () => result.current.start());
    expect(result.current.status).toBe("connecting");

    const captured = new ArrayBuffer(4);
    act(() => mocks.captureAudio?.(captured));
    expect(mocks.sendAudio).not.toHaveBeenCalled();

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "session.ready",
          generation: 1,
        }),
    );
    expect(result.current.status).toBe("listening");
    expect(mocks.sendAudio).toHaveBeenCalledWith(captured);

    unmount();
  });

  it("asks the mounted Chat to reconnect when a new Agent run starts", async () => {
    const onAgentRunStarted = vi.fn();
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted,
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "agent.run.started",
          generation: 1,
          event_id: "event-1",
          status: "started",
        }),
    );

    expect(onAgentRunStarted).toHaveBeenCalledOnce();
    unmount();
  });

  it("keeps Agent work visible between incremental speech segments", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({ type: "session.ready", generation: 1 });
      mocks.clientCallbacks?.onEvent({
        type: "agent.run.started",
        generation: 1,
        status: "started",
      });
    });
    expect(result.current.status).toBe("agent_working");
    expect(result.current.agentState).toBe("working");

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "output.begin",
          output_id: "out-1",
          generation: 1,
        }),
    );

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "output.started",
          generation: 1,
        }),
    );
    expect(result.current.status).toBe("assistant_speaking");

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "output.stopped",
          generation: 1,
        }),
    );
    expect(result.current.status).toBe("assistant_speaking");
    act(() => mocks.playbackBegin.mock.lastCall?.[1]("out-1", "drained"));
    expect(mocks.playbackFeedback).toHaveBeenLastCalledWith("out-1", "drained");
    expect(result.current.status).toBe("agent_working");

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "agent.run.completed",
          generation: 1,
        }),
    );
    expect(result.current.status).toBe("listening");
    unmount();
  });

  it("drops output audio outside the active response epoch", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    const first = new ArrayBuffer(4);
    act(() => mocks.clientCallbacks?.onAudio(first, 24000));
    expect(mocks.playbackEnqueue).not.toHaveBeenCalled();

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "output.started",
        generation: 1,
      });
      mocks.clientCallbacks?.onAudio(first, 24000);
    });
    expect(mocks.playbackEnqueue).toHaveBeenCalledOnce();

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "speech.started",
        generation: 1,
      });
      mocks.clientCallbacks?.onAudio(new ArrayBuffer(4), 24000);
    });
    expect(mocks.playbackInterrupt).toHaveBeenCalledOnce();
    expect(mocks.playbackEnqueue).toHaveBeenCalledOnce();

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "output.started",
        generation: 1,
      });
      mocks.clientCallbacks?.onAudio(new ArrayBuffer(4), 24000);
    });
    expect(mocks.playbackEnqueue).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("ignores lifecycle and playback state from an older Agent run", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({ type: "session.ready", generation: 1 });
      mocks.clientCallbacks?.onEvent({
        type: "agent.input.accepted",
        generation: 1,
        run_id: "run-new",
        status: "accepted",
      });
      mocks.clientCallbacks?.onEvent({
        type: "agent.run.completed",
        generation: 1,
        run_id: "run-old",
      });
      mocks.clientCallbacks?.onEvent({
        type: "output.started",
        generation: 1,
        run_id: "run-old",
      });
    });

    expect(result.current.status).toBe("agent_working");
    expect(result.current.outputState).toBe("idle");

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "agent.run.completed",
          generation: 1,
          run_id: "run-new",
        }),
    );
    expect(result.current.status).toBe("listening");
    unmount();
  });

  it("normalizes whitespace-only final text", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "input_transcript.final",
        generation: 1,
        event_id: "blank-user",
        text: "  \n ",
      });
    });

    expect(result.current.inputTranscript).toBe("");
    unmount();
  });

  it("refreshes the ordinary Chat after durable voice history changes", async () => {
    const onTimelineChanged = vi.fn();
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
        onTimelineChanged,
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "chat.history.updated",
        generation: 1,
        turn_id: "turn-1",
        messages: [{ id: "turn-1", role: "user" }],
      });
    });

    expect(onTimelineChanged).toHaveBeenCalledWith([
      { id: "turn-1", role: "user" },
    ]);
    unmount();
  });

  it("starts each spoken turn with a fresh live transcript", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "input_transcript.final",
        generation: 1,
        event_id: "first",
        text: "first turn",
      });
      mocks.clientCallbacks?.onEvent({
        type: "speech.started",
        generation: 1,
      });
      mocks.clientCallbacks?.onEvent({
        type: "input_transcript.partial",
        generation: 1,
        text: "second",
      });
    });

    expect(result.current.inputTranscript).toBe("second");
    unmount();
  });

  it("replaces revisable input previews without repeating their prefixes", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({ onChatCreated: vi.fn(), onAgentRunStarted: vi.fn() }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());
    act(() =>
      mocks.clientCallbacks?.onEvent({ type: "speech.started", generation: 1 }),
    );
    for (const text of ["今天", "今天天汽", "今天天气", "今天天气", "今天", ""]) {
      act(() =>
        mocks.clientCallbacks?.onEvent({
          type: "input_transcript.partial", generation: 1, text,
        }),
      );
      expect(result.current.inputTranscript).toBe(text);
    }
    unmount();
  });

  it("preserves pending speech across pauses and supports manual commit", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "input_turn.pending",
        generation: 1,
        state: "waiting",
        text: "请帮我计算一百二十三加上",
      });
      mocks.clientCallbacks?.onEvent({
        type: "speech.started",
        generation: 1,
      });
      mocks.clientCallbacks?.onEvent({
        type: "input_transcript.partial",
        generation: 1,
        text: "四百五十六",
      });
    });

    expect(result.current.inputTranscript).toBe(
      "请帮我计算一百二十三加上四百五十六",
    );
    act(() =>
      mocks.clientCallbacks?.onEvent({
        type: "input_transcript.partial",
        generation: 1,
        text: "四百五十七",
      }),
    );
    expect(result.current.inputTranscript).toBe(
      "请帮我计算一百二十三加上四百五十七",
    );
    expect(result.current.canCommitPending).toBe(true);
    act(() => result.current.commitPending());
    expect(mocks.clientCommitPending).toHaveBeenCalledOnce();

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "input_turn.committed",
        generation: 1,
      });
    });
    expect(result.current.canCommitPending).toBe(false);
    expect(result.current.inputTranscript).toBe("");
    unmount();
  });

  it("clears rejected input without closing the voice session", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "input_turn.pending",
        generation: 1,
        state: "needs_confirmation",
        text: "执行任务",
      });
      mocks.clientCallbacks?.onEvent({
        type: "input_turn.rejected",
        generation: 1,
        message: "The current Chat has too many pending admissions.",
      });
    });

    expect(result.current.canCommitPending).toBe(false);
    expect(result.current.inputTranscript).toBe("");
    expect(result.current.error).toContain("too many pending admissions");
    expect(mocks.clientClose).not.toHaveBeenCalled();
    unmount();
  });

  it("keeps the media session open after a recoverable provider error", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "session.ready",
        generation: 1,
      });
      mocks.clientCallbacks?.onEvent({
        type: "error",
        generation: 1,
        source: "provider",
        recoverable: true,
        message: "Realtime response was cancelled",
      });
    });

    expect(result.current.status).toBe("listening");
    expect(result.current.error).toContain("response was cancelled");
    expect(mocks.clientClose).not.toHaveBeenCalled();
    expect(mocks.createSession).toHaveBeenCalledOnce();

    unmount();
  });

  it("does not reconnect after the configured session duration", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());

    await act(async () => result.current.start());
    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "session.closed",
          generation: 1,
          reason: "max_duration",
        }),
    );

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toContain("configured session duration");
    expect(mocks.createSession).toHaveBeenCalledTimes(1);

    unmount();
  });

  it("applies mute and releases the client and media resources on stop", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "speech.started",
        generation: 1,
      });
    });
    expect(result.current.inputState).toBe("speaking");

    act(() => result.current.setMuted(true));
    expect(mocks.captureSetMuted).toHaveBeenLastCalledWith(true);
    expect(result.current.inputState).toBe("listening");

    act(() => {
      mocks.clientCallbacks?.onEvent({
        type: "speech.started",
        generation: 1,
      });
    });
    expect(result.current.inputState).toBe("listening");

    await act(async () => result.current.stop());
    expect(result.current.status).toBe("idle");
    expect(mocks.clientStop).toHaveBeenCalledOnce();
    expect(mocks.clientClose).toHaveBeenCalled();
    expect(mocks.captureStop).toHaveBeenCalled();
    expect(mocks.playbackClose).toHaveBeenCalledOnce();

    unmount();
  });

  it("can stop immediately while microphone startup is still pending", async () => {
    let finishCapture: (() => void) | undefined;
    mocks.captureStart.mockImplementationOnce(
      (onAudio: (audio: ArrayBuffer) => void) => {
        mocks.captureAudio = onAudio;
        return new Promise<void>((resolve) => {
          finishCapture = resolve;
        });
      },
    );
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());

    let starting: Promise<void> | undefined;
    act(() => {
      starting = result.current.start();
    });
    expect(result.current.status).toBe("connecting");
    await act(async () => result.current.stop());
    expect(result.current.status).toBe("idle");

    finishCapture?.();
    await act(async () => starting);
    expect(mocks.createSession).not.toHaveBeenCalled();
    expect(result.current.status).toBe("idle");
    unmount();
  });

  it("restarts capture when the selected microphone disappears", async () => {
    const microphone = {
      deviceId: "mic-1",
      groupId: "group-1",
      kind: "audioinput",
      label: "Test microphone",
      toJSON: () => ({}),
    } as MediaDeviceInfo;
    const enumerateDevices = vi.mocked(navigator.mediaDevices.enumerateDevices);
    enumerateDevices.mockResolvedValueOnce([microphone]);

    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());
    await waitFor(() => expect(result.current.inputDevices).toHaveLength(1));
    await act(async () => result.current.setInputDevice("mic-1"));

    enumerateDevices.mockResolvedValueOnce([]);
    await act(async () => mocks.deviceChange?.());
    await waitFor(() => expect(result.current.inputDeviceId).toBe(""));
    expect(mocks.captureStop.mock.calls.length).toBeGreaterThanOrEqual(2);

    unmount();
  });

  it("creates a fresh bootstrap after an established socket closes", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        chatId: "chat-1",
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());
    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "session.ready",
          generation: 1,
        }),
    );

    act(() => mocks.clientCallbacks?.onClose(new CloseEvent("close")));
    expect(result.current.status).toBe("reconnecting");
    await waitFor(() => expect(mocks.createSession).toHaveBeenCalledTimes(2), {
      timeout: 1500,
    });
    expect(mocks.createSession).toHaveBeenLastCalledWith({
      chat_id: "chat-1",
      previous_session_id: "live-1",
      admission_mode: "queue",
    });

    act(
      () =>
        mocks.clientCallbacks?.onEvent({
          type: "session.ready",
          generation: 1,
        }),
    );
    expect(result.current.status).toBe("listening");

    unmount();
  });

  it("does not reopen a session when stop wins an in-flight reconnect", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        chatId: "chat-1",
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    try {
      await waitFor(() => expect(result.current.capabilities).not.toBeNull());
      await act(async () => result.current.start());
      act(
        () =>
          mocks.clientCallbacks?.onEvent({
            type: "session.ready",
            generation: 1,
          }),
      );
      const oldCallbacks = mocks.clientCallbacks;
      let finishBootstrap: ((value: typeof bootstrap) => void) | undefined;
      mocks.createSession.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishBootstrap = resolve;
          }),
      );
      act(() => oldCallbacks?.onClose(new CloseEvent("close")));
      await waitFor(() => expect(finishBootstrap).toBeDefined(), {
        timeout: 1500,
      });
      await act(async () => result.current.stop());
      await act(
        async () =>
          finishBootstrap?.({
            ...bootstrap,
            session_id: "live-2",
            generation: 2,
          }),
      );
      expect(mocks.clientCallbacks).toBe(oldCallbacks);
      expect(result.current.status).toBe("idle");
      expect(mocks.endSession).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: "live-2" }),
      );
    } finally {
      unmount();
    }
  });

  it("ignores a late close from the previous socket after reconnect is ready", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        chatId: "chat-1",
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    try {
      await waitFor(() => expect(result.current.capabilities).not.toBeNull());
      await act(async () => result.current.start());
      act(
        () =>
          mocks.clientCallbacks?.onEvent({
            type: "session.ready",
            generation: 1,
          }),
      );
      const oldCallbacks = mocks.clientCallbacks;
      const oldAudio = mocks.captureAudio;
      await act(async () => result.current.stop());
      mocks.createSession.mockResolvedValueOnce({
        ...bootstrap,
        session_id: "live-2",
        generation: 2,
      });
      await act(async () => result.current.start());
      act(
        () =>
          mocks.clientCallbacks?.onEvent({
            type: "session.ready",
            generation: 2,
          }),
      );
      mocks.sendAudio.mockClear();
      act(() => {
        oldCallbacks?.onEvent({ type: "session.ready", generation: 1 });
        oldCallbacks?.onEvent({
          type: "error",
          message: "old error",
          recoverable: false,
        });
        oldCallbacks?.onEvent({
          type: "input_transcript.final",
          text: "old text",
        });
        oldAudio?.(new ArrayBuffer(640));
      });
      expect(mocks.sendAudio).not.toHaveBeenCalled();
      expect(result.current.error).toBeNull();
      expect(result.current.inputTranscript).toBe("");
      act(() => oldCallbacks?.onClose(new CloseEvent("close")));
      const pcm = new ArrayBuffer(640);
      act(() => mocks.captureAudio?.(pcm));
      expect(result.current.status).toBe("listening");
      expect(mocks.sendAudio).toHaveBeenCalledWith(pcm);
      act(() => {
        mocks.clientCallbacks?.onEvent({
          type: "output.started",
          generation: 2,
        });
        oldCallbacks?.onAudio(pcm, 24000);
      });
      expect(mocks.playbackEnqueue).not.toHaveBeenCalled();
      act(() => mocks.clientCallbacks?.onAudio(pcm, 24000));
      expect(mocks.playbackEnqueue).toHaveBeenCalledOnce();
    } finally {
      unmount();
    }
  });

  it("releases an initial bootstrap that arrives after stop", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        chatId: "chat-1",
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    let finish!: (value: typeof bootstrap) => void;
    mocks.createSession.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    let starting!: Promise<void>;
    act(() => {
      starting = result.current.start();
    });
    await waitFor(() => expect(finish).toBeDefined());
    await act(async () => result.current.stop());
    await act(async () => {
      finish(bootstrap);
      await starting;
    });
    expect(mocks.endSession).toHaveBeenCalledWith(bootstrap);
    expect(mocks.clientCallbacks).toBeNull();
    expect(result.current.status).toBe("idle");
    unmount();
  });

  it("does not restart an old microphone after stop and a new start", async () => {
    const { result, unmount } = renderHook(() =>
      useRealtimeVoice({
        chatId: "chat-1",
        onChatCreated: vi.fn(),
        onAgentRunStarted: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.capabilities).not.toBeNull());
    await act(async () => result.current.start());
    let finish!: (value: undefined) => void;
    mocks.captureStop.mockImplementationOnce(
      () =>
        new Promise<undefined>((resolve) => {
          finish = resolve;
        }),
    );
    let switching!: Promise<void>;
    act(() => {
      switching = result.current.setInputDevice("another-mic");
    });
    await act(async () => result.current.stop());
    await act(async () => result.current.start());
    const calls = mocks.captureStart.mock.calls.length;
    await act(async () => {
      finish(undefined);
      await switching;
    });
    expect(mocks.captureStart).toHaveBeenCalledTimes(calls);
    expect(result.current.error).toBeNull();
    unmount();
  });
});
