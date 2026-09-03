import { Tag } from "@agentscope-ai/design";
import { Boxes, CircleHelp, Eye, FileText, Video } from "lucide-react";
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

export function CapabilityTags({ model }: { model: ModelInfo }) {
  const { t } = useTranslation();
  const c = tagColors();
  if (model.supports_image && model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.multimodal }}>
        <Boxes size={14} style={{ marginRight: 4, verticalAlign: "-3px" }} />
        {t("models.tagMultimodal", "多模态")}
      </Tag>
    );
  }
  if (model.supports_image) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.vision }}>
        <Eye size={14} style={{ marginRight: 4, verticalAlign: "-3px" }} />
        {t("models.tagVision", "视觉")}
      </Tag>
    );
  }
  if (model.supports_video) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.video }}>
        <Video size={14} style={{ marginRight: 4, verticalAlign: "-3px" }} />
        {t("models.tagVideo", "视频")}
      </Tag>
    );
  }
  if (model.supports_multimodal === false) {
    return (
      <Tag style={{ fontSize: 11, marginRight: 4, ...c.text }}>
        <FileText size={14} style={{ marginRight: 4, verticalAlign: "-3px" }} />
        {t("models.tagText", "文本")}
      </Tag>
    );
  }
  return (
    <Tag style={{ fontSize: 11, marginRight: 4, ...c.notProbed }}>
      <CircleHelp size={14} style={{ marginRight: 4, verticalAlign: "-3px" }} />
      {t("models.tagNotProbed", "未检测")}
    </Tag>
  );
}
