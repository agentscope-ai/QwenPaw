import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RealtimeVoiceStatus } from "./useRealtimeVoice";
import {
  RealtimeVoiceControls,
  type RealtimeVoiceController,
} from "./RealtimeVoicePanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const start = vi.fn();
const stop = vi.fn();
const setMuted = vi.fn();
const commitPending = vi.fn(() => true);
const setAdmissionMode = vi.fn();

function voiceState(status: RealtimeVoiceStatus): RealtimeVoiceController {
  const capabilities = {
    protocol_version: 2,
    agent_id: "default",
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
      presentation_capacity: 32,
      playback_timeout_seconds: 90,
      max_history_turns: 20,
      max_session_seconds: 3600,
    },
    active_router_model: null,
    effective_router_model: {
      provider_id: "dashscope",
      model: "qwen3.7-plus",
    },
    providers: [],
    credential_configured: true,
    configuration_error: null,
  };
  return {
    capabilities,
    readyToStart: true,
    status,
    connectionState:
      status === "idle" ? "idle" : status === "error" ? "error" : "ready",
    inputState: status === "user_speaking" ? "speaking" : "listening",
    agentState: status === "agent_working" ? "working" : "idle",
    outputState: status === "assistant_speaking" ? "speaking" : "idle",
    muted: false,
    inputDevices: [],
    inputDeviceId: "",
    admissionMode: "queue",
    inputTranscript: "",
    pendingInputState: "idle",
    pendingInputError: null,
    canCommitPending: false,
    assistantTranscript: "",
    error: null,
    conflict: null,
    start,
    confirmSwitch: vi.fn(),
    cancelSwitch: vi.fn(),
    stop,
    setMuted,
    setInputDevice: vi.fn(),
    interrupt: vi.fn(),
    observeAgentRun: vi.fn(() => true),
    commitPending,
    setAdmissionMode,
    reloadCapabilities: vi.fn(async () => capabilities),
  };
}

function renderInRouter(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("Realtime Voice Chat surfaces", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps live controls next to the keyboard composer", () => {
    renderInRouter(<RealtimeVoiceControls voice={voiceState("listening")} />);

    expect(screen.getByText("realtimeVoice.liveHint")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: /realtimeVoice\.mute/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "realtimeVoice.stop" }));
    expect(setMuted).toHaveBeenCalledWith(true);
    expect(stop).toHaveBeenCalledOnce();
  });

  it("keeps the full live transcript available alongside all active controls", () => {
    const voice = voiceState("user_speaking");
    voice.inputTranscript = "继续处理刚才的任务".repeat(20);
    voice.canCommitPending = true;
    voice.inputDevices = [
      {
        deviceId: "microphone",
        label: "USB microphone",
        groupId: "usb",
        kind: "audioinput",
        toJSON: () => ({}),
      },
    ];
    renderInRouter(<RealtimeVoiceControls voice={voice} />);

    expect(
      screen.getByTitle(`realtimeVoice.you ${voice.inputTranscript}`),
    ).toBeVisible();
    expect(
      screen.getByRole("combobox", { name: "realtimeVoice.microphone" }),
    ).toBeInTheDocument();
    expect(screen.getByText("realtimeVoice.defaultMicrophone")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "realtimeVoice.commitPending" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "realtimeVoice.stop" }),
    ).toBeVisible();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("does not present committed user speech as the agent's live status", () => {
    const voice = voiceState("agent_working");
    voice.inputTranscript = "已经提交的上一条请求";
    renderInRouter(<RealtimeVoiceControls voice={voice} />);

    expect(
      screen.queryByTitle(
        `realtimeVoice.you ${voice.inputTranscript}`,
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText("realtimeVoice.liveHint")).toBeVisible();
  });

  it("does not invite speech before the connection is ready", () => {
    renderInRouter(<RealtimeVoiceControls voice={voiceState("connecting")} />);

    expect(screen.getByText("realtimeVoice.connectingHint")).toBeVisible();
    expect(
      screen.queryByText("realtimeVoice.liveHint"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "realtimeVoice.stop" }));
    expect(stop).toHaveBeenCalledOnce();
  });

  it("offers explicit submission when accumulated speech is pending", () => {
    const voice = voiceState("listening");
    voice.canCommitPending = true;
    voice.pendingInputState = "needs_confirmation";
    voice.inputTranscript = "尚未自动提交的请求";
    renderInRouter(<RealtimeVoiceControls voice={voice} />);

    fireEvent.click(
      screen.getByRole("button", { name: "realtimeVoice.commitPending" }),
    );
    expect(commitPending).toHaveBeenCalledOnce();
  });

  it("presents idle resume as the primary Voice action", () => {
    renderInRouter(<RealtimeVoiceControls voice={voiceState("idle")} />);

    expect(screen.getByText("realtimeVoice.resumeHint")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "realtimeVoice.resume" }),
    );
    expect(start).toHaveBeenCalledOnce();
  });

  it("does not start Voice when the current tab cannot own the Chat", () => {
    renderInRouter(
      <RealtimeVoiceControls voice={voiceState("idle")} canStart={false} />,
    );

    const resume = screen.getByRole("button", {
      name: "realtimeVoice.resume",
    });
    expect(resume).toBeDisabled();
    fireEvent.click(resume);
    expect(start).not.toHaveBeenCalled();
  });
});
