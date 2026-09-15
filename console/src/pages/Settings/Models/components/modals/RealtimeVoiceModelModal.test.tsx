import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProviderInfo } from "../../../../../api/types";
import { providerApi } from "../../../../../api/modules/provider";
import { RealtimeVoiceModelModal } from "./RealtimeVoiceModelModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../../../api/modules/provider", () => ({
  providerApi: { configureRealtimeVoiceModel: vi.fn() },
}));
vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
  }),
}));

const provider = {
  id: "dashscope",
  name: "DashScope",
  realtime_models: [
    {
      id: "qwen-realtime",
      name: "Qwen Realtime",
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
      presentation_capacity: 32,
      playback_timeout_seconds: 90,
      max_history_turns: 20,
      max_session_seconds: 3600,
    },
  ],
  realtime_voice: {
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
} as unknown as ProviderInfo;

describe("RealtimeVoiceModelModal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("persists the configured native speech model", async () => {
    vi.mocked(providerApi.configureRealtimeVoiceModel).mockResolvedValue(
      provider.realtime_models[0],
    );
    render(
      <RealtimeVoiceModelModal
        provider={provider}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    expect(
      await screen.findByLabelText("realtimeVoice.speechModel"),
    ).toBeInTheDocument();
    expect(screen.getByText("realtimeVoice.languageHelp")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("realtimeVoice.language"), {
      target: { value: "en-US" },
    });

    fireEvent.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => {
      expect(providerApi.configureRealtimeVoiceModel).toHaveBeenCalledWith(
        "dashscope",
        "qwen-realtime",
        expect.objectContaining({
          realtime_model: "qwen-audio-3.0-realtime-flash",
          language: "en-US",
          max_history_turns: 20,
          continuation_grace_ms: 1200,
        }),
      );
    });
  });
});
