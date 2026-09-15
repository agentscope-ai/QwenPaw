import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "../request";
import { providerApi } from "./provider";
import { RealtimeVoiceApiError, realtimeVoiceApi } from "./realtimeVoice";

vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "Bearer local" }),
}));
vi.mock("../request", () => ({ request: vi.fn() }));

describe("realtimeVoiceApi.createSession", () => {
  afterEach(() => vi.restoreAllMocks());

  it("releases the exact session using its original agent identity", async () => {
    await realtimeVoiceApi.endSession({
      session_id: "live-2",
      agent_id: "old-agent",
    } as Parameters<typeof realtimeVoiceApi.endSession>[0]);
    expect(request).toHaveBeenCalledWith("/realtime-voice/sessions/live-2", {
      method: "DELETE",
      headers: { "X-Agent-Id": "old-agent" },
    });
  });

  it("preserves structured conflict details for explicit switch UI", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: () =>
        Promise.resolve({
          detail: {
            code: "live_session_conflict",
            message: "Another Voice session is active.",
            session_id: "live-1",
            chat_id: "chat-1",
          },
        }),
    } as Response);

    const error = await realtimeVoiceApi
      .createSession({})
      .catch((reason) =>
        reason instanceof RealtimeVoiceApiError
          ? reason
          : Promise.reject(reason),
      );

    expect(error).toBeInstanceOf(RealtimeVoiceApiError);
    expect(error).toMatchObject({
      code: "live_session_conflict",
      status: 409,
      details: { session_id: "live-1", chat_id: "chat-1" },
    });
  });

  it("posts the resume identifiers with backend-only authorization", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ session_id: "live-2" }),
    } as Response);

    await realtimeVoiceApi.createSession({
      chat_id: "chat-1",
      previous_session_id: "live-1",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/realtime-voice/sessions",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer local" }),
        body: JSON.stringify({
          chat_id: "chat-1",
          previous_session_id: "live-1",
        }),
      }),
    );
  });
});

describe("Provider-owned realtime model configuration", () => {
  afterEach(() => vi.clearAllMocks());

  it("writes the active realtime model through the shared model slot API", async () => {
    vi.mocked(request).mockResolvedValue({});

    await providerApi.setActiveRealtimeVoice({
      provider_id: "dashscope",
      model: "qwen-realtime",
      scope: "agent",
      agent_id: "agent-1",
    });

    expect(request).toHaveBeenCalledWith("/models/active", {
      method: "PUT",
      body: JSON.stringify({
        provider_id: "dashscope",
        model: "qwen-realtime",
        scope: "agent",
        agent_id: "agent-1",
        slot: "realtime_voice",
      }),
    });
  });

  it("writes the configurable voice router through the shared model slot API", async () => {
    vi.mocked(request).mockResolvedValue({});

    await providerApi.setActiveVoiceRouter({
      provider_id: "openai",
      model: "gpt-5",
      scope: "global",
    });

    expect(request).toHaveBeenCalledWith("/models/active", {
      method: "PUT",
      body: JSON.stringify({
        provider_id: "openai",
        model: "gpt-5",
        scope: "global",
        slot: "voice_router",
      }),
    });
  });

  it("stores connection settings on the Provider realtime model", async () => {
    vi.mocked(request).mockResolvedValue({});
    const config = {
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
    };

    await providerApi.configureRealtimeVoiceModel(
      "dashscope",
      "qwen-realtime",
      config,
    );

    expect(request).toHaveBeenCalledWith(
      "/models/dashscope/realtime-models/qwen-realtime/config",
      { method: "PUT", body: JSON.stringify(config) },
    );
  });
});
