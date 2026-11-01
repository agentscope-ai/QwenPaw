import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  selectedAgent: "agent-a",
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

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(() => ({ selectedAgent: h.selectedAgent }), {
    getState: () => ({ selectedAgent: h.selectedAgent }),
  }),
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

import {
  type TranscriptionProvider,
  useVoiceTranscription,
} from "./useVoiceTranscription";

const PROVIDERS = [
  { id: "p1", name: "One", available: true },
  { id: "p2", name: "Two", available: false },
];
const WHISPER_STATUS = {
  available: true,
  ffmpeg_installed: true,
  whisper_installed: false,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

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
  h.selectedAgent = "agent-a";
  mockFetchOnce();
  h.updateAudioMode.mockResolvedValue(undefined);
  h.updateTranscriptionProviderType.mockResolvedValue(undefined);
  h.updateTranscriptionProvider.mockResolvedValue(undefined);
});

describe("useVoiceTranscription agent ownership", () => {
  it("keeps agent B settings when agent A resolves after B", async () => {
    const aMode = deferred<{ audio_mode: string }>();
    const aProviderType = deferred<{ transcription_provider_type: string }>();
    const aProviders = deferred<{
      providers: TranscriptionProvider[];
      configured_provider_id: string;
    }>();
    const aWhisper = deferred<typeof WHISPER_STATUS>();
    h.getAudioMode
      .mockReset()
      .mockReturnValueOnce(aMode.promise)
      .mockResolvedValueOnce({ audio_mode: "native" });
    h.getTranscriptionProviderType
      .mockReset()
      .mockReturnValueOnce(aProviderType.promise)
      .mockResolvedValueOnce({ transcription_provider_type: "local_whisper" });
    h.getTranscriptionProviders
      .mockReset()
      .mockReturnValueOnce(aProviders.promise)
      .mockResolvedValueOnce({
        providers: [{ id: "b-provider", name: "B", available: true }],
        configured_provider_id: "b-provider",
      });
    h.getLocalWhisperStatus
      .mockReset()
      .mockReturnValueOnce(aWhisper.promise)
      .mockResolvedValueOnce({
        available: false,
        ffmpeg_installed: false,
        whisper_installed: false,
      });

    const { result, rerender } = renderHook(() => useVoiceTranscription());
    act(() => {
      h.selectedAgent = "agent-b";
      rerender();
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.audioMode).toBe("native");
    expect(result.current.selectedProviderId).toBe("b-provider");

    await act(async () => {
      aMode.resolve({ audio_mode: "auto" });
      aProviderType.resolve({ transcription_provider_type: "whisper_api" });
      aProviders.resolve({
        providers: [{ id: "a-provider", name: "A", available: true }],
        configured_provider_id: "a-provider",
      });
      aWhisper.resolve(WHISPER_STATUS);
      await aMode.promise;
    });

    expect(result.current.audioMode).toBe("native");
    expect(result.current.providerType).toBe("local_whisper");
    expect(result.current.selectedProviderId).toBe("b-provider");
  });

  it("does not turn a late agent A rejection into agent B error state", async () => {
    const aMode = deferred<{ audio_mode: string }>();
    h.getAudioMode
      .mockReset()
      .mockReturnValueOnce(aMode.promise)
      .mockResolvedValueOnce({ audio_mode: "native" });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result, rerender } = renderHook(() => useVoiceTranscription());
    act(() => {
      h.selectedAgent = "agent-b";
      rerender();
    });
    await waitFor(() => expect(result.current.ready).toBe(true));

    await act(async () => {
      aMode.reject(new Error("agent A failed late"));
      await expect(aMode.promise).rejects.toThrow("agent A failed late");
    });

    expect(result.current.error).toBeNull();
    expect(result.current.audioMode).toBe("native");
    expect(h.message.error).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it("blocks all stale agent A save mutations and safely reloads agent B", async () => {
    mockFetchOnce({
      getTranscriptionProviderType: {
        transcription_provider_type: "whisper_api",
      },
    });
    const { result, rerender } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const staleAgentASave = result.current.handleSave;

    act(() => {
      h.selectedAgent = "agent-b";
      rerender();
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.clearAllMocks();

    await act(async () => {
      await staleAgentASave();
    });

    expect(h.updateAudioMode).not.toHaveBeenCalled();
    expect(h.updateTranscriptionProviderType).not.toHaveBeenCalled();
    expect(h.updateTranscriptionProvider).not.toHaveBeenCalled();
    expect(h.getAudioMode).toHaveBeenCalledTimes(1);
    expect(h.getTranscriptionProviderType).toHaveBeenCalledTimes(1);
    expect(h.getTranscriptionProviders).toHaveBeenCalledTimes(1);
    expect(h.getLocalWhisperStatus).toHaveBeenCalledTimes(1);
  });

  it("saves agent B values with agent B as the request target", async () => {
    const targets: Array<[string, string]> = [];
    h.updateAudioMode.mockImplementation(async (value: string) => {
      targets.push([h.selectedAgent, `audio:${value}`]);
    });
    h.updateTranscriptionProviderType.mockImplementation(
      async (value: string) => {
        targets.push([h.selectedAgent, `type:${value}`]);
      },
    );
    h.updateTranscriptionProvider.mockImplementation(async (value: string) => {
      targets.push([h.selectedAgent, `provider:${value}`]);
    });
    const { result, rerender } = renderHook(() => useVoiceTranscription());
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => {
      h.selectedAgent = "agent-b";
      rerender();
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => {
      result.current.setAudioMode("auto");
      result.current.setProviderType("whisper_api");
      result.current.setSelectedProviderId("b-provider");
    });
    await act(async () => {
      await result.current.handleSave();
    });

    expect(targets).toEqual([
      ["agent-b", "audio:auto"],
      ["agent-b", "type:whisper_api"],
      ["agent-b", "provider:b-provider"],
    ]);
  });
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
    expect(result.current.error).toEqual(new Error("down"));
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
      "error",
      "fetchSettings",
      "handleSave",
      "isLocalWhisper",
      "isWhisperApi",
      "loading",
      "localWhisperStatus",
      "providerType",
      "ready",
      "saving",
      "selectedProviderId",
      "setAudioMode",
      "setProviderType",
      "setSelectedProviderId",
      "showProviderSection",
    ]);
  });
});
