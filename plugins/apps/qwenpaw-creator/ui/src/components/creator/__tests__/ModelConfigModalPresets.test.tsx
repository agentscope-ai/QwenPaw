import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import { installMockFetch } from "@/test/mockFetch";
import type { ModelConfigData } from "@/contracts/creator";

/**
 * Picking a preset model must imply its provider endpoint: a Seedance model
 * chosen while the section still points at DashScope would otherwise submit
 * against the wrong gateway and fail only at generation time.
 */

const baseConfig: ModelConfigData = {
  llm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    multimodal: true,
  },
  vlm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    use_llm: true,
    multimodal: true,
  },
  grounding: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    reuse_llm: true,
    validation_source: "llm",
    tavily_api_key: "",
    serper_api_key: "",
    native_search_enabled: true,
    search_provider: "dashscope_qwen",
    search_reuse_llm: true,
    search_model_name: "",
    search_api_key: "",
    search_base_url: "",
    search_protocol: "DashScope（百炼）",
  },
  asr: {
    enabled: false,
    model_name: "fun-asr",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope Fun-ASR",
    custom_protocol: "",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
  },
  tts: {
    enabled: false,
    model_name: "qwen3-tts-flash",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    voice: "Cherry",
    vc_model_name: "",
    reuse_llm_key: true,
  },
  s2v: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    detect_model_name: "",
    reuse_llm_key: true,
  },
  image: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    translate_model: "",
  },
  video: {
    enabled: false,
    model_name: "wan2.7-r2v",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
  },
  oss: {
    enabled: false,
    access_key_id: "",
    access_key_secret: "",
    endpoint: "",
    bucket: "",
    public_base_url: "",
    policy_api_key: "",
  },
  embedding: {
    enabled: false,
    model_name: "qwen3-vl-embedding",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_vlm_key: true,
  },
  executionAuthorization: { mode: "allow_all" },
  creationCheckpoints: { mode: "skip" },
  mediaReview: { mode: "required" },
};

function mount(config: ModelConfigData = baseConfig) {
  installMockFetch([
    {
      match: "/models/tts-capabilities",
      method: "GET",
      response: { json: { default: "qwen3-tts-flash", models: [] } },
    },
    { match: "/models/config", method: "GET", response: { json: config } },
    {
      match: "/host-providers",
      method: "GET",
      response: { json: { providers: [] } },
    },
  ]);
  render(<ModelConfigModal open onClose={() => {}} />);
}

async function openVideoCard() {
  // The section switcher is a segmented tab bar; activate the video tab.
  const tabs = await screen.findAllByRole("button", { name: /视频生成/ });
  const tab = tabs.find((node) => node.className.includes("segmented-tab"));
  fireEvent.click((tab ?? tabs[0]) as HTMLElement);
}

describe("ModelConfigModal model presets", () => {
  it("realigns protocol and Base URL when a preset model of another provider is picked", async () => {
    mount();
    await openVideoCard();
    const modelInput = await waitFor(() => {
      const label = screen
        .getAllByText("模型名称")
        .map((node) => node.parentElement?.querySelector("input"))
        .find(
          (input): input is HTMLInputElement =>
            input instanceof HTMLInputElement && input.value === "wan2.7-r2v",
        );
      expect(label).toBeTruthy();
      return label as HTMLInputElement;
    });
    fireEvent.change(modelInput, {
      target: { value: "doubao-seedance-2.0-pro" },
    });
    await waitFor(() => {
      const urlInput = screen
        .getAllByPlaceholderText("https://api.example.com")
        .find(
          (input): input is HTMLInputElement =>
            input instanceof HTMLInputElement &&
            input.value === "https://ark.cn-beijing.volces.com",
        );
      expect(urlInput).toBeTruthy();
    });
  });
});
