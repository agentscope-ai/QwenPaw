import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { agentApi } from "./agent";
import { request } from "../request";

describe("agentApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("agentRoot calls GET /agent/", async () => {
    vi.mocked(request).mockResolvedValue({ status: "ok" });
    const result = await agentApi.agentRoot();
    expect(request).toHaveBeenCalledWith("/agent/");
    expect(result).toEqual({ status: "ok" });
  });

  it("healthCheck calls GET /agent/health", async () => {
    vi.mocked(request).mockResolvedValue({ healthy: true });
    const result = await agentApi.healthCheck();
    expect(request).toHaveBeenCalledWith("/agent/health");
    expect(result).toEqual({ healthy: true });
  });

  it("agentApi sends POST to /agent/process with body", async () => {
    const body = { message: "hello", session_id: "s1" };
    await agentApi.agentApi(body as any);
    expect(request).toHaveBeenCalledWith("/console/chat", {
      method: "POST",
      body: JSON.stringify(body),
    });
  });

  it("getProcessStatus calls GET /agent/admin/status", async () => {
    vi.mocked(request).mockResolvedValue({ running: true });
    const result = await agentApi.getProcessStatus();
    expect(request).toHaveBeenCalledWith("/agent/admin/status");
    expect(result).toEqual({ running: true });
  });

  it("shutdown sends POST to /agent/admin/shutdown", async () => {
    await agentApi.shutdown();
    expect(request).toHaveBeenCalledWith("/agent/admin/shutdown", {
      method: "POST",
    });
  });

  it("getAgentRunningConfig calls GET /agent/running-config", async () => {
    const config = { agents: [] };
    vi.mocked(request).mockResolvedValue(config);
    const result = await agentApi.getAgentRunningConfig();
    expect(request).toHaveBeenCalledWith("/workspace/running-config");
    expect(result).toEqual(config);
  });

  it("reads running-config access and safe summary", async () => {
    vi.mocked(request)
      .mockResolvedValueOnce({ can_edit: false })
      .mockResolvedValueOnce({ agent_id: "agent-1", name: "Shared Agent" });

    await agentApi.getAgentRunningConfigAccess();
    await agentApi.getAgentRunningConfigSummary();

    expect(request).toHaveBeenNthCalledWith(1, "/workspace/access");
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/workspace/running-config/summary",
    );
  });

  it("sends the explicit governance context only for runtime-config requests", async () => {
    await agentApi.getAgentRunningConfigAccess({
      agentId: "managed-agent",
      governance: true,
    });
    await agentApi.getAgentRunningConfig({
      agentId: "managed-agent",
      governance: true,
    });

    const headers = {
      "X-Agent-Id": "managed-agent",
      "X-Agent-Governance": "runtime-config",
    };
    expect(request).toHaveBeenNthCalledWith(1, "/workspace/access", {
      headers,
    });
    expect(request).toHaveBeenNthCalledWith(2, "/workspace/running-config", {
      headers,
    });
  });

  it("updateAgentRunningConfig sends PUT with config body", async () => {
    const config = { agents: [{ name: "test" }] } as any;
    vi.mocked(request).mockResolvedValue(config);
    const result = await agentApi.updateAgentRunningConfig(config);
    expect(request).toHaveBeenCalledWith("/workspace/running-config", {
      method: "PUT",
      body: JSON.stringify(config),
      timeout: 10 * 60 * 1000,
    });
    expect(result).toEqual(config);
  });

  it("reads the running-config version and sends it with saves", async () => {
    const versionedConfig = { max_iters: 101 } as any;
    vi.mocked(request)
      .mockResolvedValueOnce({ version: 3 })
      .mockResolvedValueOnce({ max_iters: 101 });
    await expect(agentApi.getAgentRunningConfigVersion()).resolves.toEqual({
      version: 3,
    });
    await agentApi.updateAgentRunningConfig(versionedConfig, 3);
    expect(request).toHaveBeenLastCalledWith("/workspace/running-config", {
      method: "PUT",
      body: JSON.stringify(versionedConfig),
      headers: { "If-Match": '"3"' },
      timeout: 10 * 60 * 1000,
    });
  });

  it("reads and retries the running-config runtime status", async () => {
    vi.mocked(request)
      .mockResolvedValueOnce({ state: "pending_reload" })
      .mockResolvedValueOnce({ state: "applied" });

    await expect(
      agentApi.getAgentRunningConfigRuntimeStatus(),
    ).resolves.toEqual({ state: "pending_reload" });
    await expect(agentApi.retryAgentRunningConfigReload()).resolves.toEqual({
      state: "applied",
    });
    expect(request).toHaveBeenNthCalledWith(
      1,
      "/workspace/running-config/runtime-status",
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/workspace/running-config/reload",
      { method: "POST" },
    );
  });

  it("testEmbedding sends unsaved embedding config", async () => {
    const config = {
      backend: "openai" as const,
      api_key: "key",
      base_url: "https://example.com/v1",
      model_name: "embedding-model",
      dimensions: 1024,
      enable_cache: true,
      use_dimensions: false,
      max_cache_size: 10000,
      max_input_length: 8192,
      max_batch_size: 10,
    };
    await agentApi.testEmbedding(config);
    expect(request).toHaveBeenCalledWith("/workspace/embedding/test", {
      method: "POST",
      body: JSON.stringify(config),
      timeout: 30 * 1000,
    });
  });

  it("testEmbedding keeps the explicit governance target", async () => {
    const config = {
      backend: "ollama" as const,
      api_key: "",
      base_url: "http://localhost:11434",
      model_name: "nomic-embed-text",
      dimensions: 768,
      enable_cache: true,
      use_dimensions: false,
      max_cache_size: 10000,
      max_input_length: 8192,
      max_batch_size: 10,
    };

    await agentApi.testEmbedding(config, {
      agentId: "governed-agent",
      governance: true,
    });

    expect(request).toHaveBeenCalledWith("/workspace/embedding/test", {
      method: "POST",
      body: JSON.stringify(config),
      timeout: 30 * 1000,
      headers: {
        "X-Agent-Id": "governed-agent",
        "X-Agent-Governance": "runtime-config",
      },
    });
  });

  it("updateAgentLanguage sends PUT with language in body", async () => {
    vi.mocked(request).mockResolvedValue({
      language: "zh",
      copied_files: ["a.txt"],
    });
    const result = await agentApi.updateAgentLanguage("zh");
    expect(request).toHaveBeenCalledWith("/workspace/language", {
      method: "PUT",
      body: JSON.stringify({ language: "zh" }),
    });
    expect(result).toEqual({ language: "zh", copied_files: ["a.txt"] });
  });

  it("updateAudioMode sends PUT with audio_mode in body", async () => {
    await agentApi.updateAudioMode("push_to_talk");
    expect(request).toHaveBeenCalledWith("/workspace/audio-mode", {
      method: "PUT",
      body: JSON.stringify({ audio_mode: "push_to_talk" }),
    });
  });

  it("getLocalWhisperStatus calls GET /agent/local-whisper-status", async () => {
    const status = {
      available: true,
      ffmpeg_installed: true,
      whisper_installed: true,
    };
    vi.mocked(request).mockResolvedValue(status);
    const result = await agentApi.getLocalWhisperStatus();
    expect(request).toHaveBeenCalledWith("/workspace/local-whisper-status");
    expect(result).toEqual(status);
  });

  it("updateTranscriptionProvider sends PUT with provider_id", async () => {
    await agentApi.updateTranscriptionProvider("openai");
    expect(request).toHaveBeenCalledWith("/workspace/transcription-provider", {
      method: "PUT",
      body: JSON.stringify({ provider_id: "openai" }),
    });
  });
});
