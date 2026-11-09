import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getAudioMode: vi.fn(),
  getTranscriptionProviderType: vi.fn(),
  getTranscriptionProviders: vi.fn(),
  getLocalWhisperStatus: vi.fn(),
  updateAudioMode: vi.fn(),
  updateTranscriptionProviderType: vi.fn(),
  updateTranscriptionProvider: vi.fn(),
}));
const app = vi.hoisted(() => ({
  selectedAgent: "agent-a",
  message: { success: vi.fn(), error: vi.fn() },
  t: (key: string) => key,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(() => ({ selectedAgent: app.selectedAgent }), {
    getState: () => ({ selectedAgent: app.selectedAgent }),
    subscribe: () => () => undefined,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: app.t }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: app.message }),
}));

vi.mock("../../../api", () => ({ default: api }));

import VoiceTranscriptionPage from ".";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

describe("VoiceTranscriptionPage initial load", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    app.selectedAgent = "agent-a";
    api.updateAudioMode.mockResolvedValue(undefined);
    api.updateTranscriptionProviderType.mockResolvedValue(undefined);
    api.updateTranscriptionProvider.mockResolvedValue(undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("blocks edits until retry restores the persisted settings", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let loadFails = true;
    api.getAudioMode.mockImplementation(async () => {
      if (loadFails) throw new Error("network down");
      return { audio_mode: "auto" };
    });
    api.getTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "local_whisper",
    });
    api.getTranscriptionProviders.mockResolvedValue({
      providers: [{ id: "p1", name: "Provider One", available: true }],
      configured_provider_id: "p1",
    });
    api.getLocalWhisperStatus.mockResolvedValue({
      available: true,
      ffmpeg_installed: true,
      whisper_installed: true,
    });

    render(<VoiceTranscriptionPage />);

    const retry = await screen.findByRole("button", { name: "common.retry" });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "voiceTranscription.loadFailed",
    );
    expect(
      screen.queryByRole("radiogroup", {
        name: "voiceTranscription.audioModeLabel",
      }),
    ).toBeNull();
    expect(
      screen.queryByRole("radiogroup", {
        name: "voiceTranscription.providerTypeLabel",
      }),
    ).toBeNull();
    expect(api.updateAudioMode).not.toHaveBeenCalled();
    expect(api.updateTranscriptionProviderType).not.toHaveBeenCalled();
    expect(api.updateTranscriptionProvider).not.toHaveBeenCalled();

    loadFails = false;
    fireEvent.click(retry);

    expect(
      await screen.findByRole("radio", {
        name: "voiceTranscription.modeAuto",
      }),
    ).toBeChecked();
    expect(
      screen.getByRole("radio", {
        name: "voiceTranscription.providerTypeLocalWhisper",
      }),
    ).toBeChecked();
    await waitFor(() => expect(api.getAudioMode).toHaveBeenCalledTimes(2));
    expect(api.getTranscriptionProviderType).toHaveBeenCalledTimes(2);
    expect(api.getTranscriptionProviders).toHaveBeenCalledTimes(2);
    expect(api.getLocalWhisperStatus).toHaveBeenCalledTimes(2);
    expect(api.updateAudioMode).not.toHaveBeenCalled();
    expect(api.updateTranscriptionProviderType).not.toHaveBeenCalled();
    expect(api.updateTranscriptionProvider).not.toHaveBeenCalled();
  });

  it("hides agent A controls while agent B settings are loading", async () => {
    const bMode = deferred<{ audio_mode: string }>();
    const bProviderType = deferred<{
      transcription_provider_type: string;
    }>();
    const bProviders = deferred<{
      providers: Array<{ id: string; name: string; available: boolean }>;
      configured_provider_id: string;
    }>();
    const bWhisper = deferred<{
      available: boolean;
      ffmpeg_installed: boolean;
      whisper_installed: boolean;
    }>();
    api.getAudioMode
      .mockResolvedValueOnce({ audio_mode: "auto" })
      .mockReturnValueOnce(bMode.promise);
    api.getTranscriptionProviderType
      .mockResolvedValueOnce({ transcription_provider_type: "disabled" })
      .mockReturnValueOnce(bProviderType.promise);
    api.getTranscriptionProviders
      .mockResolvedValueOnce({ providers: [], configured_provider_id: "" })
      .mockReturnValueOnce(bProviders.promise);
    api.getLocalWhisperStatus
      .mockResolvedValueOnce({
        available: true,
        ffmpeg_installed: true,
        whisper_installed: true,
      })
      .mockReturnValueOnce(bWhisper.promise);

    const { rerender } = render(<VoiceTranscriptionPage />);
    expect(
      await screen.findByRole("radio", {
        name: "voiceTranscription.modeAuto",
      }),
    ).toBeChecked();

    app.selectedAgent = "agent-b";
    rerender(<VoiceTranscriptionPage />);

    expect(
      screen.queryByRole("radiogroup", {
        name: "voiceTranscription.audioModeLabel",
      }),
    ).toBeNull();
    expect(api.updateAudioMode).not.toHaveBeenCalled();
    expect(api.updateTranscriptionProviderType).not.toHaveBeenCalled();
    expect(api.updateTranscriptionProvider).not.toHaveBeenCalled();

    bMode.resolve({ audio_mode: "native" });
    bProviderType.resolve({ transcription_provider_type: "local_whisper" });
    bProviders.resolve({ providers: [], configured_provider_id: "" });
    bWhisper.resolve({
      available: false,
      ffmpeg_installed: false,
      whisper_installed: false,
    });

    expect(
      await screen.findByRole("radio", {
        name: "voiceTranscription.modeNative",
      }),
    ).toBeChecked();
  });
});
