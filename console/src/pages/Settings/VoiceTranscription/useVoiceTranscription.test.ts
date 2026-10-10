import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  t: (key: string) => key,
  message: { success: vi.fn(), error: vi.fn() },
  getAudioMode: vi.fn(),
  getTranscriptionProviderType: vi.fn(),
  getTranscriptionProviders: vi.fn(),
  getLocalWhisperStatus: vi.fn(),
  updateAudioMode: vi.fn(),
  updateTranscriptionProviderType: vi.fn(),
  updateTranscriptionProvider: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.t }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));

vi.mock("../../../api", () => ({
  default: {
    getAudioMode: h.getAudioMode,
    getTranscriptionProviderType: h.getTranscriptionProviderType,
    getTranscriptionProviders: h.getTranscriptionProviders,
    getLocalWhisperStatus: h.getLocalWhisperStatus,
    updateAudioMode: h.updateAudioMode,
    updateTranscriptionProviderType: h.updateTranscriptionProviderType,
    updateTranscriptionProvider: h.updateTranscriptionProvider,
  },
}));

import { useVoiceTranscription } from "./useVoiceTranscription";

const PROVIDERS = [
  { id: "p1", name: "One", available: true },
  { id: "p2", name: "Two", available: false },
];
const WHISPER_STATUS = {
  available: true,
  ffmpeg_installed: true,
  whisper_installed: false,
};

function mockFetchOnce(overrides: Record<string, unknown> = {}) {
  h.getAudioMode.mockResolvedValue({ audio_mode: "auto" });
  h.getTranscriptionProviderType.mockResolvedValue({
    transcription_provider_type: "disabled",
  });
  h.getTranscriptionProviders.mockResolvedValue({
    providers: PROVIDERS,
    configured_provider_id: "p1",
  });
  h.getLocalWhisperStatus.mockResolvedValue(WHISPER_STATUS);
  for (const [k, v] of Object.entries(overrides)) {
    (
      h as unknown as Record<
        string,
        { mockResolvedValue: (v: unknown) => void }
      >
    )[k].mockResolvedValue(v);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchOnce();
  h.updateAudioMode.mockResolvedValue(undefined);
  h.updateTranscriptionProviderType.mockResolvedValue(undefined);
  h.updateTranscriptionProvider.mockResolvedValue(undefined);
});

describe("useVoiceTranscription initial load", () => {
  it("starts loading and then exposes every fetched setting", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.audioMode).toBe("auto");
    expect(result.current.providerType).toBe("disabled");
    expect(result.current.selectedProviderId).toBe("p1");
    expect(result.current.localWhisperStatus).toEqual(WHISPER_STATUS);
  });

  it("fetches all four settings in parallel on mount", async () => {
    renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(h.getAudioMode).toHaveBeenCalledTimes(1));
    expect(h.getTranscriptionProviderType).toHaveBeenCalledTimes(1);
    expect(h.getTranscriptionProviders).toHaveBeenCalledTimes(1);
    expect(h.getLocalWhisperStatus).toHaveBeenCalledTimes(1);
  });

  it("applies the documented defaults when the server omits fields", async () => {
    mockFetchOnce({
      getAudioMode: {},
      getTranscriptionProviderType: {},
      getTranscriptionProviders: {},
    });
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.audioMode).toBe("auto");
    expect(result.current.providerType).toBe("disabled");
    expect(result.current.selectedProviderId).toBe("");
  });

  it("reports a load failure and still leaves the loading flag false", async () => {
    h.getAudioMode.mockRejectedValue(new Error("down"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(h.message.error).toHaveBeenCalledWith(
      "voiceTranscription.loadFailed",
    );
    expect(errorSpy).toHaveBeenCalledWith(
      "Failed to load voice transcription settings:",
      expect.any(Error),
    );
    errorSpy.mockRestore();
  });

  it("leaves the providers empty when the fetch rejects", async () => {
    h.getTranscriptionProviders.mockRejectedValue(new Error("nope"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.availableProviders).toEqual([]);
  });
});

describe("useVoiceTranscription derived state", () => {
  it("only lists providers the backend marks available", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.availableProviders).toEqual([PROVIDERS[0]]);
  });

  it("hides the provider section in native audio mode", async () => {
    mockFetchOnce({ getAudioMode: { audio_mode: "native" } });
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.showProviderSection).toBe(false);
  });

  it("shows the provider section for any non-native audio mode", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.showProviderSection).toBe(true);
  });

  it("flags local whisper and whisper api provider types", async () => {
    mockFetchOnce({
      getTranscriptionProviderType: {
        transcription_provider_type: "local_whisper",
      },
    });
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.isLocalWhisper).toBe(true));
    expect(result.current.isWhisperApi).toBe(false);
  });

  it("flags whisper api and not local whisper", async () => {
    mockFetchOnce({
      getTranscriptionProviderType: {
        transcription_provider_type: "whisper_api",
      },
    });
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.isWhisperApi).toBe(true));
    expect(result.current.isLocalWhisper).toBe(false);
  });
});

describe("useVoiceTranscription setters", () => {
  it("exposes working setters for the three editable fields", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => {
      result.current.setAudioMode("native");
      result.current.setProviderType("whisper_api");
      result.current.setSelectedProviderId("p2");
    });
    expect(result.current.audioMode).toBe("native");
    expect(result.current.providerType).toBe("whisper_api");
    expect(result.current.selectedProviderId).toBe("p2");
  });

  it("re-fetches when fetchSettings is called again", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.fetchSettings();
    });
    expect(h.getAudioMode).toHaveBeenCalledTimes(2);
  });
});

describe("useVoiceTranscription handleSave", () => {
  it("saves the audio mode and provider type without the provider id", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleSave();
    });
    expect(h.updateAudioMode).toHaveBeenCalledWith("auto");
    expect(h.updateTranscriptionProviderType).toHaveBeenCalledWith("disabled");
    expect(h.updateTranscriptionProvider).not.toHaveBeenCalled();
    expect(h.message.success).toHaveBeenCalledWith(
      "voiceTranscription.saveSuccess",
    );
    expect(result.current.saving).toBe(false);
  });

  it("also persists the selected provider for the whisper_api type", async () => {
    mockFetchOnce({
      getTranscriptionProviderType: {
        transcription_provider_type: "whisper_api",
      },
    });
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleSave();
    });
    expect(h.updateTranscriptionProvider).toHaveBeenCalledWith("p1");
  });

  it("does not persist a provider id for the local_whisper type", async () => {
    mockFetchOnce({
      getTranscriptionProviderType: {
        transcription_provider_type: "local_whisper",
      },
    });
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleSave();
    });
    expect(h.updateTranscriptionProvider).not.toHaveBeenCalled();
  });

  it("saves the values the user changed, not the fetched ones", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => {
      result.current.setAudioMode("native");
    });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(h.updateAudioMode).toHaveBeenCalledWith("native");
  });

  it("reports a save failure and clears the saving flag", async () => {
    h.updateAudioMode.mockRejectedValue(new Error("nope"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleSave();
    });
    expect(h.message.error).toHaveBeenCalledWith(
      "voiceTranscription.saveFailed",
    );
    expect(h.message.success).not.toHaveBeenCalled();
    expect(result.current.saving).toBe(false);
    errorSpy.mockRestore();
  });

  it("sets the saving flag while the request is in flight", async () => {
    let release!: () => void;
    h.updateAudioMode.mockReturnValue(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.handleSave();
    });
    expect(result.current.saving).toBe(true);
    await act(async () => {
      release();
      await pending;
    });
    expect(result.current.saving).toBe(false);
  });

  it("reports the state surface the component consumes", async () => {
    const { result } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(Object.keys(result.current).sort()).toEqual([
      "audioMode",
      "availableProviders",
      "fetchSettings",
      "handleSave",
      "isLocalWhisper",
      "isWhisperApi",
      "loading",
      "localWhisperStatus",
      "providerType",
      "saving",
      "selectedProviderId",
      "setAudioMode",
      "setProviderType",
      "setSelectedProviderId",
      "showProviderSection",
    ]);
  });
});
