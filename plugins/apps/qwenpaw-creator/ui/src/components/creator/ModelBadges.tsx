import { useState, useEffect, useCallback } from "react";
import { Brain } from "lucide-react";
import {
  SettingOutlined,
  EyeOutlined,
  PictureOutlined,
  VideoCameraOutlined,
  AudioOutlined,
} from "@ant-design/icons";
import { getModelConfig } from "@/api/creator";
import type { ModelConfigData, ModelConfigItem } from "@/contracts/creator";
import ModelConfigModal from "./ModelConfigModal";

type ModelType = "llm" | "vlm" | "asr" | "image" | "video";

const BADGE_META: { type: ModelType; icon: React.ReactNode }[] = [
  { type: "llm", icon: <Brain size={12} /> },
  { type: "vlm", icon: <EyeOutlined style={{ fontSize: 12 }} /> },
  { type: "asr", icon: <AudioOutlined style={{ fontSize: 12 }} /> },
  { type: "image", icon: <PictureOutlined style={{ fontSize: 12 }} /> },
  { type: "video", icon: <VideoCameraOutlined style={{ fontSize: 12 }} /> },
];

export default function ModelBadges() {
  const [config, setConfig] = useState<ModelConfigData | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    getModelConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  const handleSaved = useCallback(() => {
    getModelConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  const modalClose = useCallback(() => {
    setModalOpen(false);
    handleSaved();
  }, [handleSaved]);

  const status = (type: ModelType): "on" | "off" | "none" => {
    if (!config) return "none";
    const item = config[type] as ModelConfigItem | undefined;
    if (!item) return "none";
    if (type === "vlm" && config.vlm.use_llm && config.llm.model_name)
      return item.enabled ? "on" : "none";
    if (!item.model_name) return "none";
    return item.enabled ? "on" : "off";
  };

  return (
    <>
      <div
        data-onboarding-id="model-badges"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          background: "var(--color-bg-primary)",
          borderRadius: 10,
          border: "1px solid var(--color-border)",
          padding: "3px 4px 3px 6px",
          marginRight: 80,
        }}
      >
        {BADGE_META.map((meta) => {
          const st = status(meta.type);
          return (
            <div
              key={meta.type}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
                padding: "3px 4px",
                borderRadius: 7,
                fontSize: 11,
                fontWeight: 500,
                color:
                  st === "on"
                    ? "var(--color-text-primary)"
                    : "var(--color-text-tertiary)",
                background:
                  st === "on" ? "var(--color-success-soft)" : "transparent",
                transition: "background 0.15s",
              }}
            >
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background:
                    st === "on"
                      ? "var(--color-success)"
                      : st === "off"
                      ? "var(--color-danger)"
                      : "var(--color-border)",
                  flexShrink: 0,
                }}
              />
              {meta.icon}
            </div>
          );
        })}
        <button
          onClick={() => setModalOpen(true)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 26,
            height: 26,
            borderRadius: 6,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            color: "var(--color-text-tertiary)",
            transition: "all 0.15s",
            marginLeft: 2,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background =
              "var(--color-accent-soft)";
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-accent)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background =
              "transparent";
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-text-tertiary)";
          }}
        >
          <SettingOutlined style={{ fontSize: 13 }} />
        </button>
      </div>
      <ModelConfigModal open={modalOpen} onClose={modalClose} />
    </>
  );
}
