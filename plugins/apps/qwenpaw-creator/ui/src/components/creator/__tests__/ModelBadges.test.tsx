import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ModelBadges from "../ModelBadges";
import type { ModelConfigData } from "@/contracts/creator";
import { installMockFetch } from "@/test/mockFetch";

const config: ModelConfigData = {
  llm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    multimodal: true,
  },
  vlm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    use_llm: true,
    multimodal: true,
  },
  grounding: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    reuse_llm: true,
    validation_source: "llm",
    tavily_api_key: "",
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
    base_url: "https://example.test/asr",
    protocol: "DashScope Fun-ASR",
    custom_protocol: "",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
  },
  image: {
    enabled: true,
    model_name: "qwen-image",
    api_key: "saved-secret",
    base_url: "https://example.test/image",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
  },
  video: {
    enabled: true,
    model_name: "wan2.7-r2v",
    api_key: "saved-secret",
    base_url: "https://example.test/video",
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
  executionAuthorization: { mode: "allow_all" },
};

describe("ModelBadges", () => {
  it("shows Grounding as configured when it reuses a configured LLM", async () => {
    installMockFetch([
      {
        match: "/models/config",
        method: "GET",
        response: { json: config },
      },
    ]);

    render(<ModelBadges />);

    expect(await screen.findByLabelText("Grounding：已配置")).toHaveAttribute(
      "data-status",
      "on",
    );
  });
});
