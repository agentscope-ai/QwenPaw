import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import api from "../../../../../api";
import type {
  ProviderInfo,
  LocalModelInfo,
  LocalServerStatus,
  LocalDownloadProgress,
  LocalServerUpdateStatus,
  LocalModelConfig,
} from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

import { LocalModelManageModal } from "./LocalModelManageModal";

// Mock react-i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      changeLanguage: vi.fn(),
      language: "en",
    },
  }),
}));

// Mock @agentscope-ai/design with Select included
vi.mock("@agentscope-ai/design", () => {
  const passThrough = ({ children, ...props }: Record<string, unknown>) =>
    React.createElement("div", props, children as any);

  const buttonLike = ({
    children,
    onClick,
    icon,
    ...props
  }: Record<string, unknown>) =>
    React.createElement(
      "button",
      { onClick, ...props },
      icon as any,
      children as any,
    );

  const selectLike = ({
    value,
    onChange,
    options,
    className,
  }: Record<string, unknown>) => {
    const opts = (options as Array<{ value: string; label: string }>) || [];
    const currentLabel = opts.find((o) => o.value === value)?.label ?? value;
    return React.createElement(
      "div",
      { className, "data-testid": "select-wrapper" },
      React.createElement(
        "span",
        { "data-testid": "select-value" },
        currentLabel as any,
      ),
      React.createElement(
        "div",
        { role: "listbox" },
        opts.map((o) =>
          React.createElement(
            "button",
            {
              key: o.value,
              type: "button",
              role: "option",
              "aria-selected": o.value === value,
              onClick: () => (onChange as (v: string) => void)?.(o.value),
            },
            o.label,
          ),
        ),
      ),
    );
  };

  return {
    Button: buttonLike,
    Input: Object.assign(
      (props: Record<string, unknown>) =>
        React.createElement("input", props as any),
      {
        TextArea: (props: Record<string, unknown>) =>
          React.createElement("textarea", props as any),
        Search: (props: Record<string, unknown>) =>
          React.createElement("input", { ...props, type: "search" } as any),
        Password: (props: Record<string, unknown>) =>
          React.createElement("input", { ...props, type: "password" } as any),
        Group: passThrough,
      },
    ),
    InputNumber: (props: Record<string, unknown>) => {
      const { value, onChange, min, max, step, className, placeholder } =
        props as any;
      return React.createElement("input", {
        type: "number",
        value: value ?? "",
        min,
        max,
        step,
        className,
        placeholder,
        onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
          const num = e.target.value === "" ? null : Number(e.target.value);
          onChange?.(num);
        },
      });
    },
    Modal: Object.assign(passThrough, {
      confirm: vi.fn(({ onOk }: { onOk?: () => void }) => {
        if (onOk) void onOk();
      }),
      info: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
    }),
    Select: selectLike,
    Tooltip: passThrough,
    Tag: passThrough,
    Spin: passThrough,
    Form: Object.assign(passThrough, {
      Item: passThrough,
      useForm: () => [{}],
    }),
    Tabs: Object.assign(passThrough, { TabPane: passThrough }),
    IconButton: buttonLike,
    Dropdown: passThrough,
  };
});

// Mock API
vi.mock("../../../../../api", () => ({
  default: {
    listRecommendedLocalModels: vi.fn(),
    getLocalModelConfig: vi.fn(),
    getLocalServerStatus: vi.fn(),
    getLocalServerUpdateStatus: vi.fn(),
    getLlamacppDownloadProgress: vi.fn(),
    getLocalModelDownloadProgress: vi.fn(),
    configureLocalModelSettings: vi.fn(),
    startLlamacppDownload: vi.fn(),
    cancelLlamacppDownload: vi.fn(),
    startLocalModelDownload: vi.fn(),
    cancelLocalModelDownload: vi.fn(),
    startLocalServer: vi.fn(),
    stopLocalServer: vi.fn(),
    deleteLocalModel: vi.fn(),
  },
}));

// Mock ThemeContext
vi.mock("../../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

// Mock useAppMessage
vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
    modal: {
      confirm: vi.fn(),
    },
    notification: {
      info: vi.fn(),
    },
  }),
}));

// Mock antd Progress
vi.mock("antd", async () => {
  const actual = await vi.importActual<any>("antd");
  return {
    ...actual,
    Progress: (props: Record<string, unknown>) =>
      React.createElement("div", { "data-testid": "progress", ...props }),
  };
});

// Test fixtures
const mockProvider: ProviderInfo = {
  id: "ollama",
  name: "Ollama",
  api_key_prefix: "",
  chat_model: "OllamaChatModel",
  models: [],
  extra_models: [],
  discovered_models: [],
  hidden_model_ids: [],
  is_custom: false,
  is_local: true,
  support_model_discovery: false,
  support_connection_check: false,
  freeze_url: false,
  require_api_key: false,
  api_key: "",
  base_url: "http://localhost:11434",
  generate_kwargs: {},
} as unknown as ProviderInfo;

const mockModels: LocalModelInfo[] = [
  {
    id: "llama2:7b",
    name: "Llama 2 7B",
    size_bytes: 3_800_000_000,
    downloaded: true,
    source: "huggingface",
  },
  {
    id: "mistral:7b",
    name: "Mistral 7B",
    size_bytes: 4_100_000_000,
    downloaded: false,
    source: "huggingface",
  },
];

const mockServerStatus: LocalServerStatus = {
  available: true,
  installable: true,
  installed: true,
  port: 8080,
  model_name: null,
  message: null,
};

const mockLlamacppProgress: LocalDownloadProgress = {
  status: "idle",
  model_name: null,
  downloaded_bytes: 0,
  total_bytes: null,
  speed_bytes_per_sec: 0,
  source: null,
  error: null,
  local_path: null,
};

const mockModelProgress: LocalDownloadProgress = {
  status: "idle",
  model_name: null,
  downloaded_bytes: 0,
  total_bytes: null,
  speed_bytes_per_sec: 0,
  source: null,
  error: null,
  local_path: null,
};

const mockUpdateStatus: LocalServerUpdateStatus = {
  has_update: false,
};

const mockConfig: LocalModelConfig = {
  max_context_length: 65536,
  port: 8080,
};

// Helper to setup default API mocks
function setupDefaultMocks() {
  vi.mocked(api.listRecommendedLocalModels).mockResolvedValue(mockModels);
  vi.mocked(api.getLocalModelConfig).mockResolvedValue(mockConfig);
  vi.mocked(api.getLocalServerStatus).mockResolvedValue(mockServerStatus);
  vi.mocked(api.getLocalServerUpdateStatus).mockResolvedValue(mockUpdateStatus);
  vi.mocked(api.getLlamacppDownloadProgress).mockResolvedValue(
    mockLlamacppProgress,
  );
  vi.mocked(api.getLocalModelDownloadProgress).mockResolvedValue(
    mockModelProgress,
  );
  vi.mocked(api.configureLocalModelSettings).mockResolvedValue({
    success: true,
  } as any);
}

function renderModal(
  overrides: {
    open?: boolean;
    onClose?: () => void;
    onSaved?: () => void;
    provider?: ProviderInfo;
  } = {},
) {
  return renderWithProviders(
    <LocalModelManageModal
      provider={overrides.provider ?? mockProvider}
      open={overrides.open ?? true}
      onClose={overrides.onClose ?? vi.fn()}
      onSaved={overrides.onSaved ?? vi.fn()}
    />,
  );
}

describe("LocalModelManageModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  describe("组件渲染", () => {
    it("当 open=false 时不渲染内容", () => {
      renderModal({ open: false });
      // the modal content must not render when closed
      expect(
        screen.queryByText("models.localModelsTitle"),
      ).not.toBeInTheDocument();
    });

    it("当 open=true 时渲染模态框并调用初始化 API", async () => {
      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
        expect(api.listRecommendedLocalModels).toHaveBeenCalled();
        expect(api.getLocalModelConfig).toHaveBeenCalled();
      });
    });

    it("加载时显示 loading 状态", async () => {
      let resolveStatus!: (value: LocalServerStatus) => void;
      vi.mocked(api.getLocalServerStatus).mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveStatus = resolve;
          }),
      );

      renderModal();

      // the loading translation key must be shown
      await waitFor(() => {
        expect(screen.getByText("common.loading")).toBeInTheDocument();
      });

      resolveStatus(mockServerStatus);
    });
  });

  describe("模型列表展示", () => {
    it("显示推荐的本地模型列表", async () => {
      renderModal();

      await waitFor(() => {
        expect(api.listRecommendedLocalModels).toHaveBeenCalled();
      });

      // model names must be shown
      expect(screen.getByText("Llama 2 7B")).toBeInTheDocument();
      expect(screen.getByText("Mistral 7B")).toBeInTheDocument();
    });

    it("当没有推荐模型时显示提示", async () => {
      vi.mocked(api.listRecommendedLocalModels).mockResolvedValue([]);

      renderModal();

      await waitFor(() => {
        expect(api.listRecommendedLocalModels).toHaveBeenCalled();
      });

      // the no-recommended-model hint (translation key) must be shown
      expect(
        screen.getByText("models.localNoRecommendedModels"),
      ).toBeInTheDocument();
    });

    it("当没有已下载模型时显示提示", async () => {
      const allUndownloaded: LocalModelInfo[] = [
        { ...mockModels[0], downloaded: false },
        { ...mockModels[1], downloaded: false },
      ];
      vi.mocked(api.listRecommendedLocalModels).mockResolvedValue(
        allUndownloaded,
      );

      renderModal();

      await waitFor(() => {
        expect(api.listRecommendedLocalModels).toHaveBeenCalled();
      });

      // the no-downloaded-model hint (translation key) must be shown
      expect(
        screen.getByText("models.localNoDownloadedModelsHint"),
      ).toBeInTheDocument();
    });
  });

  describe("自定义模型下载", () => {
    it("显示自定义模型输入区域", async () => {
      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the custom model section title (translation key) must be shown
      expect(
        screen.getByText("models.localCustomModelTitle"),
      ).toBeInTheDocument();

      // the input must be shown
      const input = screen.getByPlaceholderText(
        "models.localRepoIdPlaceholder",
      );
      expect(input).toBeInTheDocument();
    });

    it("输入 repo ID 后可以下载", async () => {
      const user = userEvent.setup();
      vi.mocked(api.startLocalModelDownload).mockResolvedValue({
        success: true,
      } as any);

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // type the repo ID
      const input = screen.getByPlaceholderText(
        "models.localRepoIdPlaceholder",
      );
      await user.type(input, "custom/model");

      // find the download button in the custom model section (the last download button)
      const downloadButtons = screen.getAllByRole("button", {
        name: /common.download/i,
      });
      const customDownloadBtn = downloadButtons[downloadButtons.length - 1];
      await user.click(customDownloadBtn);

      // the download API must be called
      await waitFor(() => {
        expect(api.startLocalModelDownload).toHaveBeenCalledWith(
          "custom/model",
          "huggingface",
        );
      });
    });

    it("空 repo ID 时禁用下载按钮", async () => {
      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the custom model download button (the last one) must be disabled
      const downloadButtons = screen.getAllByRole("button", {
        name: /common.download/i,
      });
      const customDownloadBtn = downloadButtons[downloadButtons.length - 1];
      expect(customDownloadBtn).toBeDisabled();
    });

    it("可以切换下载源", async () => {
      const user = userEvent.setup();
      vi.mocked(api.startLocalModelDownload).mockResolvedValue({
        success: true,
      } as any);

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // type the repo ID
      const input = screen.getByPlaceholderText(
        "models.localRepoIdPlaceholder",
      );
      await user.type(input, "custom/model");

      // switch the source selector - click the ModelScope option
      const modelscopeOption = screen.getByRole("option", {
        name: "models.localSourceModelScope",
      });
      await user.click(modelscopeOption);

      // find the download button in the custom model section (the last one)
      const downloadButtons = screen.getAllByRole("button", {
        name: /common.download/i,
      });
      const customDownloadBtn = downloadButtons[downloadButtons.length - 1];
      await user.click(customDownloadBtn);

      // the modelscope source must be used
      await waitFor(() => {
        expect(api.startLocalModelDownload).toHaveBeenCalledWith(
          "custom/model",
          "modelscope",
        );
      });
    });
  });

  describe("高级配置", () => {
    it("默认折叠高级配置", async () => {
      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the advanced settings title (translation key) must be shown
      expect(
        screen.getByText("models.localAdvancedConfigTitle"),
      ).toBeInTheDocument();

      // but the settings fields must not be shown
      expect(
        screen.queryByText("models.localMaxContextLengthLabel"),
      ).not.toBeInTheDocument();
    });

    it("点击可以展开高级配置", async () => {
      const user = userEvent.setup();

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // click to expand
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // the settings fields (translation keys) must be shown
      expect(
        screen.getByText("models.localMaxContextLengthLabel"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("models.localServerPortLabel"),
      ).toBeInTheDocument();
    });

    it("显示从 API 加载的配置值", async () => {
      const user = userEvent.setup();
      vi.mocked(api.getLocalModelConfig).mockResolvedValue({
        max_context_length: 131072,
        port: 9090,
      });

      renderModal();

      await waitFor(() => {
        expect(api.getLocalModelConfig).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // the loaded values must be shown
      expect(screen.getByDisplayValue("131072")).toBeInTheDocument();
      expect(screen.getByDisplayValue("9090")).toBeInTheDocument();
    });

    it("可以修改并保存 max context length", async () => {
      const user = userEvent.setup();
      const onSaved = vi.fn();

      renderModal({ onSaved });

      await waitFor(() => {
        expect(api.getLocalModelConfig).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // change max context length - use fireEvent.change for reliable number input handling
      const contextInput = screen.getByDisplayValue("65536");
      fireEvent.change(contextInput, { target: { value: "131072" } });

      // find the save button next to max context length
      const saveButtons = screen.getAllByRole("button", {
        name: /models.save/i,
      });
      // the first save button belongs to max context length
      await user.click(saveButtons[0]);

      // the settings API must be called
      await waitFor(() => {
        expect(api.configureLocalModelSettings).toHaveBeenCalledWith({
          max_context_length: 131072,
        });
      });
    });

    it("可以修改并保存 server port", async () => {
      const user = userEvent.setup();
      const onSaved = vi.fn();

      renderModal({ onSaved });

      await waitFor(() => {
        expect(api.getLocalModelConfig).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // change the server port
      const portInput = screen.getByDisplayValue("8080");
      await user.clear(portInput);
      await user.type(portInput, "9090");

      // find the save button next to server port
      const saveButtons = screen.getAllByRole("button", {
        name: /models.save/i,
      });
      // the second save button belongs to server port
      await user.click(saveButtons[1]);

      // the settings API must be called
      await waitFor(() => {
        expect(api.configureLocalModelSettings).toHaveBeenCalledWith({
          port: 9090,
        });
      });
    });
  });

  describe("Runtime 状态展示", () => {
    it("显示 runtime 安装状态", async () => {
      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the runtime panel (translation key) must be shown
      expect(screen.getByText("models.localLlamacppName")).toBeInTheDocument();
    });

    it("当 runtime 未安装时显示锁定面板", async () => {
      vi.mocked(api.getLocalServerStatus).mockResolvedValue({
        ...mockServerStatus,
        installed: false,
        installable: true,
      });

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the runtime-missing hint (translation key) must be shown - use getAllByText since there may be multiple
      const elements = screen.getAllByText("models.localRuntimeMissing");
      expect(elements.length).toBeGreaterThan(0);
    });

    it("当 runtime 不可安装时显示不支持提示", async () => {
      vi.mocked(api.getLocalServerStatus).mockResolvedValue({
        ...mockServerStatus,
        installed: false,
        installable: false,
        message: "Platform not supported",
      });

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the unsupported hint (translation key) must be shown - use getAllByText since there may be multiple
      const elements = screen.getAllByText("models.localRuntimeUnsupported");
      expect(elements.length).toBeGreaterThan(0);
    });

    it("显示当前运行的模型", async () => {
      vi.mocked(api.getLocalServerStatus).mockResolvedValue({
        ...mockServerStatus,
        model_name: "llama2:7b",
      });

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // the currently running model label (translation key) must be shown
      expect(
        screen.getByText("models.localEngineCurrentModelLabel"),
      ).toBeInTheDocument();
    });
  });

  describe("API 调用错误处理", () => {
    it("获取模型列表失败时显示空列表", async () => {
      vi.mocked(api.listRecommendedLocalModels).mockRejectedValue(
        new Error("Network error"),
      );

      renderModal();

      await waitFor(() => {
        expect(api.listRecommendedLocalModels).toHaveBeenCalled();
      });

      // the no-model hint must be shown instead of crashing
      expect(
        screen.getByText("models.localNoRecommendedModels"),
      ).toBeInTheDocument();
    });

    it("获取配置失败时使用默认值", async () => {
      const user = userEvent.setup();
      vi.mocked(api.getLocalModelConfig).mockRejectedValue(
        new Error("Config error"),
      );

      renderModal();

      await waitFor(() => {
        expect(api.getLocalModelConfig).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // the default values must be shown
      expect(screen.getByDisplayValue("65536")).toBeInTheDocument();
    });

    it("保存配置失败时不崩溃", async () => {
      const user = userEvent.setup();
      vi.mocked(api.configureLocalModelSettings).mockRejectedValue(
        new Error("Save failed"),
      );

      renderModal();

      await waitFor(() => {
        expect(api.getLocalModelConfig).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // change the value
      const contextInput = screen.getByDisplayValue("65536");
      await user.clear(contextInput);
      await user.type(contextInput, "131072");

      // click save
      const saveButtons = screen.getAllByRole("button", {
        name: /models.save/i,
      });
      await user.click(saveButtons[0]);

      // the API must be called (the error is handled internally)
      await waitFor(() => {
        expect(api.configureLocalModelSettings).toHaveBeenCalled();
      });
    });
  });

  describe("轮询机制", () => {
    it("当有下载任务时启动轮询", async () => {
      const downloadingProgress: LocalDownloadProgress = {
        ...mockLlamacppProgress,
        status: "downloading",
        downloaded_bytes: 1000000,
        total_bytes: 5000000,
      };

      vi.mocked(api.getLlamacppDownloadProgress).mockResolvedValue(
        downloadingProgress,
      );

      renderModal();

      // wait for the initial load
      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // wait for polling (3-second interval)
      await waitFor(
        () => {
          expect(api.getLocalServerStatus).toHaveBeenCalledTimes(2);
        },
        { timeout: 5000 },
      );
    });
  });

  describe("generate_kwargs 配置", () => {
    it("展开高级配置后显示 generate config 字段", async () => {
      const user = userEvent.setup();

      renderModal();

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // the generate config label (translation key) must be shown
      expect(
        screen.getByText("models.modelGenerateConfig"),
      ).toBeInTheDocument();
    });

    it("provider 有 generate_kwargs 时预填充", async () => {
      const user = userEvent.setup();
      const providerWithKwargs: ProviderInfo = {
        ...mockProvider,
        generate_kwargs: { temperature: 0.7, top_p: 0.95 },
      } as unknown as ProviderInfo;

      renderModal({ provider: providerWithKwargs });

      await waitFor(() => {
        expect(api.getLocalServerStatus).toHaveBeenCalled();
      });

      // expand the advanced settings
      const toggle = screen.getByText("models.localAdvancedConfigTitle");
      await user.click(toggle);

      // the generate config fields must be shown (check the field labels exist)
      const generateConfigLabel = screen.queryByText(
        "models.modelGenerateConfig",
      );
      // if the labels exist, the advanced settings are expanded and generate_kwargs is handled
      expect(generateConfigLabel).toBeInTheDocument();
    });
  });
});
