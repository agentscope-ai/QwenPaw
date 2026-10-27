import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import ModelBadges from "../ModelBadges";
import type { ModelConfigData } from "@/contracts/creator";
import { configuredModelConfig } from "@/test/agentFixtures";
import { installMockFetch } from "@/test/mockFetch";
import { useModelConfigStore } from "@/store/modelConfigStore";

function renderBadges(tts: Partial<ModelConfigData["tts"]> = {}) {
  const config = {
    ...configuredModelConfig,
    llm: {
      ...configuredModelConfig.llm,
      protocol: "DashScope（百炼）",
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    tts: { ...configuredModelConfig.tts, ...tts },
  };
  const configResponse = { json: config };
  const { calls } = installMockFetch([
    {
      match: "/models/config",
      method: "GET",
      response: configResponse,
    },
    {
      match: "/host-providers",
      response: { json: { providers: [] } },
    },
  ]);
  render(<ModelBadges />);
  return { configResponse, calls };
}

beforeEach(() => {
  useModelConfigStore.setState({ config: null });
});

describe("ModelBadges", () => {
  it("shows one readiness ring, exposes details on focus, and refreshes after configuration", async () => {
    const { configResponse, calls } = renderBadges();
    const button = screen.getByRole("button", { name: "模型配置" });
    expect(await screen.findByLabelText("模型 5/8")).toHaveTextContent("5/8");
    expect(button.querySelectorAll("[data-model-badges-ring]")).toHaveLength(1);
    expect(button.querySelector("[stroke-dasharray]")).toHaveAttribute(
      "stroke-dasharray",
      "62.5 100",
    );
    expect(button.querySelector("[data-model-badge]")).toBeNull();
    fireEvent.focus(button);
    expect(await screen.findByLabelText("Grounding：已配置")).toHaveAttribute(
      "data-status",
      "on",
    );
    fireEvent.click(button);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    const readsBeforeClose = calls.filter((call) =>
      call.url.endsWith("/models/config"),
    ).length;
    configResponse.json = {
      ...configResponse.json,
      tts: { ...configResponse.json.tts, enabled: true },
    };
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.endsWith("/models/config")),
      ).toHaveLength(readsBeforeClose + 1),
    );
    expect(await screen.findByLabelText("模型 6/8")).toHaveTextContent("6/8");
  });

  it.each<[string, Partial<ModelConfigData["tts"]>, string, string]>([
    [
      "configured when enabled with its own key",
      { enabled: true, api_key: "saved-secret", voice: "Cherry" },
      "语音合成模型：已配置",
      "on",
    ],
    [
      "configured but idle when saved yet disabled",
      {},
      "语音合成模型：已配置但未启用",
      "off",
    ],
  ])("marks TTS %s on hover", async (_name, tts, label, dataStatus) => {
    renderBadges(tts);
    fireEvent.mouseEnter(screen.getByRole("button", { name: "模型配置" }));
    expect(await screen.findByLabelText(label)).toHaveAttribute(
      "data-status",
      dataStatus,
    );
  });

  it("keeps configuration accessible when the config request fails", async () => {
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        response: { ok: false, status: 503, json: { message: "Unavailable" } },
      },
      { match: "/host-providers", response: { json: { providers: [] } } },
    ]);
    render(<ModelBadges />);
    const button = screen.getByRole("button", { name: "模型配置" });
    expect(screen.getByLabelText("模型 0/8")).toBeVisible();
    expect(button.querySelector("[stroke-dasharray]")).toBeNull();
    fireEvent.click(button);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.endsWith("/models/config")),
      ).toHaveLength(2),
    );
    expect(screen.getByLabelText("模型 0/8")).toBeVisible();
  });
});
