import { Popover, Segmented } from "antd";
import {
  Image,
  AudioLines,
  Video,
  Wrench,
  Check,
  Minus,
  CircleHelp,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelInfo } from "../../../../../api/types";
import styles from "./ModelCapabilitiesFields.module.less";

const fields = [
  "supports_image",
  "supports_audio",
  "supports_video",
  "supports_tool_calling",
] as const;
const icons = [Image, AudioLines, Video, Wrench];
export type CapabilityOverrides = Partial<
  Record<(typeof fields)[number], boolean | null>
>;

export function ModelCapabilitiesFields({
  model,
  changes,
  onChange,
}: {
  model: ModelInfo;
  changes: CapabilityOverrides;
  onChange: (changes: CapabilityOverrides) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.capabilities}>
      {fields.map((field, index) => {
        const override =
          field in changes
            ? changes[field]
            : model.config_overrides?.includes(field)
            ? model[field]
            : null;
        const effective = override ?? model[field];
        const Icon = icons[index];
        const Status =
          effective == null ? CircleHelp : effective ? Check : Minus;
        const status = t(
          effective == null
            ? "models.capabilities.unknown"
            : effective
            ? "models.capabilities.supported"
            : "models.capabilities.unsupported",
        );
        const automatic = override == null;
        const label = t(`models.capabilities.${field}`);
        return (
          <Popover
            key={field}
            trigger="click"
            placement="top"
            content={
              <div className={styles.editor}>
                <div className={styles.heading}>
                  <Icon size={16} />
                  <span>{label}</span>
                </div>
                <Segmented
                  block
                  aria-label={label}
                  value={automatic ? "auto" : String(override)}
                  options={[
                    { value: "auto", label: t("models.capabilities.auto") },
                    {
                      value: "true",
                      label: t("models.capabilities.supported"),
                    },
                    {
                      value: "false",
                      label: t("models.capabilities.unsupported"),
                    },
                  ]}
                  onChange={(value) =>
                    onChange({
                      ...changes,
                      [field]: value === "auto" ? null : value === "true",
                    })
                  }
                />
              </div>
            }
          >
            <button
              type="button"
              className={styles.chip}
              data-supported={effective === true}
              aria-label={`${label}: ${
                automatic ? t("models.capabilities.auto") + " · " : ""
              }${status}`}
            >
              <Icon size={16} strokeWidth={1.7} />
              <span>{label}</span>
              {automatic && (
                <span className={styles.auto}>
                  {t("models.capabilities.auto")}
                </span>
              )}
              <Status size={14} strokeWidth={1.7} />
            </button>
          </Popover>
        );
      })}
    </div>
  );
}
