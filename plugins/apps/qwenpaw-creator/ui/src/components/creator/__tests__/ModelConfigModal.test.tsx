import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelConfigModal, {
  ASR_PROTOCOLS,
  EMBEDDING_PROTOCOLS,
  IMAGE_PROTOCOLS,
  LLM_PROTOCOLS,
  PROTOCOL_LABEL_KEYS,
  S2V_PROTOCOLS,
  TTS_PROTOCOLS,
  VIDEO_PROTOCOLS,
  VLM_PROTOCOLS,
} from "../ModelConfigModal";
import { installMockFetch } from "@/test/mockFetch";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";

const emptyConfig = {
  llm: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    multimodal: false,
  },
  vlm: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    use_llm: false,
    multimodal: false,
  },
  grounding: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
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
  },
  image: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
  },
  video: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "Volcano Engine（火山引擎）",
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
  executionAuthorization: { mode: "required" as const },
};

const configuredGroundingConfig = {
  ...emptyConfig,
  llm: {
    ...emptyConfig.llm,
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  grounding: {
    ...emptyConfig.grounding,
    tavily_api_key: "tvly-saved-secret",
  },
};

describe("ModelConfigModal configuration lifecycle", () => {
  it("keeps a VLM that reuses the LLM enabled after an LLM connectivity test", async () => {
    // A successful test flips llm.enabled via updateItem; that derived-flag
    // update must not cascade into vlm.use_llm/enabled=false — saving right
    // after would silently persist the VLM as disabled.
    const onClose = vi.fn();
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        method: "POST",
        response: { json: { ok: true } },
      },
      {
        match: "/models/config",
        method: "GET",
        response: {
          json: {
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
        },
      },
      {
        match: "/models/real-api-key/llm",
        method: "GET",
        response: { json: { apiKey: "saved-secret" } },
      },
      {
        match: "/models/test",
        method: "POST",
        response: { json: { ok: true, ms: 8 } },
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

    // The VLM badge keeps reflecting the reused LLM model instead of
    // falling into the "disabled" branch …
    expect(screen.queryByText("qwen-vl-max（已停用）")).not.toBeInTheDocument();

    // … and the VLM section still reuses the LLM config and stays enabled.
    // Expand the VLM card via its header title.
    fireEvent.click(screen.getByText("VLM 模型"));
    await waitFor(() =>
      expect(
        screen.getByRole("checkbox", { name: /复用 LLM 配置/ }),
      ).toBeChecked(),
    );
  });

  it("stays unconfigured until the user tests and saves entered model data", async () => {
    const onClose = vi.fn();
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        method: "POST",
        response: { json: { ok: true } },
      },
      {
        match: "/models/config",
        method: "GET",
        response: {
          json: {
            ...emptyConfig,
            grounding: {
              ...emptyConfig.grounding,
              tavily_api_key: "tvly-test",
            },
          },
        },
      },
      {
        match: "/models/test",
        method: "POST",
        response: { json: { ok: true, ms: 8 } },
      },
    ]);
    render(<ModelConfigModal open onClose={onClose} />);

    // The language pane opens with the LLM card already expanded.
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
    // Dirty sections are saved through one atomic POST of the full config and
    // the modal closes automatically on success.
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

  it("shows separate Grounding search and validation sections and can disable grounding", async () => {
    const onClose = vi.fn();
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        method: "POST",
        response: { json: { ok: true } },
      },
      {
        match: "/models/config",
        method: "GET",
        response: { json: configuredGroundingConfig },
      },
    ]);
    render(<ModelConfigModal open onClose={onClose} />);

    fireEvent.click(await screen.findByRole("button", { name: /感知与检索/ }));
    expect(
      await screen.findByText(/tavily\/qwen3\.7-plus/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Grounding"));
    expect(screen.getByText("1. 搜索")).toBeInTheDocument();
    expect(screen.getByText("2. 验证")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "复用 LLM 配置" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("复用 LLM 配置").length).toBeGreaterThanOrEqual(
      2,
    );
    expect(screen.getByText("优先")).toBeInTheDocument();
    expect(screen.getByText("回退")).toBeInTheDocument();
    expect(screen.getByText("Tavily 搜索")).toBeInTheDocument();
    expect(screen.getByText("Qwen/DashScope 原生搜索")).toBeInTheDocument();
    expect(screen.queryByText("复用 qwen3.7-plus")).not.toBeInTheDocument();
    expect(screen.queryByText("超时、重试与来源上限")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "启用 Grounding" }));
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() => {
      const save = calls.find(
        (call) => call.method === "POST" && call.url.endsWith("/models/config"),
      );
      expect(save?.body).toMatchObject({
        grounding: {
          enabled: false,
          reuse_llm: true,
          tavily_api_key: "tvly-saved-secret",
        },
      });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it("shows only the reused model name when Tavily is not configured", async () => {
    installMockFetch([
      {
        match: "/models/config",
        method: "GET",
        response: {
          json: {
            ...configuredGroundingConfig,
            grounding: {
              ...configuredGroundingConfig.grounding,
              tavily_api_key: "",
            },
          },
        },
      },
    ]);

    render(<ModelConfigModal open onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /感知与检索/ }));
    await waitFor(() =>
      expect(screen.queryAllByText(/qwen3\.7-plus/).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/tavily\/qwen3\.7-plus/)).not.toBeInTheDocument();
    expect(screen.queryByText("复用 qwen3.7-plus")).not.toBeInTheDocument();
  });

  it("fills the qwen3-asr preset base url and model when the protocol is picked", async () => {
    installMockFetch([
      {
        match: "/models/config",
        method: "GET",
        response: { json: emptyConfig },
      },
    ]);

    render(<ModelConfigModal open onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /感知与检索/ }));
    fireEvent.click(await screen.findByText("ASR 模型"));
    // Open the ASR protocol select, which shows the Fun-ASR default.
    const protocolSelector = screen
      .getByText("DashScope Fun-ASR")
      .closest(".ant-select");
    expect(protocolSelector).not.toBeNull();
    fireEvent.mouseDown(protocolSelector!.querySelector(".ant-select-input")!);
    await waitFor(() => {
      expect(
        document.querySelector(
          '.ant-select-item-option[title="DashScope Qwen3-ASR"]',
        ),
      ).not.toBeNull();
    });
    fireEvent.click(
      document.querySelector(
        '.ant-select-item-option[title="DashScope Qwen3-ASR"]',
      )!,
    );

    // The preset fills the model candidate and seeds the official base
    // url while keeping it editable for self-hosted deployments.
    await waitFor(() => {
      const values = screen
        .getAllByRole("combobox")
        .map((input) => (input as HTMLInputElement).value);
      expect(values).toContain("qwen3-asr-flash");
    });
    const baseUrl = screen
      .getAllByPlaceholderText("https://api.example.com")
      .find(
        (input) =>
          (input as HTMLInputElement).value ===
          "https://dashscope.aliyuncs.com/api/v1",
      ) as HTMLInputElement | undefined;
    expect(baseUrl).toBeTruthy();
    expect(baseUrl!.disabled).toBe(false);
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

  it("runs the connectivity test when a model is switched on and enables it on success", async () => {
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        method: "GET",
        response: { json: llmConfiguredVideoOff },
      },
      {
        match: "/models/test",
        method: "POST",
        response: { json: { ok: true, ms: 8 } },
      },
    ]);
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
    // A passing probe switches the card on, so the enabled-but-untested
    // (red) state is never shown.
    await waitFor(() => expect(toggle.checked).toBe(true));
    expect(screen.queryByText(/（未测试）/)).not.toBeInTheDocument();
  });

  it("keeps the model switched off when the automatic connectivity test fails", async () => {
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        method: "GET",
        response: { json: llmConfiguredVideoOff },
      },
      {
        match: "/models/test",
        method: "POST",
        response: { json: { ok: false, error: "bad gateway" } },
      },
    ]);
    render(<ModelConfigModal open onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /媒体生成/ }));
    fireEvent.click(await screen.findByText("视频生成模型"));
    const toggle = (await screen.findByRole("checkbox", {
      name: "视频生成模型",
    })) as HTMLInputElement;

    fireEvent.click(toggle);
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/models/test"))).toBe(
        true,
      ),
    );
    await waitFor(() => expect(toggle.disabled).toBe(false));
    expect(toggle.checked).toBe(false);
  });

  it("renders the TTS, S2V and Embedding card copy through i18n keys", async () => {
    installMockFetch([
      {
        match: "/models/config",
        method: "GET",
        response: { json: emptyConfig },
      },
    ]);
    render(<ModelConfigModal open onClose={vi.fn()} />);

    // Assert against the locale JSON values (test locale is forced to zh)
    // so a drifting translation fails here instead of passing silently.
    const mc = zh.modelConfig;
    const escaped = (value: string) =>
      new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

    // Embedding lives on the default language pane.
    fireEvent.click(await screen.findByText(mc.embedding));
    await waitFor(() =>
      expect(screen.getByText(mc.reuseVlmApiKey)).toBeInTheDocument(),
    );
    expect(screen.getByText(mc.embeddingReuseNote)).toBeInTheDocument();

    // TTS and S2V live on the media pane.
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(mc.paneMedia) }),
    );
    fireEvent.click(await screen.findByText(mc.tts));
    await waitFor(() =>
      expect(screen.getByText(mc.reuseLlmApiKey)).toBeInTheDocument(),
    );
    // Both TTS notes share one paragraph, so match each note fragment.
    expect(
      screen.getByText(escaped(mc.ttsSystemVoicesNote)),
    ).toBeInTheDocument();
    expect(
      screen.getByText(escaped(mc.ttsCloneModelAutoNote)),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText(mc.s2v));
    await waitFor(() =>
      expect(screen.getByText(mc.s2vDetectModelLabel)).toBeInTheDocument(),
    );
    expect(screen.getByText(mc.s2vDetectNote)).toBeInTheDocument();
  });

  it("maps every protocol option to a label key present in both locales", () => {
    // Guards the display-label map against drift: a protocol added to any
    // dropdown array without a PROTOCOL_LABEL_KEYS entry would silently fall
    // back to the raw (Chinese) value in English mode.
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
