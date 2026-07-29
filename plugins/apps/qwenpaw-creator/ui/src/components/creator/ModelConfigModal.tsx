import { useState, useEffect, useCallback, useRef } from "react";
import { Modal, Input, Select, Checkbox, Button, message } from "antd";
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
  ReloadOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import {
  getModelConfig,
  saveModelConfig,
  patchModelConfigSection,
  patchExecutionAuthorization,
  testModelConnection,
} from "@/api/creator";
import type { ModelConfigData, ModelConfigItem } from "@/contracts/creator";
import ModelSetupGuide from "@/components/onboarding/ModelSetupGuide";

const LLM_PROTOCOLS = [
  "Anthropic Claude",
  "DashScope（百炼）",
  "DeepSeek",
  "Google Gemini",
  "OpenAI 协议",
  "百度千帆",
  "Volcano Engine（火山引擎）",
  "自定义",
];
const VLM_PROTOCOLS = [
  "Anthropic Claude",
  "DashScope（百炼）",
  "DeepSeek",
  "Google Gemini",
  "OpenAI 协议",
  "百度千帆",
  "Volcano Engine（火山引擎）",
  "自定义",
];
const ASR_PROTOCOLS = ["DashScope Fun-ASR", "OpenAI Whisper"];
const IMAGE_PROTOCOLS = ["OpenAI 协议", "DashScope（百炼）"];
const VIDEO_PROTOCOLS = ["DashScope（百炼）", "Volcano Engine（火山引擎）"];
type ModelType = "llm" | "vlm" | "asr" | "image" | "video";
type TabType = ModelType;
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

interface Props {
  open: boolean;
  onClose: () => void;
}

const CARD_META: {
  type: ModelType;
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

  const loadConfig = useCallback(async () => {
    try {
      const data = await getModelConfig();
      const merged: ModelConfigData = {
        ...DEFAULT_CONFIG,
        ...data,
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
        const data = await testModelConnection({
          type: "vlm",
          base_url: llmItem.base_url,
          api_key: llmItem.api_key,
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
        const data = await testModelConnection({
          type,
          base_url: item.base_url,
          api_key:
            type === "asr" && config.asr.reuse_llm_key
              ? config.llm.api_key
              : item.api_key,
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

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const prev = snapshotRef.current;
      if (!prev) throw new Error("快照丢失，请重新打开配置");

      const dirtySections: TabType[] = [];
      for (const section of [
        "llm",
        "vlm",
        "asr",
        "image",
        "video",
      ] as TabType[]) {
        if (JSON.stringify(config[section]) !== JSON.stringify(prev[section])) {
          dirtySections.push(section);
        }
      }

      for (const section of dirtySections) {
        if (!tested[section]) {
          const ok = await handleTest(section);
          if (!ok) return;
        }
        const res = await patchModelConfigSection(
          section,
          config[section] as unknown as Record<string, unknown>,
        );
        if (!res.ok) throw new Error(`保存 ${section} 失败：服务端未确认写入`);
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

  const renderFields = (type: ModelType) => {
    const item = config[type] as ModelConfigItem;
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
            <Input
              placeholder="model"
              value={item.model_name}
              onChange={(e) => updateItem(type, "model_name", e.target.value)}
            />
          </div>
          <div>
            <label className="field-label">API Key</label>
            <Input.Password
              placeholder="sk-..."
              value={item.api_key}
              onChange={(e) => updateItem(type, "api_key", e.target.value)}
            />
          </div>
          <div>
            <label className="field-label">Base URL</label>
            <Input
              placeholder="https://api.example.com"
              value={item.base_url}
              onChange={(e) => updateItem(type, "base_url", e.target.value)}
            />
          </div>
          <div>
            <label className="field-label">API 协议</label>
            <Select
              value={item.protocol}
              onChange={(v) => {
                updateItem(type, "protocol", v);
                if (type === "asr") {
                  const provider =
                    v === "OpenAI Whisper" ? "whisper" : "fun-asr";
                  updateItem("asr", "provider", provider);
                  updateItem(
                    "asr",
                    "model_name",
                    provider === "whisper" ? "whisper-1" : "fun-asr",
                  );
                  updateItem(
                    "asr",
                    "base_url",
                    provider === "whisper"
                      ? "https://api.openai.com/v1"
                      : "https://dashscope.aliyuncs.com/api/v1",
                  );
                }
              }}
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

  const renderCard = (meta: (typeof CARD_META)[number]) => {
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
            if (
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
