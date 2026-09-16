import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { App } from "antd";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVoiceTranscription } from "./useVoiceTranscription";
import { useAuthStore } from "@/stores/authStore";

const settings = {
  audio_mode: "auto",
  transcription_provider_type: "whisper_api",
  transcription_provider_id: "safe",
  transcription_model: "asr",
  transcription_local_model: "base",
};
const dto = {
  settings,
  providers: [{ id: "safe", name: "Safe", available: true }],
  local_status: {
    available: false,
    ffmpeg_installed: false,
    whisper_installed: false,
  },
  local_models: ["base", "tiny"],
};
const response = (data: unknown) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <App>{children}</App>
);
beforeEach(() =>
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "admin", platform_role: "admin" } as never,
  }),
);
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("loads the joint safe DTO and saves all five fields atomically", async () => {
  const fetch = vi.fn().mockResolvedValue(response(dto));
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.selectedProviderId).toBe("safe");
  await act(async () => {
    await result.current.handleSave();
  });
  const calls = fetch.mock.calls.filter(
    ([, options]) => options.method === "PUT",
  );
  expect(calls).toHaveLength(1);
  expect(calls[0][0]).toContain("/workspace/voice-transcription");
  expect(JSON.parse(calls[0][1].body)).toEqual(settings);
});
it("does not save defaults after loading fails", async () => {
  const fetch = vi.fn().mockRejectedValue(new Error("private upstream"));
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => {
    await result.current.handleSave();
  });
  expect(
    fetch.mock.calls.filter(([, options]) => options.method === "PUT"),
  ).toHaveLength(0);
});
it("does not request infrastructure configuration for a member", async () => {
  useAuthStore.setState({
    user: { id: "member", platform_role: "member" } as never,
  });
  const fetch = vi.fn().mockResolvedValue(response(dto));
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  await act(async () => {
    await result.current.handleSave();
  });
  expect(fetch).not.toHaveBeenCalled();
});
it("discards late administrator configuration after switching identity", async () => {
  const finishes: ((r: Response) => void)[] = [];
  const fetch = vi.fn(
    () =>
      new Promise<Response>((r) => {
        finishes.push(r);
      }),
  );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  act(() =>
    useAuthStore.setState({
      user: { id: "member", platform_role: "member" } as never,
    }),
  );
  await act(async () => finishes.forEach((finish) => finish(response(dto))));
  expect(result.current.selectedProviderId).toBe("");
  expect(fetch.mock.calls).toHaveLength(1);
});

it("tests saved configuration using only an uploaded file and blocks an unsaved model", async () => {
  const fetch = vi
    .fn()
    .mockImplementation((_url, options) =>
      Promise.resolve(
        response(
          options.method === "POST"
            ? { text: "test text" }
            : options.method === "PUT"
            ? { ...dto, settings: JSON.parse(options.body) }
            : dto,
        ),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  await waitFor(() => expect(result.current.canTest).toBe(true));
  act(() => result.current.setModel("changed"));
  await act(async () =>
    result.current.handleTest(new File(["audio"], "sample.wav")),
  );
  expect(fetch.mock.calls.filter(([, o]) => o.method === "POST")).toHaveLength(
    0,
  );
  await act(async () => result.current.handleSave());
  await act(async () =>
    result.current.handleTest(new File(["audio"], "sample.wav")),
  );
  const posts = fetch.mock.calls.filter(([, o]) => o.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toContain("/workspace/transcription-test");
  expect([...posts[0][1].body.keys()]).toEqual(["file"]);
  expect(result.current.testResult).toBe("test text");
});
it("failed save retains the edited model and keeps test disabled", async () => {
  const fetch = vi
    .fn()
    .mockImplementation((_url, options) =>
      Promise.resolve(
        options.method === "PUT"
          ? new Response("upstream secret", { status: 500 })
          : response(dto),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  await waitFor(() => expect(result.current.canSave).toBe(true));
  act(() => result.current.setModel("unsaved"));
  await act(async () => result.current.handleSave());
  expect(result.current.model).toBe("unsaved");
  expect(result.current.canTest).toBe(false);
  expect(result.current.canSave).toBe(true);
});
it.each(["save", "test"])(
  "ignores a late %s result after switching administrators",
  async (kind) => {
    let finish!: (r: Response) => void;
    const fetch = vi.fn().mockImplementation((_url, options) =>
      !options.method || options.method === "GET"
        ? Promise.resolve(response(dto))
        : new Promise<Response>((r) => {
            finish = r;
          }),
    );
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(useVoiceTranscription, { wrapper });
    await waitFor(() => expect(result.current.canSave).toBe(true));
    let pending!: Promise<void>;
    act(() => {
      pending =
        kind === "save"
          ? result.current.handleSave()
          : result.current.handleTest(new File(["audio"], "sample.wav"));
    });
    act(() =>
      useAuthStore.setState({
        user: { id: "other", platform_role: "admin" } as never,
      }),
    );
    await act(async () => {
      finish(response({ text: "old text" }));
      await pending;
    });
    expect(result.current.testResult).toBe("");
    expect(result.current.saving).toBe(false);
    expect(result.current.testing).toBe(false);
  },
);

it.each([false, true])(
  "uses the full saved model status while preserving concurrent draft edits: %s",
  async (editDuringSave) => {
    const initial = {
      ...dto,
      settings: {
        ...settings,
        transcription_provider_type: "local_whisper",
        transcription_local_model: "base",
      },
      local_status: {
        available: true,
        ffmpeg_installed: true,
        whisper_installed: true,
      },
      local_models: ["base", "small", "tiny"],
    };
    const saved = {
      ...initial,
      settings: { ...initial.settings, transcription_local_model: "small" },
      local_status: {
        available: false,
        ffmpeg_installed: true,
        whisper_installed: true,
      },
      providers: [],
      local_models: ["base", "small"],
    };
    let finish!: (r: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url, options) =>
        options.method === "PUT"
          ? new Promise<Response>((r) => {
              finish = r;
            })
          : Promise.resolve(response(initial)),
      ),
    );
    const { result } = renderHook(useVoiceTranscription, { wrapper });
    await waitFor(() => expect(result.current.canSave).toBe(true));
    act(() => result.current.setLocalModel("small"));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.handleSave();
    });
    if (editDuringSave) act(() => result.current.setLocalModel("tiny"));
    await act(async () => {
      finish(response(saved));
      await pending;
    });
    expect(result.current.localWhisperStatus).toEqual({
      available: false,
      ffmpeg_installed: true,
      whisper_installed: true,
    });
    expect(result.current.localModels).toEqual(["base", "small"]);
    expect(result.current.availableProviders).toEqual([]);
    expect(result.current.localModel).toBe(editDuringSave ? "tiny" : "small");
    expect(result.current.canTest).toBe(!editDuringSave);
  },
);
it("failed local model save preserves the loaded status and later draft edits", async () => {
  const initial = {
    ...dto,
    settings: { ...settings, transcription_provider_type: "local_whisper" },
    local_status: {
      available: true,
      ffmpeg_installed: true,
      whisper_installed: true,
    },
  };
  let finish!: (r: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((_url, options) =>
      options.method === "PUT"
        ? new Promise<Response>((r) => {
            finish = r;
          })
        : Promise.resolve(response(initial)),
    ),
  );
  const { result } = renderHook(useVoiceTranscription, { wrapper });
  await waitFor(() => expect(result.current.canSave).toBe(true));
  act(() => result.current.setLocalModel("small"));
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.handleSave();
  });
  act(() => result.current.setLocalModel("tiny"));
  await act(async () => {
    finish(new Response("failed", { status: 500 }));
    await pending;
  });
  expect(result.current.localWhisperStatus).toEqual(initial.local_status);
  expect(result.current.localModel).toBe("tiny");
  expect(result.current.canTest).toBe(false);
});
