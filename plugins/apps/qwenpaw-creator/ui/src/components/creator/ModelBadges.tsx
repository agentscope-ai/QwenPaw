import { useState, useEffect, useCallback } from "react";
import { GlobalOutlined } from "@ant-design/icons";
import { getModelConfig } from "@/api/creator";
import type { ModelConfigData, ModelConfigItem } from "@/contracts/creator";
import modelLlmIcon from "@/assets/design/model-llm.svg";
import modelVlmIcon from "@/assets/design/model-vlm.svg";
import modelAsrIcon from "@/assets/design/model-asr.svg";
import modelImageIcon from "@/assets/design/model-image.svg";
import modelVideoIcon from "@/assets/design/model-video.svg";
import ModelConfigModal, { supportsQwenNativeSearch } from "./ModelConfigModal";

type ModelType = "llm" | "vlm" | "grounding" | "asr" | "image" | "video";
type ModelStatus = "on" | "off" | "none";

const READY_COLOR = "#14B8A6";
const READY_HALO = "#C8F4E9";
const IDLE_COLOR = "#8E8C99";
const IDLE_HALO = "#EFF0F3";

const BADGE_META: {
  type: ModelType;
  icon: string | null;
  label: string;
}[] = [
  { type: "llm", icon: modelLlmIcon, label: "文本模型" },
  { type: "vlm", icon: modelVlmIcon, label: "视觉理解模型" },
  { type: "grounding", icon: null, label: "Grounding" },
  { type: "asr", icon: modelAsrIcon, label: "语音识别模型" },
  { type: "image", icon: modelImageIcon, label: "图像模型" },
  { type: "video", icon: modelVideoIcon, label: "视频模型" },
];

const STATUS_TEXT: Record<ModelStatus, string> = {
  on: "已配置",
  off: "已配置但未启用",
  none: "未配置",
};

/**
 * Model readiness indicator from the draft header: a fill-tertiary pill with
 * one 8px status dot plus one 20px glyph per model type, tinted by state via
 * a CSS mask. Clicking the pill opens the model configuration.
 */
export default function ModelBadges() {
  const [config, setConfig] = useState<ModelConfigData | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(() => {
    getModelConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const modalClose = useCallback(() => {
    setModalOpen(false);
    refresh();
  }, [refresh]);

  const status = (type: ModelType): ModelStatus => {
    if (!config) return "none";
    if (type === "grounding") {
      if (!config.grounding) return "none";
      const verifier =
        config.grounding.validation_source === "llm"
          ? config.llm
          : config.grounding.validation_source === "vlm"
          ? config.vlm.use_llm
            ? config.llm
            : config.vlm
          : config.grounding;
      const searchModel = config.grounding.search_reuse_llm
        ? config.llm
        : {
            ...config.grounding,
            model_name: config.grounding.search_model_name,
            api_key: config.grounding.search_api_key,
            base_url: config.grounding.search_base_url,
            protocol: config.grounding.search_protocol,
          };
      const nativeSearchReady =
        config.grounding.native_search_enabled &&
        !!searchModel.model_name &&
        !!searchModel.api_key &&
        !!searchModel.base_url &&
        supportsQwenNativeSearch(searchModel);
      const searchReady =
        !!config.grounding.tavily_api_key || nativeSearchReady;
      const verifierReady =
        !!verifier.model_name && !!verifier.api_key && !!verifier.base_url;
      if (!searchReady && !verifierReady) return "none";
      return config.grounding.enabled && searchReady && verifierReady
        ? "on"
        : "off";
    }
    const item = config[type] as ModelConfigItem | undefined;
    if (!item) return "none";
    if (type === "vlm" && config.vlm.use_llm && config.llm.model_name)
      return item.enabled ? "on" : "none";
    if (!item.model_name) return "none";
    return item.enabled ? "on" : "off";
  };

  return (
    <>
      <button
        type="button"
        data-onboarding-id="model-badges"
        onClick={() => setModalOpen(true)}
        title="模型配置"
        aria-label="模型配置"
        className="mr-[92px] flex cursor-pointer items-center gap-3 rounded-full bg-[rgba(43,27,0,0.04)] px-3 py-1 transition-colors hover:bg-[rgba(43,27,0,0.07)]"
      >
        {BADGE_META.map((meta) => {
          const state = status(meta.type);
          const ready = state === "on";
          const tint = ready ? READY_COLOR : IDLE_COLOR;
          return (
            <span
              key={meta.type}
              className="flex h-5 items-center gap-2"
              title={`${meta.label}：${STATUS_TEXT[state]}`}
              aria-label={`${meta.label}：${STATUS_TEXT[state]}`}
              data-model-badge={meta.type}
              data-status={state}
            >
              <span
                className="flex h-2 w-2 shrink-0 items-center justify-center rounded-full"
                style={{ background: ready ? READY_HALO : IDLE_HALO }}
              >
                <span
                  className="h-1 w-1 rounded-full"
                  style={{ background: tint }}
                />
              </span>
              {meta.icon ? (
                <span
                  className="h-5 w-5 shrink-0"
                  style={{
                    backgroundColor: tint,
                    // Quoted so inlined `data:` glyphs keep working: an
                    // unquoted url() would break on their `#` fill colours.
                    maskImage: `url("${meta.icon}")`,
                    WebkitMaskImage: `url("${meta.icon}")`,
                    maskSize: "100% 100%",
                    WebkitMaskSize: "100% 100%",
                    maskRepeat: "no-repeat",
                    WebkitMaskRepeat: "no-repeat",
                  }}
                />
              ) : (
                <GlobalOutlined style={{ fontSize: 18, color: tint }} />
              )}
            </span>
          );
        })}
      </button>
      <ModelConfigModal open={modalOpen} onClose={modalClose} />
    </>
  );
}
