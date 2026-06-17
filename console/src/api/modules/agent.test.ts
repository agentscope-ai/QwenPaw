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
    expect(request).toHaveBeenCalledWith("/agent/process", {
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

  it("updateAgentRunningConfig sends PUT with config body", async () => {
    const config = { agents: [{ name: "test" }] } as any;
    vi.mocked(request).mockResolvedValue(config);
    const result = await agentApi.updateAgentRunningConfig(config);
    expect(request).toHaveBeenCalledWith("/workspace/running-config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
    expect(result).toEqual(config);
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
