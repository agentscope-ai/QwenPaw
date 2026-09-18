import { Select } from "antd";
import { useTranslation } from "react-i18next";
import type { ModelInfo } from "../../../../../api/types";

const fields = [
  "supports_image",
  "supports_audio",
  "supports_video",
  "supports_tool_calling",
] as const;

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
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 12,
        marginBottom: 16,
      }}
    >
      {fields.map((field) => {
        const override =
          field in changes
            ? changes[field]
            : model.config_overrides?.includes(field)
            ? model[field]
            : null;
        return (
          <label key={field} style={{ display: "grid", gap: 4 }}>
            {t(`models.capabilities.${field}`)}
            <Select
              aria-label={t(`models.capabilities.${field}`)}
              value={override == null ? "auto" : String(override)}
              onChange={(value) =>
                onChange({
                  ...changes,
                  [field]: value === "auto" ? null : value === "true",
                })
              }
              options={[
                { value: "auto", label: t("models.capabilities.auto") },
                { value: "true", label: t("models.capabilities.supported") },
                { value: "false", label: t("models.capabilities.unsupported") },
              ]}
            />
          </label>
        );
      })}
    </div>
  );
}
