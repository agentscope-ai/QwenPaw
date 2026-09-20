import { useEffect, useState } from "react";
import { Select } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../../../api";
import type { ModelInfo } from "../../../../../api/types";

export function ModelInfoPreview({
  providerId,
  modelId,
  templateId,
  onTemplateChange,
}: {
  providerId: string;
  modelId?: string;
  templateId?: string;
  onTemplateChange?: (value?: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [templates, setTemplates] = useState<
    { value: string; label: string }[]
  >([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!onTemplateChange) return;
    let active = true;
    api
      .listModelTemplates()
      .then((items) => {
        if (active)
          setTemplates(
            items.map((item) => ({
              value: item.id,
              label: `${item.name} · ${item.provider_id}`,
            })),
          );
      })
      .catch(() => {
        if (active) setTemplates([]);
      });
    return () => {
      active = false;
    };
  }, [onTemplateChange]);
  useEffect(() => {
    let active = true;
    setInfo(null);
    setFailed(false);
    if (!modelId?.trim()) return;
    const timer = setTimeout(() => {
      api
        .previewModelInfo(providerId, modelId.trim(), templateId)
        .then((result) => {
          if (active) setInfo(result);
        })
        .catch(() => {
          if (active) setFailed(true);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [providerId, modelId, templateId]);
  if (!modelId?.trim()) return null;
  const display = (value?: number | null) =>
    value?.toLocaleString(i18n.language) ?? t("models.unknown");
  return (
    <div style={{ marginBottom: 16, display: "grid", gap: 8 }}>
      {onTemplateChange && (
        <label>
          {t("models.modelTemplate")}
          <Select
            style={{ width: "100%", marginTop: 4 }}
            showSearch
            allowClear
            aria-label={t("models.modelTemplate")}
            placeholder={t("models.automatic")}
            optionFilterProp="label"
            options={templates}
            value={templateId}
            onChange={onTemplateChange}
          />
        </label>
      )}
      <div
        role="status"
        style={{
          fontSize: 12,
          color: "var(--app-text-secondary)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {info ? (
          <>
            {t("models.maxInputLengthLabel")}:{" "}
            {display(info.effective_max_input_length)}
            {" · "}
            {t(
              `models.metadataSource.${
                info.context_length_source ?? "unknown"
              }`,
            )}
            <br />
            {t("models.maxOutputCapabilityLabel")}:{" "}
            {display(info.max_output_length)}
            {" · "}
            {t(
              `models.metadataSource.${
                info.max_output_length_source ?? "unknown"
              }`,
            )}
          </>
        ) : failed ? (
          t("models.modelInfoUnavailable")
        ) : (
          t("common.loading")
        )}
      </div>
    </div>
  );
}
