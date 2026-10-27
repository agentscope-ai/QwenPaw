import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import type { ModelConfigItem } from "@/contracts/creator";
import { useModelConfigStore } from "@/store/modelConfigStore";
import ModelConfigModal, { supportsQwenNativeSearch } from "./ModelConfigModal";

type ModelType =
  | "llm"
  | "vlm"
  | "grounding"
  | "asr"
  | "tts"
  | "s2v"
  | "image"
  | "video";
type ModelStatus = "on" | "off" | "none" | "incomplete";

const READY_COLOR = "#14B8A6";
const IDLE_COLOR = "var(--color-text-tertiary)";

const BADGE_META: { type: ModelType; labelKey: string }[] = [
  { type: "llm", labelKey: "modelBadges.textModel" },
  { type: "vlm", labelKey: "modelBadges.visionModel" },
  { type: "grounding", labelKey: "Grounding" },
  { type: "asr", labelKey: "modelBadges.asrModel" },
  { type: "tts", labelKey: "modelBadges.ttsModel" },
  { type: "s2v", labelKey: "modelBadges.s2vModel" },
  { type: "image", labelKey: "modelBadges.imageModel" },
  { type: "video", labelKey: "modelBadges.videoModel" },
];

const STATUS_TEXT_KEYS: Record<ModelStatus, string> = {
  on: "modelBadges.configured",
  off: "modelBadges.configuredNotEnabled",
  none: "modelBadges.notConfigured",
  incomplete: "modelBadges.configurationIncomplete",
};

export default function ModelBadges() {
  const { t } = useTranslation();
  const config = useModelConfigStore((state) => state.config);
  const refresh = useModelConfigStore((state) => state.refresh);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const modalClose = useCallback(() => {
    setModalOpen(false);
    void refresh();
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
        !!config.grounding.tavily_api_key ||
        !!config.grounding.serper_api_key ||
        nativeSearchReady;
      const verifierReady =
        !!verifier.model_name && !!verifier.api_key && !!verifier.base_url;
      if (!searchReady && !verifierReady) return "none";
      if (!searchReady || !verifierReady) return "incomplete";
      return config.grounding.enabled ? "on" : "off";
    }
    const item = config[type] as ModelConfigItem | undefined;
    if (!item) return "none";
    if (type === "vlm" && config.vlm.use_llm && config.llm.model_name)
      return item.enabled ? "on" : "none";
    if (!item.model_name) return "none";
    return item.enabled ? "on" : "off";
  };

  const badges = BADGE_META.map((meta) => ({
    ...meta,
    state: status(meta.type),
  }));
  const readyCount = badges.filter((badge) => badge.state === "on").length;
  const summary = t("modelBadges.compactSummary", {
    ready: readyCount,
    total: badges.length,
  });

  return (
    <>
      <Tooltip
        trigger={["hover", "focus"]}
        title={
          <div className="flex flex-col gap-1 py-1">
            <span className="mb-1 font-semibold">{summary}</span>
            {badges.map((badge) => {
              const label = t("modelBadges.badgeTitle", {
                name: t(badge.labelKey),
                status: t(STATUS_TEXT_KEYS[badge.state]),
              });
              return (
                <span
                  key={badge.type}
                  data-model-badge={badge.type}
                  data-status={badge.state}
                  aria-label={label}
                  className="flex items-center gap-2"
                >
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{
                      background:
                        badge.state === "on" ? READY_COLOR : IDLE_COLOR,
                    }}
                  />
                  {label}
                </span>
              );
            })}
          </div>
        }
      >
        <button
          type="button"
          data-onboarding-id="model-badges"
          onClick={() => setModalOpen(true)}
          aria-label={t("modelBadges.modelConfig")}
          className="relative mr-[92px] flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
        >
          <svg
            data-model-badges-ring
            viewBox="0 0 36 36"
            className="absolute inset-0 h-full w-full -rotate-90"
            aria-hidden="true"
          >
            <circle
              cx="18"
              cy="18"
              r="15"
              fill="none"
              stroke="var(--color-border)"
              strokeWidth="3"
            />
            {readyCount > 0 && (
              <circle
                cx="18"
                cy="18"
                r="15"
                fill="none"
                stroke={READY_COLOR}
                strokeWidth="3"
                strokeLinecap="round"
                pathLength="100"
                strokeDasharray={`${(readyCount / badges.length) * 100} 100`}
              />
            )}
          </svg>
          <span
            data-model-badges-compact
            className="text-[10px] font-semibold tabular-nums"
            aria-label={summary}
          >
            {readyCount}/{badges.length}
          </span>
        </button>
      </Tooltip>
      <ModelConfigModal open={modalOpen} onClose={modalClose} />
    </>
  );
}
