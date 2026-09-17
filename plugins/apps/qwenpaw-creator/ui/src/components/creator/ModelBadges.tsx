import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { GlobalOutlined, SoundOutlined, UserOutlined } from "@ant-design/icons";
import type { ModelConfigItem } from "@/contracts/creator";
import { useModelConfigStore } from "@/store/modelConfigStore";
import modelLlmIcon from "@/assets/design/model-llm.svg";
import modelVlmIcon from "@/assets/design/model-vlm.svg";
import modelAsrIcon from "@/assets/design/model-asr.svg";
import modelImageIcon from "@/assets/design/model-image.svg";
import modelVideoIcon from "@/assets/design/model-video.svg";
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
type ModelStatus = "on" | "off" | "none";

const READY_COLOR = "#14B8A6";
const READY_HALO = "#C8F4E9";
const IDLE_COLOR = "#8E8C99";
const IDLE_HALO = "#EFF0F3";

const BADGE_META: {
  type: ModelType;
  icon: string | null;
  labelKey: string;
  // Rendered when no masked SVG glyph exists for the type.
  fallbackIcon?: React.ComponentType<{ style?: React.CSSProperties }>;
}[] = [
  { type: "llm", icon: modelLlmIcon, labelKey: "modelBadges.textModel" },
  { type: "vlm", icon: modelVlmIcon, labelKey: "modelBadges.visionModel" },
  {
    type: "grounding",
    icon: null,
    labelKey: "Grounding",
    fallbackIcon: GlobalOutlined,
  },
  { type: "asr", icon: modelAsrIcon, labelKey: "modelBadges.asrModel" },
  {
    type: "tts",
    icon: null,
    labelKey: "modelBadges.ttsModel",
    fallbackIcon: SoundOutlined,
  },
  {
    type: "s2v",
    icon: null,
    labelKey: "modelBadges.s2vModel",
    fallbackIcon: UserOutlined,
  },
  { type: "image", icon: modelImageIcon, labelKey: "modelBadges.imageModel" },
  { type: "video", icon: modelVideoIcon, labelKey: "modelBadges.videoModel" },
];

const STATUS_TEXT_KEYS: Record<ModelStatus, string> = {
  on: "modelBadges.configured",
  off: "modelBadges.configuredNotEnabled",
  none: "modelBadges.notConfigured",
};

/**
 * Model readiness indicator from the draft header: a fill-tertiary pill with
 * one 8px status dot plus one 20px glyph per model type, tinted by state via
 * a CSS mask. Clicking the pill opens the model configuration.
 */
export default function ModelBadges() {
  const { t } = useTranslation();
  // Shared snapshot: badges follow config saves made from any home-page
  // modal, not just the one opened from here.
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

  const readyCount = BADGE_META.filter(
    (meta) => status(meta.type) === "on",
  ).length;
  const compactTitle = BADGE_META.map((meta) =>
    t("modelBadges.badgeTitle", {
      name: t(meta.labelKey),
      status: t(STATUS_TEXT_KEYS[status(meta.type)]),
    }),
  ).join("\n");

  return (
    <>
      <button
        type="button"
        data-onboarding-id="model-badges"
        onClick={() => setModalOpen(true)}
        title={t("modelBadges.modelConfig")}
        aria-label={t("modelBadges.modelConfig")}
        className="mr-[92px] flex cursor-pointer items-center rounded-full bg-[rgba(43,27,0,0.04)] px-3 py-1 transition-colors hover:bg-[rgba(43,27,0,0.07)]"
      >
        <span className="hidden items-center gap-3 xl:flex">
          {BADGE_META.map((meta) => {
            const state = status(meta.type);
            const ready = state === "on";
            const tint = ready ? READY_COLOR : IDLE_COLOR;
            return (
              <span
                key={meta.type}
                className="flex h-5 items-center gap-2"
                title={t("modelBadges.badgeTitle", {
                  name: t(meta.labelKey),
                  status: t(STATUS_TEXT_KEYS[state]),
                })}
                aria-label={t("modelBadges.badgeTitle", {
                  name: t(meta.labelKey),
                  status: t(STATUS_TEXT_KEYS[state]),
                })}
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
                ) : meta.fallbackIcon ? (
                  <meta.fallbackIcon style={{ fontSize: 18, color: tint }} />
                ) : null}
              </span>
            );
          })}
        </span>
        {/* Narrow viewports collapse the eight glyphs into one readiness
            summary pill; the per-model statuses stay reachable via title. */}
        <span
          data-model-badges-compact
          className="flex h-5 items-center gap-2 whitespace-nowrap text-xs font-semibold text-[var(--color-text-secondary)] xl:hidden"
          title={compactTitle}
        >
          <span
            className="flex h-2 w-2 shrink-0 items-center justify-center rounded-full"
            style={{
              background:
                readyCount === BADGE_META.length ? READY_HALO : IDLE_HALO,
            }}
          >
            <span
              className="h-1 w-1 rounded-full"
              style={{
                background:
                  readyCount === BADGE_META.length ? READY_COLOR : IDLE_COLOR,
              }}
            />
          </span>
          {t("modelBadges.compactSummary", {
            ready: readyCount,
            total: BADGE_META.length,
          })}
        </span>
      </button>
      <ModelConfigModal open={modalOpen} onClose={modalClose} />
    </>
  );
}
