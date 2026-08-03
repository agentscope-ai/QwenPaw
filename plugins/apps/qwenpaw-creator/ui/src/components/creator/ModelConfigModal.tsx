import { useState, useEffect, useCallback, useRef } from "react";
import {
  Modal,
  Input,
  Select,
  Checkbox,
  Button,
  message,
  AutoComplete,
} from "antd";
import { Brain } from "lucide-react";
import {
  SettingOutlined,
  LinkOutlined,
  SaveOutlined,
  DownOutlined,
  EyeOutlined,
  PictureOutlined,
  VideoCameraOutlined,
  AudioOutlined,
  GlobalOutlined,
  ReloadOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import {
  getModelConfig,
  saveModelConfig,
  patchExecutionAuthorization,
  testModelConnection,
  getHostProviders,
  getHostProviderApiKey,
  getRealApiKey,
} from "@/api/creator";
import type { HostProviderInfo } from "@/api/creator";
import type {
  GroundingConfig,
  ModelConfigData,
  ModelConfigItem,
} from "@/contracts/creator";
import ModelSetupGuide from "@/components/onboarding/ModelSetupGuide";

const LLM_PROTOCOLS = [
  "Anthropic Claude",
  "DashScope（百炼）",
  "Aliyun Token Plan",
  "Aliyun Coding Plan",
  "DeepSeek",
  "Google Gemini",
  "OpenAI 协议",
  "Azure OpenAI",
  "MiniMax",
  "Kimi（月之暗面）",
  "智谱 AI",
  "SiliconFlow（硅基流动）",
  "ModelScope（魔搭）",
  "百度千帆",
  "Volcano Engine（火山引擎）",
  "小米 MiMo",
  "自定义",
];
const VLM_PROTOCOLS = [
  "Anthropic Claude",
  "DashScope（百炼）",
  "Aliyun Token Plan",
  "Aliyun Coding Plan",
  "DeepSeek",
  "Google Gemini",
  "OpenAI 协议",
  "Azure OpenAI",
  "MiniMax",
  "Kimi（月之暗面）",
  "智谱 AI",
  "SiliconFlow（硅基流动）",
  "ModelScope（魔搭）",
  "百度千帆",
  "Volcano Engine（火山引擎）",
  "小米 MiMo",
  "自定义",
];
const ASR_PROTOCOLS = ["DashScope Fun-ASR", "OpenAI Whisper"];
const IMAGE_PROTOCOLS = ["OpenAI 协议", "DashScope（百炼）"];
const VIDEO_PROTOCOLS = ["DashScope（百炼）", "Volcano Engine（火山引擎）"];

interface ProtocolPreset {
  base_url: string;
  freeze_url: boolean;
  models: string[];
  base_url_options?: { label: string; value: string }[];
}

const PROTOCOL_TO_PROVIDER_ID: Record<string, string> = {
  "DashScope（百炼）": "dashscope",
  "Aliyun Token Plan": "aliyun-tokenplan",
  "Aliyun Coding Plan": "aliyun-codingplan",
  DeepSeek: "deepseek",
  "OpenAI 协议": "openai",
  "Azure OpenAI": "azure-openai",
  "Anthropic Claude": "anthropic",
  "Google Gemini": "gemini",
  MiniMax: "minimax-cn",
  "Kimi（月之暗面）": "kimi-cn",
  "智谱 AI": "zhipu-cn",
  "SiliconFlow（硅基流动）": "siliconflow-cn",
  "ModelScope（魔搭）": "modelscope",
  百度千帆: "qianfan",
  "Volcano Engine（火山引擎）": "volcengine-cn",
  "小米 MiMo": "mimo-tokenplan",
};

const ASR_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope Fun-ASR": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    freeze_url: true,
    models: ["fun-asr"],
  },
  "OpenAI Whisper": {
    base_url: "https://api.openai.com/v1",
    freeze_url: true,
    models: ["whisper-1"],
  },
};

const IMAGE_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    freeze_url: true,
    models: [
      "wan2.7-image-pro",
      "wan2.7-image",
      "wan2.6-t2i",
      "wan2.6-image",
      "wan2.5-t2i-preview",
      "wan2.2-t2i-plus",
      "wan2.2-t2i-flash",
      "wan2.1-t2i-plus",
      "wan2.1-t2i-turbo",
      "qwen-image-3.0-pro",
      "qwen-image-2.0-pro",
      "qwen-image-2.0",
      "qwen-image-max",
      "qwen-image-plus",
      "z-image-turbo",
    ],
  },
  "OpenAI 协议": {
    base_url: "https://api.openai.com/v1",
    freeze_url: true,
    models: ["gpt-image-2"],
  },
};

const VIDEO_PRESETS: Record<string, ProtocolPreset> = {
  "DashScope（百炼）": {
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    freeze_url: true,
    models: [
      "wan2.7-r2v",
      "wan2.6-r2v-flash",
      "wan2.6-r2v",
      "happyhorse-1.1-r2v",
    ],
  },
  "Volcano Engine（火山引擎）": {
    base_url: "https://ark.cn-beijing.volces.com",
    freeze_url: true,
    models: ["doubao-seedance-2.0-pro", "doubao-seedance-2.0-lite"],
  },
};

type ModelType = "llm" | "vlm" | "asr" | "image" | "video";
type TabType = ModelType | "grounding";
const DEFAULT_CONFIG: ModelConfigData = {
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
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope Fun-ASR",
    custom_protocol: "",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
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
  executionAuthorization: { mode: "required" },
};

function hasUsableApiKey(item: ModelConfigItem): boolean {
  return item.api_key !== undefined && item.api_key.length > 0;
}

function groundingValidationModel(config: ModelConfigData): ModelConfigItem {
  if (config.grounding.validation_source === "llm") return config.llm;
  if (config.grounding.validation_source === "vlm") {
    return config.vlm.use_llm ? config.llm : config.vlm;
  }
  return config.grounding;
}

function groundingSearchModel(config: ModelConfigData): ModelConfigItem {
  if (config.grounding.search_reuse_llm) return config.llm;
  return {
    enabled: config.grounding.native_search_enabled,
    model_name: config.grounding.search_model_name,
    api_key: config.grounding.search_api_key,
    base_url: config.grounding.search_base_url,
    protocol: config.grounding.search_protocol,
    custom_protocol: "",
  };
}

/**
 * Check whether a model's protocol/host indicates DashScope/Qwen native
 * search capability. Mirrors the backend ``dashscope_native_search_unavailable_reason``
 * hostname extraction so UI and server agree on edge-case URLs.
 */
export function supportsQwenNativeSearch(item: ModelConfigItem): boolean {
  const protocol = item.protocol.toLocaleLowerCase();
  if (protocol.includes("dashscope") || item.protocol.includes("百炼"))
    return true;
  try {
    const host = new URL(item.base_url).hostname.toLocaleLowerCase();
    return host.includes("dashscope");
  } catch {
    return false;
  }
}

function groundingSearchLabel(config: ModelConfigData): string {
  const providers: string[] = [];
  if (config.grounding.tavily_api_key) providers.push("tavily");
  const searchModel = groundingSearchModel(config);
  if (
    config.grounding.native_search_enabled &&
    searchModel.model_name &&
    supportsQwenNativeSearch(searchModel)
  ) {
    providers.push(searchModel.model_name);
  }
  return providers.join("/");
}

interface Props {
  open: boolean;
  onClose: () => void;
}

const CARD_META: {
  type: TabType;
  label: string;
  icon: React.ReactNode;
  required: boolean;
}[] = [
  {
    type: "llm",
    label: "LLM 模型",
    icon: <Brain size={16} style={{ color: "var(--color-accent)" }} />,
    required: true,
  },
  {
    type: "vlm",
    label: "VLM 模型",
    icon: (
      <EyeOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "grounding",
    label: "Grounding",
    icon: (
      <GlobalOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "asr",
    label: "ASR 模型",
    icon: (
      <AudioOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "image",
    label: "图片生成模型",
    icon: (
      <PictureOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
  {
    type: "video",
    label: "视频生成模型",
    icon: (
      <VideoCameraOutlined
        style={{ color: "var(--color-text-tertiary)", fontSize: 16 }}
      />
    ),
    required: false,
  },
];

export default function ModelConfigModal({ open, onClose }: Props) {
  const [config, setConfig] = useState<ModelConfigData>(DEFAULT_CONFIG);
  const snapshotRef = useRef<ModelConfigData | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("llm");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    llm: true,
  });
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [tested, setTested] = useState<Record<string, boolean>>({});
  const [testingLlmMultimodal, setTestingLlmMultimodal] = useState(false);
  const [testingVlmMultimodal, setTestingVlmMultimodal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [hostProviders, setHostProviders] = useState<HostProviderInfo[]>([]);

  useEffect(() => {
    getHostProviders().then(setHostProviders);
  }, []);

  // Resolve the real API key (for connection tests).
  const resolveRealApiKey = async (
    section: string,
    item?: ModelConfigItem,
  ): Promise<string> => {
    // Use the key the frontend already holds when it is real (not the
    // mask and not empty).
    if (item && item.api_key && item.api_key !== "__CREATOR_SECRET__") {
      return item.api_key;
    }

    // Otherwise fetch it from the backend.
    try {
      const result = await getRealApiKey(section);
      return result.api_key;
    } catch {
      return "";
    }
  };

  const loadConfig = useCallback(async () => {
    try {
      const data = await getModelConfig();
      const receivedGrounding = data.grounding as Partial<GroundingConfig>;
      const validationSource =
        receivedGrounding.validation_source ??
        (receivedGrounding.reuse_llm === false ? "custom" : "llm");
      const merged: ModelConfigData = {
        ...DEFAULT_CONFIG,
        ...data,
        grounding: {
          ...DEFAULT_CONFIG.grounding,
          ...data.grounding,
          validation_source: validationSource,
          reuse_llm: validationSource === "llm",
          search_reuse_llm:
            receivedGrounding.search_reuse_llm ??
            receivedGrounding.reuse_llm ??
            true,
        },
        oss: { ...DEFAULT_CONFIG.oss, ...data.oss },
        executionAuthorization: {
          ...DEFAULT_CONFIG.executionAuthorization,
          ...data.executionAuthorization,
        },
      };
      if (!VLM_PROTOCOLS.includes(merged.vlm.protocol))
        merged.vlm.protocol = VLM_PROTOCOLS[0];
      if (!ASR_PROTOCOLS.includes(merged.asr.protocol))
        merged.asr.protocol = ASR_PROTOCOLS[0];
      if (!IMAGE_PROTOCOLS.includes(merged.image.protocol))
        merged.image.protocol = IMAGE_PROTOCOLS[0];
      if (!VIDEO_PROTOCOLS.includes(merged.video.protocol))
        merged.video.protocol = VIDEO_PROTOCOLS[0];
      const initialTested: Record<string, boolean> = {};
      CARD_META.forEach((meta) => {
        if (meta.type === "grounding") return;
        const item = merged[meta.type] as ModelConfigItem;
        if (item?.enabled) initialTested[meta.type] = true;
      });
      setConfig(merged);
      setTested(initialTested);
      snapshotRef.current = JSON.parse(JSON.stringify(merged));
    } catch {
      setConfig(DEFAULT_CONFIG);
      snapshotRef.current = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
    }
  }, []);

  useEffect(() => {
    if (open) {
      loadConfig();
      setActiveTab("llm");
      setExpanded({ llm: true });
    }
  }, [open, loadConfig]);

  const handleReload = useCallback(async () => {
    if (reloading) return;
    setReloading(true);
    try {
      await loadConfig();
      message.success("配置已重新加载");
    } catch (err) {
      message.error((err as Error).message || "重新加载配置时发生错误");
    } finally {
      setReloading(false);
    }
  }, [loadConfig, reloading]);

  const updateItem = useCallback(
    (type: ModelType, field: string, value: unknown) => {
      setConfig((prev) => {
        const updated = { ...prev, [type]: { ...prev[type], [field]: value } };
        if (type === "llm" && prev.vlm.use_llm) {
          updated.vlm = { ...updated.vlm, use_llm: false, enabled: false };
        }
        if (
          type === "vlm" &&
          field !== "enabled" &&
          prev.vlm.enabled &&
          !prev.vlm.use_llm
        ) {
          updated.vlm = { ...updated.vlm, enabled: false };
        }
        return updated;
      });
      if (field !== "enabled") {
        setTested((prev) => ({ ...prev, [type]: false }));
        if (type === "llm" || type === "vlm") {
          setTested((prev) => ({
            ...prev,
            groundingValidation: false,
            groundingSearch:
              type === "llm" && config.grounding.search_reuse_llm
                ? false
                : prev.groundingSearch,
          }));
        }
      }
    },
    [config.grounding.search_reuse_llm],
  );

  const updateGrounding = useCallback(
    (field: keyof GroundingConfig, value: unknown) => {
      setConfig((prev) => ({
        ...prev,
        grounding: { ...prev.grounding, [field]: value },
      }));
      if (
        field === "reuse_llm" ||
        field === "validation_source" ||
        field === "api_key" ||
        field === "base_url" ||
        field === "model_name" ||
        field === "protocol"
      ) {
        setTested((prev) => ({ ...prev, groundingValidation: false }));
      }
      if (
        field === "tavily_api_key" ||
        field === "native_search_enabled" ||
        field === "search_reuse_llm" ||
        field === "search_api_key" ||
        field === "search_base_url" ||
        field === "search_model_name" ||
        field === "search_protocol"
      ) {
        setTested((prev) => ({ ...prev, groundingSearch: false }));
      }
    },
    [],
  );

  const toggleExpand = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleTabChange = useCallback((tab: TabType) => {
    setActiveTab(tab);
    setExpanded((prev) => ({ ...prev, [tab]: true }));
  }, []);

  const handleVlmToggle = useCallback(
    async (enabled: boolean) => {
      if (!enabled) {
        setConfig((prev) => ({
          ...prev,
          vlm: { ...prev.vlm, enabled: false },
        }));
        setTested((prev) => ({ ...prev, vlm: false }));
        return;
      }

      if (config.vlm.use_llm) {
        setConfig((prev) => ({ ...prev, vlm: { ...prev.vlm, enabled: true } }));
        return;
      }

      const vlmItem = config.vlm;
      if (
        !vlmItem.base_url ||
        !vlmItem.model_name ||
        !hasUsableApiKey(vlmItem)
      ) {
        message.warning(
          "请先填写完整的 VLM 模型配置（Base URL、API Key、模型名称）",
        );
        return;
      }

      setTestingVlmMultimodal(true);
      try {
        const data = await testModelConnection({
          type: "vlm",
          base_url: vlmItem.base_url,
          api_key: vlmItem.api_key,
          model_name: vlmItem.model_name,
          protocol: vlmItem.protocol,
        });
        if (data.ok) {
          message.success("多模态测试通过，已启用 VLM");
          setTested((prev) => ({ ...prev, vlm: true }));
          setConfig((prev) => ({
            ...prev,
            vlm: { ...prev.vlm, enabled: true, multimodal: true },
          }));
        } else {
          message.warning(data.error || "多模态测试失败，该模型不支持图片输入");
          setTested((prev) => ({ ...prev, vlm: false }));
        }
      } catch (err) {
        message.error((err as Error).message || "测试多模态时发生错误");
        setTested((prev) => ({ ...prev, vlm: false }));
      } finally {
        setTestingVlmMultimodal(false);
      }
    },
    [config],
  );

  const handleVlmUseLlm = useCallback(
    async (checked: boolean) => {
      if (!checked) {
        setConfig((prev) => ({
          ...prev,
          vlm: { ...prev.vlm, use_llm: false },
        }));
        return;
      }

      const llmItem = config.llm;
      if (
        !llmItem.base_url ||
        !llmItem.model_name ||
        !hasUsableApiKey(llmItem)
      ) {
        message.warning(
          "请先填写完整的 LLM 模型配置（Base URL、API Key、模型名称）",
        );
        return;
      }

      setTestingLlmMultimodal(true);
      try {
        // Resolve the real API key (the frontend only stores the mask).
        const realApiKey = await resolveRealApiKey("llm", llmItem);
        const data = await testModelConnection({
          type: "vlm",
          base_url: llmItem.base_url,
          api_key: realApiKey,
          model_name: llmItem.model_name,
          protocol: llmItem.protocol,
        });
        if (data.ok) {
          message.success("多模态测试通过，已复用 LLM 配置");
          setTested((prev) => ({ ...prev, vlm: true, llm: true }));
          setConfig((prev) => ({
            ...prev,
            llm: { ...prev.llm, multimodal: true },
            vlm: { ...prev.vlm, use_llm: true, enabled: true },
          }));
        } else {
          message.warning(
            data.error ||
              "多模态测试失败，该模型不支持图片输入，无法复用 LLM 配置",
          );
          setTested((prev) => ({ ...prev, vlm: false }));
        }
      } catch (err) {
        message.error((err as Error).message || "测试多模态时发生错误");
        setTested((prev) => ({ ...prev, vlm: false }));
      } finally {
        setTestingLlmMultimodal(false);
      }
    },
    [config],
  );

  const handleTest = useCallback(
    async (type: ModelType): Promise<boolean> => {
      let item = config[type] as ModelConfigItem;
      if (type === "vlm" && config.vlm.use_llm) {
        item = config.llm;
      }
      const hasKey =
        type === "asr" && config.asr.reuse_llm_key
          ? hasUsableApiKey(config.llm)
          : hasUsableApiKey(item);
      if (!item.base_url || !hasKey || !item.model_name) {
        message.warning(
          "请先填写完整的模型配置（Base URL、API Key、模型名称）",
        );
        return false;
      }

      setTesting((prev) => ({ ...prev, [type]: true }));
      try {
        // Resolve the real API key (the frontend only stores the mask).
        let testApiKey: string;
        if (type === "asr" && config.asr.reuse_llm_key) {
          // ASR reuses the LLM API key.
          testApiKey = await resolveRealApiKey("llm", config.llm);
        } else if (type === "vlm" && config.vlm.use_llm) {
          // VLM reuses the LLM config.
          testApiKey = await resolveRealApiKey("llm", config.llm);
        } else {
          // Use the API key of the current section.
          testApiKey = await resolveRealApiKey(type, item);
        }

        const data = await testModelConnection({
          type,
          base_url: item.base_url,
          api_key: testApiKey,
          model_name: item.model_name,
          protocol: item.protocol,
          provider: type === "asr" ? config.asr.provider : undefined,
        });
        if (data.ok) {
          message.success("连接测试成功");
          setTested((prev) => ({ ...prev, [type]: true }));
          updateItem(type, "enabled", true);
          return true;
        } else {
          message.warning(data.error || "连接测试失败");
          setTested((prev) => ({ ...prev, [type]: false }));
          return false;
        }
      } catch (err) {
        message.error((err as Error).message || "测试连接时发生错误");
        setTested((prev) => ({ ...prev, [type]: false }));
        return false;
      } finally {
        setTesting((prev) => ({ ...prev, [type]: false }));
      }
    },
    [config, updateItem],
  );

  const handleGroundingTest = useCallback(async (): Promise<boolean> => {
    const item = groundingValidationModel(config);
    if (!item.base_url || !hasUsableApiKey(item) || !item.model_name) {
      message.warning(
        "请完整配置 Grounding 验证模型（Base URL、API Key、模型名称）",
      );
      return false;
    }

    setTesting((prev) => ({ ...prev, grounding: true }));
    try {
      // Resolve the real API key (the frontend only stores the mask),
      // picking the section that matches the validation model source.
      let realApiKey = item.api_key;
      if (config.grounding.validation_source === "llm") {
        realApiKey = await resolveRealApiKey("llm", config.llm);
      } else if (config.grounding.validation_source === "vlm") {
        const vlmSection = config.vlm.use_llm ? "llm" : "vlm";
        const vlmItem = config.vlm.use_llm ? config.llm : config.vlm;
        realApiKey = await resolveRealApiKey(vlmSection, vlmItem);
      } else {
        realApiKey = await resolveRealApiKey("grounding", item);
      }

      const data = await testModelConnection({
        type: "vlm",
        base_url: item.base_url,
        api_key: realApiKey,
        model_name: item.model_name,
        protocol: item.protocol,
      });
      if (!data.ok) {
        message.warning(data.error || "Grounding LLM 图片输入测试失败");
        setTested((prev) => ({ ...prev, groundingValidation: false }));
        return false;
      }
      message.success("Grounding LLM 图片输入测试成功");
      setTested((prev) => ({ ...prev, groundingValidation: true }));
      return true;
    } catch (err) {
      message.error((err as Error).message || "测试 Grounding LLM 时发生错误");
      setTested((prev) => ({ ...prev, groundingValidation: false }));
      return false;
    } finally {
      setTesting((prev) => ({ ...prev, grounding: false }));
    }
  }, [config]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const prev = snapshotRef.current;
      if (!prev) throw new Error("快照丢失，请重新打开配置");

      if (config.grounding.enabled) {
        const groundingModel = groundingValidationModel(config);
        if (
          !groundingModel.base_url ||
          !groundingModel.model_name ||
          !hasUsableApiKey(groundingModel)
        ) {
          message.warning(
            "Grounding 默认开启，请完整配置验证模型，或关闭 Grounding",
          );
          return;
        }
        const searchModel = groundingSearchModel(config);
        const nativeSearchReady =
          config.grounding.native_search_enabled &&
          !!searchModel.base_url &&
          !!searchModel.model_name &&
          hasUsableApiKey(searchModel) &&
          supportsQwenNativeSearch(searchModel);
        if (!config.grounding.tavily_api_key && !nativeSearchReady) {
          message.warning(
            "Grounding 搜索未配置：请填写 Tavily API Key，或配置支持原生搜索的 Qwen/DashScope 模型",
          );
          return;
        }
      }

      const dirtySections: TabType[] = [];
      for (const section of [
        "llm",
        "vlm",
        "grounding",
        "asr",
        "image",
        "video",
      ] as TabType[]) {
        if (JSON.stringify(config[section]) !== JSON.stringify(prev[section])) {
          dirtySections.push(section);
        }
      }

      for (const section of dirtySections) {
        if (section !== "grounding" && !tested[section]) {
          const ok = await handleTest(section);
          if (!ok) return;
        }
      }

      if (dirtySections.length > 0) {
        // Save everything in one POST: sequential per-section PATCHes each
        // re-validate the full grounding config, so interdependent edits
        // (e.g. a generic LLM plus a Tavily key) could fail mid-sequence
        // and leave a partially saved configuration behind.
        const res = await saveModelConfig(config);
        if (!res.ok) throw new Error("保存失败：服务端未确认写入");
      }

      message.success("配置已保存");
      snapshotRef.current = JSON.parse(JSON.stringify(config));
      onClose();
    } catch (error) {
      const detail = error instanceof Error ? error.message : "未知错误";
      message.error(`保存失败：${detail}`);
    } finally {
      setSaving(false);
    }
  }, [config, tested, saving, handleTest, onClose]);

  const handleCancel = useCallback(() => {
    if (snapshotRef.current)
      setConfig(JSON.parse(JSON.stringify(snapshotRef.current)));
    onClose();
  }, [onClose]);

  const protocolsFor = (type: ModelType) =>
    type === "llm"
      ? LLM_PROTOCOLS
      : type === "vlm"
      ? VLM_PROTOCOLS
      : type === "asr"
      ? ASR_PROTOCOLS
      : type === "image"
      ? IMAGE_PROTOCOLS
      : VIDEO_PROTOCOLS;

  const getPresetForType = (
    type: ModelType,
    protocol: string,
  ): ProtocolPreset | null => {
    if (type === "llm" || type === "vlm") {
      const providerId = PROTOCOL_TO_PROVIDER_ID[protocol];
      if (!providerId) return null;
      const provider = hostProviders.find((p) => p.id === providerId);
      if (!provider) return null;
      return {
        base_url: provider.base_url,
        freeze_url: provider.freeze_url,
        models: [
          ...provider.models.map((m) => m.id),
          ...provider.extra_models.map((m) => m.id),
        ],
        base_url_options: provider.meta?.base_url_options,
      };
    }
    if (type === "asr") return ASR_PRESETS[protocol] || null;
    if (type === "image") return IMAGE_PRESETS[protocol] || null;
    if (type === "video") return VIDEO_PRESETS[protocol] || null;
    return null;
  };

  const getModelOptions = (
    type: ModelType,
    protocol: string,
  ): { value: string; label: string }[] => {
    if (type === "llm" || type === "vlm") {
      const providerId = PROTOCOL_TO_PROVIDER_ID[protocol];
      if (!providerId) return [];
      const provider = hostProviders.find((p) => p.id === providerId);
      if (!provider) return [];
      return [
        ...provider.models.map((m) => ({ value: m.id, label: m.id })),
        ...provider.extra_models.map((m) => ({ value: m.id, label: m.id })),
      ];
    }
    const preset = getPresetForType(type, protocol);
    if (!preset?.models.length) return [];
    return preset.models.map((m) => ({ value: m, label: m }));
  };

  const handleProtocolChange = async (type: ModelType, protocol: string) => {
    updateItem(type, "protocol", protocol);
    const preset = getPresetForType(type, protocol);
    if (preset) {
      if (preset.base_url_options?.length) {
        updateItem(type, "base_url", preset.base_url_options[0].value);
      } else if (preset.base_url !== undefined) {
        updateItem(type, "base_url", preset.base_url);
      }
      if (preset.models.length > 0) {
        const currentModel = (config[type] as ModelConfigItem).model_name;
        if (!preset.models.includes(currentModel)) {
          updateItem(type, "model_name", preset.models[0]);
        }
      }
    }

    // For LLM/VLM on their first configuration (empty api_key), try to
    // sync the API key from the host.
    if ((type === "llm" || type === "vlm") && protocol !== "自定义") {
      const currentItem = config[type] as ModelConfigItem;
      // Only sync on first configuration (api_key is empty).
      if (
        !currentItem.api_key ||
        currentItem.api_key === "__CREATOR_SECRET__"
      ) {
        const providerId = PROTOCOL_TO_PROVIDER_ID[protocol];
        if (providerId) {
          try {
            const result = await getHostProviderApiKey(providerId);
            if (result.api_key) {
              updateItem(type, "api_key", result.api_key);
            }
          } catch (error) {
            console.warn(
              `Failed to sync API key from host for ${providerId}:`,
              error,
            );
          }
        }
      }
    }

    if (type === "asr") {
      const provider = protocol === "OpenAI Whisper" ? "whisper" : "fun-asr";
      updateItem("asr", "provider", provider);
    }
  };

  const renderFields = (type: ModelType) => {
    const item = config[type] as ModelConfigItem;
    const preset = getPresetForType(type, item.protocol);
    const modelOptions = getModelOptions(type, item.protocol);
    const hasPresetModels = modelOptions.length > 0;
    const urlDisabled = preset?.freeze_url || false;
    const hasBaseUrlOptions = (preset?.base_url_options?.length ?? 0) > 0;

    return (
      <>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "0 16px",
          }}
        >
          <div>
            <label className="field-label">模型名称</label>
            {hasPresetModels ? (
              <AutoComplete
                value={item.model_name}
                onChange={(v) => updateItem(type, "model_name", v)}
                options={modelOptions}
                filterOption={(inputValue, option) =>
                  (option?.label as string)
                    ?.toLowerCase()
                    .includes(inputValue.toLowerCase()) ||
                  (option?.value as string)
                    ?.toLowerCase()
                    .includes(inputValue.toLowerCase())
                }
                placeholder="选择或输入模型"
              />
            ) : (
              <Input
                placeholder="model"
                value={item.model_name}
                onChange={(e) => updateItem(type, "model_name", e.target.value)}
              />
            )}
          </div>
          <div>
            <label className="field-label">API Key</label>
            <Input.Password
              placeholder={
                item.api_key === "__CREATOR_SECRET__" ? "已配置" : "sk-..."
              }
              value={
                item.api_key === "__CREATOR_SECRET__" ? "sk-****" : item.api_key
              }
              onChange={(e) => updateItem(type, "api_key", e.target.value)}
            />
          </div>
          <div>
            <label className="field-label">Base URL</label>
            {hasBaseUrlOptions ? (
              <Select
                value={item.base_url}
                onChange={(v) => updateItem(type, "base_url", v)}
                options={preset!.base_url_options!.map((opt) => ({
                  value: opt.value,
                  label: opt.label,
                }))}
                style={{ width: "100%" }}
              />
            ) : (
              <Input
                placeholder="https://api.example.com"
                value={item.base_url}
                disabled={urlDisabled}
                onChange={(e) => updateItem(type, "base_url", e.target.value)}
              />
            )}
          </div>
          <div>
            <label className="field-label">API 协议</label>
            <Select
              value={item.protocol}
              onChange={(v) => handleProtocolChange(type, v)}
              options={protocolsFor(type).map((p) => ({ value: p, label: p }))}
            />
            {item.protocol === "自定义" && (
              <Input
                className="mt-2"
                placeholder="输入协议名称"
                value={item.custom_protocol}
                onChange={(e) =>
                  updateItem(type, "custom_protocol", e.target.value)
                }
              />
            )}
          </div>
        </div>
        {type === "asr" && (
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <Checkbox
              checked={config.asr.reuse_llm_key}
              onChange={(e) =>
                updateItem("asr", "reuse_llm_key", e.target.checked)
              }
            >
              复用 LLM API Key
            </Checkbox>
            <Input
              style={{ width: 220 }}
              placeholder="语言（可选，如 zh）"
              value={config.asr.language}
              onChange={(e) => updateItem("asr", "language", e.target.value)}
            />
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Button
            className="test-btn"
            icon={<LinkOutlined />}
            loading={testing[type]}
            onClick={() => handleTest(type)}
          >
            测试连通性
          </Button>
        </div>
      </>
    );
  };

  const toggleControl = (type: ModelType) => {
    if (type === "llm") return null;
    const item = config[type] as ModelConfigItem;
    const testing = type === "vlm" && testingVlmMultimodal;
    return (
      <>
        <label className="desktop-toggle" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={item.enabled}
            disabled={testing}
            onChange={(e) => {
              if (type === "vlm") handleVlmToggle(e.target.checked);
              else updateItem(type, "enabled", e.target.checked);
            }}
          />
          <div className="track" />
          <div className="thumb" />
        </label>
        {testing && (
          <span
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              whiteSpace: "nowrap",
            }}
          >
            多模态测试中…
          </span>
        )}
      </>
    );
  };

  const renderGroundingCard = (meta: (typeof CARD_META)[number]) => {
    const { type, label, icon } = meta;
    const isExpanded = expanded.grounding;
    const verifier = groundingValidationModel(config);
    const searchModel = groundingSearchModel(config);
    const verifierReady =
      !!verifier.model_name && !!verifier.base_url && hasUsableApiKey(verifier);
    const nativeSearchReady =
      config.grounding.native_search_enabled &&
      !!searchModel.model_name &&
      !!searchModel.base_url &&
      hasUsableApiKey(searchModel) &&
      supportsQwenNativeSearch(searchModel);
    const searchReady = !!config.grounding.tavily_api_key || nativeSearchReady;
    const searchLabel = groundingSearchLabel(config);

    return (
      <div key={type} className="glass-card">
        <div
          onClick={() => toggleExpand("grounding")}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 18px",
            cursor: "pointer",
            userSelect: "none",
            borderBottom: isExpanded ? "1px solid var(--color-border)" : "none",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {icon}
            <span style={{ fontSize: 14, fontWeight: 600 }}>{label}</span>
            <span
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                background: "var(--color-bg-secondary)",
                padding: "1px 7px",
                borderRadius: 4,
              }}
            >
              搜索 / 验证解耦
            </span>
            {config.grounding.enabled &&
              (searchLabel || verifier.model_name) && (
                <span
                  className="text-ellipsis"
                  style={{
                    fontSize: 10,
                    color:
                      verifierReady && searchReady
                        ? "var(--color-success)"
                        : "var(--color-text-tertiary)",
                    background: "var(--color-success-soft)",
                    padding: "1px 7px",
                    borderRadius: 4,
                    maxWidth: 140,
                  }}
                >
                  {searchLabel || "未配置搜索"}
                  {verifier.model_name ? ` · ${verifier.model_name}` : ""}
                </span>
              )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: config.grounding.enabled
                  ? "var(--color-success)"
                  : "var(--color-border)",
              }}
            />
            <label
              className="desktop-toggle"
              onClick={(event) => event.stopPropagation()}
            >
              <input
                type="checkbox"
                aria-label="启用 Grounding"
                checked={config.grounding.enabled}
                onChange={(event) =>
                  updateGrounding("enabled", event.target.checked)
                }
              />
              <div className="track" />
              <div className="thumb" />
            </label>
            <DownOutlined
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                transition: "transform 0.2s",
                transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          </div>
        </div>
        {isExpanded && (
          <div
            style={{
              padding: "16px 18px 32px",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>1. 搜索</div>
            {/* 优先级链：Tavily 优先，Qwen 原生搜索回退 */}
            <div
              style={{
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "12px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: "var(--color-accent-soft)",
                    color: "var(--color-accent)",
                    flexShrink: 0,
                  }}
                >
                  优先
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--color-text-primary)",
                  }}
                >
                  Tavily 搜索
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: config.grounding.tavily_api_key
                      ? "var(--color-success)"
                      : "var(--color-text-tertiary)",
                  }}
                >
                  {config.grounding.tavily_api_key
                    ? "已配置"
                    : "未配置，将直接使用原生搜索"}
                </span>
              </div>
              <div>
                <label className="field-label">Tavily API Key（可选）</label>
                <Input.Password
                  placeholder="tvly-..."
                  value={config.grounding.tavily_api_key}
                  onChange={(event) =>
                    updateGrounding("tavily_api_key", event.target.value)
                  }
                />
              </div>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                margin: "-8px 0 -8px 16px",
                fontSize: 13,
                lineHeight: 1,
                color: "var(--color-text-tertiary)",
              }}
            >
              ↓
            </div>
            <div
              style={{
                border: "1px solid var(--color-border)",
                borderRadius: 8,
                padding: "12px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
                opacity: config.grounding.native_search_enabled ? 1 : 0.75,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: "var(--color-bg-secondary)",
                    color: "var(--color-text-secondary)",
                    flexShrink: 0,
                  }}
                >
                  回退
                </span>
                <Checkbox
                  checked={config.grounding.native_search_enabled}
                  onChange={(event) =>
                    updateGrounding(
                      "native_search_enabled",
                      event.target.checked,
                    )
                  }
                >
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "var(--color-text-primary)",
                    }}
                  >
                    Qwen/DashScope 原生搜索
                  </span>
                </Checkbox>
              </div>
              {config.grounding.native_search_enabled ? (
                <div
                  style={{
                    borderLeft: "2px solid var(--color-border)",
                    marginLeft: 5,
                    paddingLeft: 14,
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                    }}
                  >
                    <Checkbox
                      checked={config.grounding.search_reuse_llm}
                      onChange={(event) =>
                        updateGrounding(
                          "search_reuse_llm",
                          event.target.checked,
                        )
                      }
                    >
                      <span
                        style={{
                          fontSize: 12,
                          color: "var(--color-text-secondary)",
                        }}
                      >
                        复用 LLM 配置
                      </span>
                    </Checkbox>
                    <span
                      style={{
                        fontSize: 11,
                        color: nativeSearchReady
                          ? "var(--color-success)"
                          : "var(--color-text-tertiary)",
                      }}
                    >
                      {searchModel.model_name
                        ? `当前：${searchModel.model_name}${
                            nativeSearchReady ? "" : "（不支持原生搜索）"
                          }`
                        : "未配置"}
                    </span>
                  </div>
                  {!config.grounding.search_reuse_llm && (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "0 16px",
                      }}
                    >
                      <div>
                        <label className="field-label">Qwen 搜索模型</label>
                        <Input
                          placeholder="qwen3.7-plus"
                          value={config.grounding.search_model_name}
                          onChange={(event) =>
                            updateGrounding(
                              "search_model_name",
                              event.target.value,
                            )
                          }
                        />
                      </div>
                      <div>
                        <label className="field-label">Qwen 搜索 API Key</label>
                        <Input.Password
                          placeholder="sk-search-..."
                          value={config.grounding.search_api_key}
                          onChange={(event) =>
                            updateGrounding(
                              "search_api_key",
                              event.target.value,
                            )
                          }
                        />
                      </div>
                      <div>
                        <label className="field-label">
                          Qwen 搜索 Base URL
                        </label>
                        <Input
                          placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                          value={config.grounding.search_base_url}
                          onChange={(event) =>
                            updateGrounding(
                              "search_base_url",
                              event.target.value,
                            )
                          }
                        />
                      </div>
                      <div>
                        <label className="field-label">搜索 Adapter</label>
                        <Select
                          value={config.grounding.search_protocol}
                          onChange={(value) =>
                            updateGrounding("search_protocol", value)
                          }
                          options={[
                            {
                              value: "DashScope（百炼）",
                              label: "Qwen / DashScope（百炼）",
                            },
                          ]}
                        />
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>

            <div
              style={{
                borderTop: "1px solid var(--color-border)",
                paddingTop: 16,
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              2. 验证
            </div>
            <div>
              <label className="field-label">验证模型来源</label>
              <Select
                value={config.grounding.validation_source}
                onChange={(value) => {
                  updateGrounding("validation_source", value);
                  updateGrounding("reuse_llm", value === "llm");
                }}
                options={[
                  { value: "llm", label: "复用 LLM 配置" },
                  { value: "vlm", label: "复用 VLM 配置" },
                  { value: "custom", label: "自定义验证模型" },
                ]}
              />
              {config.grounding.validation_source !== "custom" && (
                <div
                  style={{
                    marginTop: 6,
                    fontSize: 11,
                    color: verifierReady
                      ? "var(--color-success)"
                      : "var(--color-text-tertiary)",
                  }}
                >
                  {verifier.model_name
                    ? `当前：${verifier.model_name}`
                    : "未配置"}
                </div>
              )}
            </div>

            {config.grounding.validation_source === "custom" && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "0 16px",
                }}
              >
                <div>
                  <label className="field-label">验证模型</label>
                  <Input
                    placeholder="model"
                    value={config.grounding.model_name}
                    onChange={(event) =>
                      updateGrounding("model_name", event.target.value)
                    }
                  />
                </div>
                <div>
                  <label className="field-label">验证模型 API Key</label>
                  <Input.Password
                    placeholder="sk-..."
                    value={config.grounding.api_key}
                    onChange={(event) =>
                      updateGrounding("api_key", event.target.value)
                    }
                  />
                </div>
                <div>
                  <label className="field-label">验证模型 Base URL</label>
                  <Input
                    placeholder="https://api.example.com"
                    value={config.grounding.base_url}
                    onChange={(event) =>
                      updateGrounding("base_url", event.target.value)
                    }
                  />
                </div>
                <div>
                  <label className="field-label">API 协议</label>
                  <Select
                    value={config.grounding.protocol}
                    onChange={(value) => updateGrounding("protocol", value)}
                    options={VLM_PROTOCOLS.map((protocol) => ({
                      value: protocol,
                      label: protocol,
                    }))}
                  />
                </div>
              </div>
            )}

            <div>
              <Button
                className="test-btn"
                icon={<LinkOutlined />}
                loading={testing.grounding}
                onClick={handleGroundingTest}
              >
                测试验证模型图片输入
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderCard = (meta: (typeof CARD_META)[number]) => {
    if (meta.type === "grounding") return renderGroundingCard(meta);
    const { type, label, icon, required } = meta;
    const isExpanded = expanded[type];
    const item = config[type] as ModelConfigItem;
    const usingLlm =
      type === "vlm" && config.vlm.use_llm && config.llm.model_name;
    const configured = !item.enabled
      ? false
      : usingLlm
      ? true
      : !!item.model_name;
    const isTested = tested[type] === true;

    const statusColor = !configured
      ? "var(--color-border)"
      : isTested
      ? "var(--color-success)"
      : "var(--color-danger)";
    const statusDot = (
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: statusColor,
          flexShrink: 0,
        }}
      />
    );

    return (
      <div key={type} className="glass-card">
        <div
          onClick={() => toggleExpand(type)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 18px",
            cursor: "pointer",
            userSelect: "none",
            borderBottom: isExpanded ? "1px solid var(--color-border)" : "none",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {icon}
            <span
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              {label}
            </span>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                fontSize: 10,
                fontWeight: 500,
                color: required
                  ? "var(--color-accent)"
                  : "var(--color-text-tertiary)",
                background: required
                  ? "var(--color-accent-soft)"
                  : "var(--color-bg-secondary)",
                padding: "1px 7px",
                borderRadius: 4,
              }}
            >
              {required ? "必选" : "可选"}
            </span>
            {configured && (
              <span
                className="text-ellipsis"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  fontSize: 10,
                  fontWeight: 500,
                  color: isTested
                    ? "var(--color-success)"
                    : "var(--color-danger)",
                  background: "var(--color-success-soft)",
                  padding: "1px 7px",
                  borderRadius: 4,
                  maxWidth: 100,
                }}
              >
                {!item.enabled
                  ? "（已关闭）"
                  : usingLlm
                  ? config.llm.model_name
                  : item.model_name}
                {!isTested && item.enabled && "（未测试）"}
              </span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {statusDot}
            {toggleControl(type)}
            <DownOutlined
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                transition: "transform 0.2s",
                transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          </div>
        </div>
        {isExpanded && (
          <div
            style={{
              padding: "16px 18px 32px",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            {type === "vlm" && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Checkbox
                  checked={config.vlm.use_llm}
                  disabled={testingLlmMultimodal}
                  onChange={(e) => handleVlmUseLlm(e.target.checked)}
                >
                  <span
                    style={{
                      fontSize: 12,
                      color: testingLlmMultimodal
                        ? "var(--color-text-tertiary)"
                        : "var(--color-text-secondary)",
                      cursor: "pointer",
                    }}
                  >
                    {testingLlmMultimodal ? "多模态测试中…" : "复用 LLM 配置"}
                  </span>
                </Checkbox>
                {testingLlmMultimodal && (
                  <span
                    style={{
                      fontSize: 11,
                      color: "var(--color-text-tertiary)",
                    }}
                  >
                    发送图片请求验证 LLM 多模态能力
                  </span>
                )}
              </div>
            )}
            {type !== "vlm" && renderFields(type)}
            {type === "vlm" && !config.vlm.use_llm && renderFields("vlm")}
          </div>
        )}
      </div>
    );
  };

  return (
    <Modal
      open={open}
      onCancel={handleCancel}
      footer={null}
      width={800}
      centered
      closable={false}
      styles={{ body: { padding: 0 } }}
      rootClassName="model-config-modal"
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "18px 22px 14px",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <SettingOutlined
            style={{ color: "var(--color-text-primary)", fontSize: 16 }}
          />
          <span
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            模型配置
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--color-text-tertiary)",
            padding: 4,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 4,
            transition: "all 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-text-primary)";
            (e.currentTarget as HTMLButtonElement).style.background =
              "var(--color-bg-secondary)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-text-tertiary)";
            (e.currentTarget as HTMLButtonElement).style.background = "none";
          }}
          aria-label="关闭"
        >
          <CloseOutlined style={{ fontSize: 14 }} />
        </button>
      </div>

      {/* Body */}
      <div
        style={{
          padding: "16px 22px 8px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          maxHeight: "calc(80vh - 120px)",
          overflowY: "auto",
        }}
      >
        <details className="glass-card" style={{ padding: "10px 18px" }}>
          <summary
            style={{
              cursor: "pointer",
              userSelect: "none",
              fontSize: 12,
              fontWeight: 600,
              color: "var(--color-accent)",
            }}
          >
            不知道该配什么？查看各场景的模型要求与支持的提供商
          </summary>
          <div style={{ marginTop: 10 }}>
            <ModelSetupGuide />
          </div>
        </details>
        <div
          className="glass-card"
          style={{
            padding: "14px 18px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 20,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              高花费模型执行授权
            </div>
            <div
              style={{
                marginTop: 4,
                fontSize: 12,
                lineHeight: 1.5,
                color: "var(--color-text-tertiary)",
              }}
            >
              开启后，高花费模型的执行需要确认。
            </div>
          </div>
          <label className="desktop-toggle" style={{ flexShrink: 0 }}>
            <input
              type="checkbox"
              aria-label="高花费模型执行授权"
              checked={config.executionAuthorization.mode === "required"}
              onChange={async (event) => {
                const mode = event.target.checked ? "required" : "allow_all";
                setConfig((previous) => ({
                  ...previous,
                  executionAuthorization: { mode },
                }));
                try {
                  await patchExecutionAuthorization(mode);
                } catch (err) {
                  message.error((err as Error).message || "授权设置保存失败");
                }
              }}
            />
            <div className="track" />
            <div className="thumb" />
          </label>
        </div>

        {/* Segmented tabs */}
        <div className="segmented-tabs">
          {CARD_META.map((meta) => {
            const item = config[meta.type] as ModelConfigItem;
            const hasModel = !!item.model_name;
            const active = activeTab === meta.type;
            let subText: string;
            let subColor: string;
            if (meta.type === "grounding") {
              const verifier = groundingValidationModel(config);
              const searchLabel = groundingSearchLabel(config);
              subText = !config.grounding.enabled
                ? "已关闭"
                : searchLabel && verifier.model_name
                ? `${searchLabel} · ${verifier.model_name}`
                : "未配置";
              subColor = !config.grounding.enabled
                ? "var(--color-text-tertiary)"
                : searchLabel && verifier.model_name
                ? "var(--color-success)"
                : "var(--color-text-tertiary)";
            } else if (
              meta.type === "vlm" &&
              config.vlm.use_llm &&
              config.llm.model_name
            ) {
              subText = tested.vlm
                ? config.llm.model_name
                : `${config.llm.model_name}（未测试）`;
              subColor = tested.vlm
                ? "var(--color-success)"
                : "var(--color-text-tertiary)";
            } else if (!item.enabled && hasModel) {
              subText = `${item.model_name}（已关闭）`;
              subColor = "var(--color-text-tertiary)";
            } else if (!hasModel) {
              subText = "未配置";
              subColor = "var(--color-text-tertiary)";
            } else if (tested[meta.type] !== true) {
              subText = `${item.model_name}（未测试）`;
              subColor = "var(--color-danger)";
            } else {
              subText = item.model_name;
              subColor = "var(--color-success)";
            }
            return (
              <button
                key={meta.type}
                className={`segmented-tab ${active ? "active" : ""}`}
                onClick={() => handleTabChange(meta.type)}
                style={{
                  flexDirection: "column",
                  padding: "5px 6px 4px",
                  gap: 2,
                }}
              >
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  {meta.icon} {meta.label.replace("模型", "")}
                  <span style={{ fontSize: 9, opacity: 0.5, fontWeight: 400 }}>
                    {meta.required ? "必选" : "可选"}
                  </span>
                </span>
                <span
                  className="text-ellipsis"
                  style={{
                    fontSize: 10,
                    lineHeight: "14px",
                    color: subColor,
                    fontWeight: active ? 600 : 400,
                    maxWidth: 100,
                  }}
                >
                  {subText}
                </span>
              </button>
            );
          })}
        </div>

        {/* Active tab card */}
        {CARD_META.filter((meta) => meta.type === activeTab).map((meta) =>
          renderCard(meta),
        )}
      </div>

      {/* Footer */}
      <div className="action-bar">
        <div />
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Button onClick={handleCancel}>取消</Button>
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            loading={reloading}
            onClick={handleReload}
          >
            重新加载配置
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSave}
          >
            保存配置
          </Button>
        </div>
      </div>
    </Modal>
  );
}
