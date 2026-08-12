import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import { installMockFetch } from "@/test/mockFetch";
import type { ModelConfigData } from "@/contracts/creator";

/**
 * The speech section must describe only what the selected model can do.
 * Offering a system-voice picker for a model that has none, or asking the user
 * to name the clone/design companion models, turns a working configuration
 * into a failing one at synthesis time.
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
    enabled: true,
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
    reuse_llm_key: true,
  },
  video: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_llm_key: true,
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
  selfReview: {
    sync_enabled: false,
    media_enabled: false,
    render_enabled: false,
  },
};

const capabilities = {
  default: "qwen3-tts-flash",
  models: [
    {
      model: "qwen3-tts-flash",
      label: "Qwen3 TTS Flash（系统音色，快速）",
      family: "qwen-tts",
      transport: "http",
      systemVoices: ["Cherry", "Ethan"],
      supportsDesign: true,
    },
    {
      model: "cosyvoice-v3.5-plus",
      label: "CosyVoice 3.5 Plus（无系统音色，需先设计或复刻音色）",
      family: "cosyvoice",
      transport: "websocket",
      systemVoices: [],
      supportsDesign: true,
    },
  ],
};

function mount(config: ModelConfigData = baseConfig) {
  installMockFetch([
    {
      match: "/models/tts-capabilities",
      method: "GET",
      response: { json: capabilities },
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

async function openSpeechCard() {
  // Navigate to the media pane, then expand the collapsed TTS card by
  // clicking its header label.
  fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
  const headers = await screen.findAllByText(/TTS 语音合成/);
  fireEvent.click(headers[0]);
}

describe("ModelConfigModal speech section", () => {
  it("never asks the user to name the clone or design companion model", async () => {
    mount();
    await openSpeechCard();
    await waitFor(() => {
      expect(screen.getByText("默认旁白音色")).toBeInTheDocument();
    });
    expect(screen.queryByText(/声音复刻模型/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/复刻\/设计所用的配套模型由后端自动选择/),
    ).toBeInTheDocument();
  });

  it("offers only the system voices the selected model actually has", async () => {
    mount();
    await openSpeechCard();
    await waitFor(() => {
      expect(screen.getByText("默认旁白音色")).toBeInTheDocument();
    });
    const voiceInput = screen
      .getByText("默认旁白音色")
      .parentElement?.querySelector("input");
    expect(voiceInput).toHaveValue("Cherry");
  });

  it("seeds the frozen preset endpoint for a never-configured s2v section", async () => {
    // The digital-human section has a single protocol, so switching protocol
    // — the only thing that applies a preset — is impossible; without
    // seeding, its frozen Base URL stays empty and the section cannot be
    // saved at all.
    mount({
      ...baseConfig,
      s2v: {
        ...baseConfig.s2v,
        model_name: "",
        base_url: "",
        detect_model_name: "",
      },
    });
    // Navigate to the media pane, then expand the digital-human card by
    // clicking its header label.
    fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
    const headers = await screen.findAllByText(/数字人模型/);
    fireEvent.click(headers[0]);
    await waitFor(() => {
      expect(screen.getByText("人像检测模型（可选）")).toBeInTheDocument();
    });
    const inputs = Array.from(document.querySelectorAll("input"));
    const values = inputs.map((node) => (node as HTMLInputElement).value);
    expect(values).toContain("https://dashscope.aliyuncs.com/api/v1");
    expect(values).toContain("wan2.2-s2v");
  });

  it("hides the voice picker for a model without system voices", async () => {
    mount({
      ...baseConfig,
      tts: { ...baseConfig.tts, model_name: "cosyvoice-v3.5-plus", voice: "" },
    });
    await openSpeechCard();
    await waitFor(() => {
      expect(
        screen.getByText(
          /该模型没有系统音色：Agent 会先根据角色设定设计专属音色/,
        ),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("默认旁白音色")).not.toBeInTheDocument();
  });
});

describe("ModelConfigModal model dropdown catalog", () => {
  it("shows the whole speech catalog even when a model is configured", async () => {
    mount();
    await openSpeechCard();
    const modelInput = (await screen.findByDisplayValue(
      "qwen3-tts-flash",
    )) as HTMLInputElement;
    // Opening the dropdown must not filter by the configured value:
    // CosyVoice stays visible next to the current qwen3-tts pick.
    fireEvent.focus(modelInput);
    fireEvent.mouseDown(modelInput);
    await waitFor(() => {
      expect(
        document.querySelector(
          '.ant-select-item-option[title*="CosyVoice 3.5 Plus"]',
        ),
      ).toBeTruthy();
    });
  });

  it("keeps the speech base url editable", async () => {
    mount();
    await openSpeechCard();
    const baseUrl = (await screen.findByDisplayValue(
      "https://dashscope.aliyuncs.com/api/v1",
    )) as HTMLInputElement;
    expect(baseUrl.disabled).toBe(false);
  });
});
