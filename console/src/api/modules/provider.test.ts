import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { providerApi } from "./provider";

vi.mock("@/api/request", () => ({
  request: vi.fn(),
}));

import { request } from "@/api/request";

describe("providerApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("listProviders calls /models", async () => {
    await providerApi.listProviders();
    expect(request).toHaveBeenCalledWith("/models");
  });

  it("getActiveModels with no params calls /models/active", async () => {
    await providerApi.getActiveModels();
    expect(request).toHaveBeenCalledWith("/models/active");
  });

  it("getActiveModels with only scope builds correct query", async () => {
    await providerApi.getActiveModels({ scope: "global" });
    expect(request).toHaveBeenCalledWith("/models/active?scope=global");
  });

  it("getActiveModels with only agent_id builds correct query", async () => {
    await providerApi.getActiveModels({ agent_id: "agent-1" });
    expect(request).toHaveBeenCalledWith("/models/active?agent_id=agent-1");
  });

  it("getActiveModels with both scope and agent_id builds correct query", async () => {
    await providerApi.getActiveModels({
      scope: "effective",
      agent_id: "agent-1",
    });
    expect(request).toHaveBeenCalledWith(
      "/models/active?scope=effective&agent_id=agent-1",
    );
  });

  it("getActiveModels with session_id builds correct query", async () => {
    await providerApi.getActiveModels({
      scope: "effective",
      agent_id: "agent-1",
      session_id: "channel:private:user-1",
    });
    expect(request).toHaveBeenCalledWith(
      "/models/active?scope=effective&agent_id=agent-1&session_id=channel%3Aprivate%3Auser-1",
    );
  });

  it("setActiveLlm sends a PUT request", async () => {
    const body = {
      provider_id: "openai",
      model: "gpt-4",
      scope: "agent" as const,
    };
    await providerApi.setActiveLlm(body);
    expect(request).toHaveBeenCalledWith("/models/active", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  });

  it("getSessionModelOverrides calls /models/session-overrides", async () => {
    await providerApi.getSessionModelOverrides();
    expect(request).toHaveBeenCalledWith("/models/session-overrides");
  });

  it("setSessionModelOverride encodes ids and sends PUT", async () => {
    const body = { provider_id: "openai", model: "gpt-4o" };
    await providerApi.setSessionModelOverride(
      "agent/1",
      "channel:private:user-1",
      body,
    );
    expect(request).toHaveBeenCalledWith(
      "/models/session-overrides/agent%2F1/channel%3Aprivate%3Auser-1",
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
  });

  it("resetSessionModelOverride encodes ids and sends DELETE", async () => {
    await providerApi.resetSessionModelOverride("agent/1", "console:session-1");
    expect(request).toHaveBeenCalledWith(
      "/models/session-overrides/agent%2F1/console%3Asession-1",
      { method: "DELETE" },
    );
  });

  it("resetAllSessionModelOverrides sends DELETE", async () => {
    await providerApi.resetAllSessionModelOverrides();
    expect(request).toHaveBeenCalledWith("/models/session-overrides", {
      method: "DELETE",
    });
  });

  it("configureProvider encodes providerId and sends PUT", async () => {
    await providerApi.configureProvider("open/ai", { api_key: "sk-xxx" });
    expect(request).toHaveBeenCalledWith(
      "/models/open%2Fai/config",
      expect.objectContaining({ method: "PUT" }),
    );
  });

  it("addModel sends POST to the correct path", async () => {
    await providerApi.addModel("openai", { id: "gpt-5", name: "GPT-5" });
    expect(request).toHaveBeenCalledWith(
      "/models/openai/models",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("removeModel sends DELETE and encodes both ids", async () => {
    await providerApi.removeModel("open/ai", "gpt-4");
    expect(request).toHaveBeenCalledWith(
      "/models/open%2Fai/models/gpt-4",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
