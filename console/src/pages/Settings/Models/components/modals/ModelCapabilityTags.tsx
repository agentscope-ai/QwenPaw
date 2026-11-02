import { Tooltip } from "antd";
import { Tag } from "@agentscope-ai/design";
import {
  AudioLines,
  Wrench,
  Gift,
  CreditCard,
  type LucideIcon,
  Boxes,
  CircleHelp,
  Eye,
  FileText,
  Video,
} from "lucide-react";
import type { ModelInfo } from "../../../../../api/types";
import { useTranslation } from "react-i18next";

const tagColors = () => ({
  multimodal: {
    backgroundColor: "var(--app-info-bg)",
    color: "var(--app-info-text)",
    borderColor: "var(--app-info-border)",
  },
  vision: {
    backgroundColor: "var(--app-info-bg)",
    color: "var(--app-info-text)",
    borderColor: "var(--app-info-border)",
  },
  video: {
    backgroundColor: "var(--app-accent-soft)",
    color: "var(--app-accent-text)",
    borderColor: "var(--app-accent-border)",
  },
  text: {
    backgroundColor: "var(--app-fill-subtle)",
    color: "var(--app-text-secondary)",
    borderColor: "var(--app-border-strong)",
  },
  notProbed: {
    backgroundColor: "var(--app-fill-subtle)",
    color: "var(--app-text-tertiary)",
    borderColor: "var(--app-border-strong)",
  },
  builtin: {
    backgroundColor: "var(--app-success-bg)",
    color: "var(--app-success-text)",
    borderColor: "var(--app-success-border)",
  },
  free: {
    backgroundColor: "var(--app-success-bg)",
    color: "var(--app-success-text)",
    borderColor: "var(--app-success-border)",
  },
  userAdded: {
    backgroundColor: "var(--app-info-bg)",
    color: "var(--app-info-text)",
    borderColor: "var(--app-info-border)",
  },
});

function CapabilityTag({
  icon: Icon,
  children,
  tone = "info",
  iconOnly = false,
}: {
  icon: LucideIcon;
  iconOnly?: boolean;
  children: React.ReactNode;
  tone?: "info" | "neutral" | "free";
}) {
  const colors = tagColors();
  const tag = (
    <Tag
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        minHeight: 24,
        padding: iconOnly ? "1px 4px" : "1px 6px",
        borderRadius: 4,
        fontSize: "var(--app-font-caption)",
        fontWeight: 500,
        lineHeight: "20px",
        borderWidth: 1,
        borderStyle: "solid",
        margin: 0,
        ...(tone === "free"
          ? colors.free
          : tone === "neutral"
          ? colors.text
          : colors.multimodal),
      }}
    >
      <Icon size={14} strokeWidth={1.8} aria-hidden />
      {!iconOnly && children}
    </Tag>
  );
  return iconOnly ? (
    <Tooltip title={children}>
      <span
        tabIndex={0}
        role="img"
        aria-label={typeof children === "string" ? children : undefined}
        style={{ display: "inline-flex" }}
      >
        {tag}
      </span>
    </Tooltip>
  ) : (
    tag
  );
}

export function CapabilityTags({
  model,
  iconOnly = false,
}: {
  model: ModelInfo;
  iconOnly?: boolean;
}) {
  const { t } = useTranslation();
  const isDecision = model.model_type === "decision";
  const modalities = [
    model.supports_image,
    model.supports_audio,
    model.supports_video,
  ];
  const multiple = modalities.filter(Boolean).length > 1;
  const icon = multiple
    ? Boxes
    : model.supports_image
    ? Eye
    : model.supports_video
    ? Video
    : model.supports_audio
    ? AudioLines
    : model.supports_multimodal === false
    ? FileText
    : CircleHelp;
  const label = multiple
    ? "models.tagMultimodal"
    : model.supports_image
    ? "models.tagVision"
    : model.supports_video
    ? "models.tagVideo"
    : model.supports_audio
    ? "models.pool.capabilityOptions.audio"
    : model.supports_multimodal === false
    ? "models.tagText"
    : "models.tagNotProbed";
  return (
    <>
      {isDecision && (
        <CapabilityTag icon={Boxes} iconOnly={iconOnly}>
          {t("models.modelTypeDecision")}
        </CapabilityTag>
      )}
      {((!iconOnly && !isDecision) || modalities.some(Boolean)) && (
        <CapabilityTag
          icon={icon}
          iconOnly={iconOnly}
          tone={modalities.some(Boolean) ? "info" : "neutral"}
        >
          {t(label)}
        </CapabilityTag>
      )}
      {model.supports_tool_calling === true && (
        <CapabilityTag icon={Wrench} iconOnly={iconOnly}>
          {t("models.pool.capabilityOptions.tool_calling")}
        </CapabilityTag>
      )}
    </>
  );
}

export function BillingTag({
  model,
  iconOnly = false,
  priceDetails = false,
}: {
  model: ModelInfo;
  iconOnly?: boolean;
  priceDetails?: boolean;
}) {
  const { t } = useTranslation();
  const billing = model.billing ?? (model.is_free ? "free" : "unknown");
  const tag = (
    <CapabilityTag
      iconOnly={iconOnly}
      icon={
        billing === "free" ? Gift : billing === "paid" ? CreditCard : CircleHelp
      }
      tone={billing === "free" ? "free" : "neutral"}
    >
      {t(`models.billing.${billing}`)}
    </CapabilityTag>
  );
  if (!priceDetails || !model.pricing?.prompt) return tag;
  const pricing = model.pricing;
  const source = model.capability_provenance?.billing;
  const price = (value: string) => {
    const amount = Number(value) * 1_000_000;
    return Number.isFinite(amount)
      ? amount.toLocaleString(undefined, { maximumFractionDigits: 6 })
      : "—";
  };
  return (
    <Tooltip
      trigger={["hover", "focus", "click"]}
      title={
        <div>
          <div>{t("models.apiPricing.standard")}</div>
          {(["prompt", "completion", "input_cache_read"] as const).map(
            (key) =>
              pricing[key] != null && (
                <div key={key}>
                  {t(`models.apiPricing.${key}`)}: ${price(pricing[key])}
                </div>
              ),
          )}
          {typeof source?.context_threshold === "number" &&
            typeof source.long_context_input_multiplier === "number" &&
            typeof source.long_context_output_multiplier === "number" && (
              <p>
                {t("models.apiPricing.longContext", {
                  threshold: source.context_threshold.toLocaleString(),
                  inputMultiplier: source.long_context_input_multiplier,
                  outputMultiplier: source.long_context_output_multiplier,
                })}
              </p>
            )}
          {typeof source?.cache_write_30m_multiplier === "number" &&
            typeof source.cache_write_12h_multiplier === "number" && (
              <p>
                {t("models.apiPricing.cacheWrite", {
                  shortMultiplier: source.cache_write_30m_multiplier,
                  longMultiplier: source.cache_write_12h_multiplier,
                })}
              </p>
            )}
          <div>{t("models.apiPricing.exclusions")}</div>
          {typeof source?.updated_at === "string" && (
            <div>
              {t("models.apiPricing.checked", { date: source.updated_at })}
            </div>
          )}
        </div>
      }
    >
      <span tabIndex={0} style={{ display: "inline-flex" }}>
        {tag}
      </span>
    </Tooltip>
  );
}
