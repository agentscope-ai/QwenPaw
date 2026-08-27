import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelConfigModal, {
  ASR_PROTOCOLS,
  EMBEDDING_PROTOCOLS,
  IMAGE_PROTOCOLS,
  LLM_PROTOCOLS,
  PRESETS_BY_TYPE,
  PROTOCOL_LABEL_KEYS,
  S2V_PROTOCOLS,
  TTS_PROTOCOLS,
  VIDEO_PROTOCOLS,
  VLM_PROTOCOLS,
} from "../ModelConfigModal";
import { installMockFetch } from "@/test/mockFetch";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import type { ModelConfigData } from "@/contracts/creator";

const DASH = "https://dashscope.aliyuncs.com/api/v1";

/** Minimal model-section builder shared by every config fixture. */
function section<T extends Record<string, unknown>>(over: T) {
  return {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    ...over,
  };
}

const groundingDefaults = section({
  enabled: true,
  reuse_llm: true,
  validation_source: "llm" as const,
  tavily_api_key: "",
  serper_api_key: "",
  native_search_enabled: true,
  search_provider: "dashscope_qwen" as const,
  search_reuse_llm: true,
  search_model_name: "",
  search_api_key: "",
  search_base_url: "",
  search_protocol: "DashScope（百炼）",
});

const ossDefaults = {
  enabled: false,
  access_key_id: "",
  access_key_secret: "",
  endpoint: "",
  bucket: "",
  public_base_url: "",
  policy_api_key: "",
};

const emptyConfig = {
  llm: section({ enabled: true, multimodal: false }),
  vlm: section({ use_llm: false, multimodal: false }),
  grounding: groundingDefaults,
  image: section({}),
  video: section({
    protocol: "Volcano Engine（火山引擎）",
    reuse_llm_key: true,
  }),
  oss: ossDefaults,
  executionAuthorization: { mode: "required" as const },
};

/** Full schema fixture used by the presets/speech suites. */
const speechBaseConfig: ModelConfigData = {
  llm: section({
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    multimodal: true,
  }),
  vlm: section({
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    use_llm: true,
    multimodal: true,
  }),
  grounding: { ...groundingDefaults, enabled: false },
  asr: section({
    model_name: "fun-asr",
    base_url: DASH,
    protocol: "DashScope Fun-ASR",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
  }),
  tts: section({
    enabled: true,
    model_name: "qwen3-tts-flash",
    base_url: DASH,
    protocol: "DashScope（百炼）",
    voice: "Cherry",
    vc_model_name: "",
    reuse_llm_key: true,
  }),
  s2v: section({
    protocol: "DashScope（百炼）",
    detect_model_name: "",
    reuse_llm_key: true,
  }),
  image: section({ translate_model: "", reuse_llm_key: true }),
  video: section({ protocol: "DashScope（百炼）", reuse_llm_key: true }),
  oss: ossDefaults,
  embedding: section({
    model_name: "qwen3-vl-embedding",
    base_url: DASH,
    protocol: "DashScope（百炼）",
    reuse_vlm_key: true,
  }),
  executionAuthorization: { mode: "allow_all" },
  creationCheckpoints: { mode: "skip" },
  mediaReview: { mode: "required" },
  selfReview: {
    sync_enabled: false,
    media_enabled: false,
    render_enabled: false,
  },
};

const presetsBaseConfig: ModelConfigData = {
  ...speechBaseConfig,
  tts: { ...speechBaseConfig.tts, enabled: false },
  video: {
    ...speechBaseConfig.video,
    model_name: "wan2.7-r2v",
    base_url: DASH,
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
  ],
};

function mountModal(
  config: ModelConfigData,
  caps: unknown = { default: "qwen3-tts-flash", models: [] },
  videoCaps: unknown = {
    provider: "wan",
    model: "wan2.7-r2v",
    known: true,
    supportedModes: ["r2v", "t2v", "i2v"],
    effectiveModels: {
      r2v: "wan2.7-r2v",
      t2v: "wan2.7-t2v",
      i2v: "wan2.7-i2v",
    },
    derivesModeModel: true,
    documentationUrl: "https://example.test/docs",
  },
) {
  installMockFetch([
    {
      match: "/models/tts-capabilities",
      method: "GET",
      response: { json: caps },
    },
    { match: "/models/config", method: "GET", response: { json: config } },
    {
      match: "/models/video-capabilities",
      method: "GET",
      response: { json: videoCaps },
    },
    {
      match: "/host-providers",
      method: "GET",
      response: { json: { providers: [] } },
    },
  ]);
  render(<ModelConfigModal open onClose={() => {}} />);
}

async function openSpeechCard() {
  // Navigate to the media pane, then expand the collapsed TTS card.
  fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
  const headers = await screen.findAllByText(/TTS 语音合成/);
  fireEvent.click(headers[0]);
}

/** GET/POST /models/config routes plus an optional /models/test probe. */
function configRoutes(json: unknown, testJson?: Record<string, unknown>) {
  const routes = [
    {
      match: "/models/config",
      method: "POST",
      response: { json: { ok: true } },
    },
    { match: "/models/config", method: "GET", response: { json } },
  ];
  if (testJson) {
    routes.push({
      match: "/models/test",
      method: "POST",
      response: { json: testJson },
    });
  }
  return routes;
}

describe("ModelConfigModal configuration lifecycle", () => {
  it("keeps a VLM that reuses the LLM enabled after an LLM connectivity test", async () => {
    // A successful test flips llm.enabled via updateItem; that update must
    // not cascade into vlm.use_llm/enabled=false before a save.
    const onClose = vi.fn();
    const { calls } = installMockFetch([
      ...configRoutes(
        {
          ...emptyConfig,
          llm: {
            ...emptyConfig.llm,
            model_name: "qwen3.7-plus",
            api_key: "saved-secret",
            base_url: "https://provider.test/v1",
          },
          vlm: {
            ...emptyConfig.vlm,
            enabled: true,
            use_llm: true,
            model_name: "qwen-vl-max",
          },
        },
        { ok: true, ms: 8 },
      ),
      {
        match: "/models/real-api-key/llm",
        method: "GET",
        response: { json: { apiKey: "saved-secret" } },
      },
    ]);
    render(<ModelConfigModal open onClose={onClose} />);

    await waitFor(() =>
      expect(screen.getAllByText("qwen3.7-plus").length).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getByRole("button", { name: /测试连通性/ }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/models/test"))).toBe(
        true,
      ),
    );

    // The VLM badge keeps reflecting the reused LLM model.
    expect(screen.queryByText("qwen-vl-max（已停用）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("VLM 模型"));
    await waitFor(() =>
      expect(
        screen.getByRole("checkbox", { name: /复用 LLM 配置/ }),
      ).toBeChecked(),
    );
  });

  it("stays unconfigured until the user tests and saves entered model data", async () => {
    const onClose = vi.fn();
    const { calls } = installMockFetch(
      configRoutes(
        {
          ...emptyConfig,
          grounding: {
            ...emptyConfig.grounding,
            tavily_api_key: "tvly-test",
          },
        },
        { ok: true, ms: 8 },
      ),
    );
    render(<ModelConfigModal open onClose={onClose} />);

    const keyInput = await screen.findByPlaceholderText("sk-...");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(
      screen.queryByRole("button", { name: "显示" }),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("model"), {
      target: { value: "saved-model" },
    });
    fireEvent.change(keyInput, { target: { value: "saved-secret" } });
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com"), {
      target: { value: "https://provider.test/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /测试连通性/ }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/models/test"))).toBe(
        true,
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));
    // One atomic POST of the full config; the modal closes on success.
    await waitFor(() => {
      const save = calls.find(
        (call) => call.method === "POST" && call.url.endsWith("/models/config"),
      );
      expect(save?.body).toMatchObject({
        llm: {
          model_name: "saved-model",
          api_key: "saved-secret",
          base_url: "https://provider.test/v1",
        },
      });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  const llmConfiguredVideoOff = {
    ...emptyConfig,
    llm: {
      ...emptyConfig.llm,
      model_name: "qwen3.7-plus",
      api_key: "saved-secret",
      base_url: "https://provider.test/v1",
    },
    video: { ...emptyConfig.video, reuse_llm_key: true },
  };

  it.each<[string, Record<string, unknown>, boolean]>([
    ["enables it on success", { ok: true, ms: 8 }, true],
    ["keeps it off on failure", { ok: false, error: "bad gateway" }, false],
  ])(
    "runs the connectivity test when a model is switched on and %s",
    async (_name, testJson, expectedChecked) => {
      const { calls } = installMockFetch(
        configRoutes(llmConfiguredVideoOff, testJson),
      );
      render(<ModelConfigModal open onClose={vi.fn()} />);

      fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
      fireEvent.click(await screen.findByText("视频生成模型"));
      const toggle = (await screen.findByRole("checkbox", {
        name: "视频生成模型",
      })) as HTMLInputElement;
      expect(toggle.checked).toBe(false);

      fireEvent.click(toggle);
      await waitFor(() =>
        expect(calls.some((call) => call.url.endsWith("/models/test"))).toBe(
          true,
        ),
      );
      await waitFor(() => expect(toggle.disabled).toBe(false));
      // A passing probe switches the card on; a failing probe keeps it off.
      await waitFor(() => expect(toggle.checked).toBe(expectedChecked));
      if (expectedChecked) {
        expect(screen.queryByText(/（未测试）/)).not.toBeInTheDocument();
      }
    },
  );

  it("maps every protocol option to a label key present in both locales", () => {
    // Guards the display-label map against drift into raw Chinese values.
    const protocols = new Set([
      ...LLM_PROTOCOLS,
      ...VLM_PROTOCOLS,
      ...ASR_PROTOCOLS,
      ...TTS_PROTOCOLS,
      ...S2V_PROTOCOLS,
      ...EMBEDDING_PROTOCOLS,
      ...IMAGE_PROTOCOLS,
      ...VIDEO_PROTOCOLS,
    ]);
    const zhProtocols = zh.modelConfig.protocols as Record<string, string>;
    const enProtocols = en.modelConfig.protocols as Record<string, string>;
    for (const protocol of protocols) {
      const key = PROTOCOL_LABEL_KEYS[protocol];
      expect(key, `missing label key for protocol "${protocol}"`).toBeTruthy();
      const leaf = key.split(".").pop()!;
      expect(
        zhProtocols[leaf],
        `missing zh translation for "${protocol}"`,
      ).toBeTruthy();
      expect(
        enProtocols[leaf],
        `missing en translation for "${protocol}"`,
      ).toBeTruthy();
    }
  });
});

describe("ModelConfigModal model presets", () => {
  it("offers Wan3.0 while keeping the legacy Bailian URL as default", () => {
    const bailian = PRESETS_BY_TYPE.video["DashScope（百炼）"];
    expect(bailian.models).toContain("wan3.0-video");
    expect(bailian.models).toContain("wan3.0-video-prime");
    expect(bailian.base_url).toBe("https://dashscope.aliyuncs.com/api/v1");
  });

  it("offers every preset protocol in its dropdown", () => {
    // A preset the dropdown does not list is unreachable, and a saved
    // protocol outside the list is silently reset on load — which would
    // strand the media channels that are selected by protocol.
    const listed: Record<string, readonly string[]> = {
      asr: ASR_PROTOCOLS,
      tts: TTS_PROTOCOLS,
      s2v: S2V_PROTOCOLS,
      embedding: EMBEDDING_PROTOCOLS,
      image: IMAGE_PROTOCOLS,
      video: VIDEO_PROTOCOLS,
    };
    for (const [type, presets] of Object.entries(PRESETS_BY_TYPE)) {
      for (const protocol of Object.keys(presets)) {
        expect(
          listed[type],
          `no protocol list for section "${type}"`,
        ).toBeTruthy();
        expect(
          listed[type],
          `preset "${protocol}" is missing from ${type} protocols`,
        ).toContain(protocol);
      }
    }
  });

  it("does NOT change protocol or base_url when model_name is changed", async () => {
    // Users must explicitly select the protocol they want.
    mountModal(presetsBaseConfig);
    fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
    fireEvent.click(await screen.findByText("视频生成模型"));
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
      target: { value: "doubao-seedance-2-0-260128" },
    });
    await waitFor(() => {
      const urlInput = screen
        .getAllByPlaceholderText("https://api.example.com")
        .find(
          (input): input is HTMLInputElement =>
            input instanceof HTMLInputElement && input.value === DASH,
        );
      expect(urlInput).toBeTruthy();
    });
  });

  it("renders exact backend capabilities for a single Vidu model", async () => {
    const viduConfig: ModelConfigData = {
      ...presetsBaseConfig,
      video: {
        ...presetsBaseConfig.video,
        protocol: "Vidu（官方）",
        model_name: "viduq2-pro",
        base_url: "https://api.vidu.com",
      },
    };
    mountModal(viduConfig, undefined, {
      provider: "vidu",
      model: "viduq2-pro",
      known: true,
      supportedModes: ["r2v", "i2v"],
      effectiveModels: { r2v: "viduq2-pro", i2v: "viduq2-pro" },
      derivesModeModel: false,
      documentationUrl: "https://platform.vidu.com/docs",
    });

    fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
    fireEvent.click(await screen.findByText("视频生成模型"));

    expect(await screen.findByText("r2v 参考生视频")).toBeInTheDocument();
    expect(screen.getByText("i2v 图生视频")).toBeInTheDocument();
    expect(screen.queryByText("t2v 文生视频")).not.toBeInTheDocument();
    expect(screen.getByText(/单模型能力声明/)).toBeInTheDocument();
  });
});

describe("ModelConfigModal speech section", () => {
  it("keeps clone companions automatic and offers only real system voices", async () => {
    mountModal(speechBaseConfig, capabilities);
    await openSpeechCard();
    await waitFor(() => {
      expect(screen.getByText("默认旁白音色")).toBeInTheDocument();
    });
    expect(screen.queryByText(/声音复刻模型/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/复刻\/设计所用的配套模型由后端自动选择/),
    ).toBeInTheDocument();
    const voiceInput = screen
      .getByText("默认旁白音色")
      .parentElement?.querySelector("input");
    expect(voiceInput).toHaveValue("Cherry");
  });

  it("seeds the frozen preset endpoint for a never-configured s2v section", async () => {
    // The digital-human section has a single protocol, so no protocol switch
    // ever applies a preset; without seeding it could never be saved.
    mountModal(speechBaseConfig, capabilities);
    fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
    const headers = await screen.findAllByText(/数字人模型/);
    fireEvent.click(headers[0]);
    await waitFor(() => {
      expect(screen.getByText("人像检测模型（可选）")).toBeInTheDocument();
    });
    const values = Array.from(document.querySelectorAll("input")).map(
      (node) => (node as HTMLInputElement).value,
    );
    expect(values).toContain(DASH);
    expect(values).toContain("wan2.2-s2v");
  });
});
