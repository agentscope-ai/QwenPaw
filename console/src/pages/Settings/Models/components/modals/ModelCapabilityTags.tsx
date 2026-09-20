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

export const tagColors = () => ({
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
        fontSize: 12,
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
      <CapabilityTag
        icon={icon}
        iconOnly={iconOnly}
        tone={modalities.some(Boolean) ? "info" : "neutral"}
      >
        {t(label)}
      </CapabilityTag>
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
}: {
  model: ModelInfo;
  iconOnly?: boolean;
}) {
  const { t } = useTranslation();
  const billing = model.billing ?? (model.is_free ? "free" : "unknown");
  return (
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
}
