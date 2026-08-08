import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelConfigModal from "../ModelConfigModal";
import { installMockFetch } from "@/test/mockFetch";

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

    await waitFor(() => expect(screen.getAllByText("未配置")).toHaveLength(5));
    const keyInput = screen.getByPlaceholderText("sk-...");
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

    expect(
      await screen.findByRole("button", {
        name: /Grounding.*tavily\/qwen3\.7-plus/,
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Grounding/ }));
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

    expect(
      await screen.findByRole("button", {
        name: /Grounding.*qwen3\.7-plus/,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("tavily/qwen3.7-plus")).not.toBeInTheDocument();
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

    fireEvent.click(await screen.findByRole("button", { name: /ASR/ }));
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
});
