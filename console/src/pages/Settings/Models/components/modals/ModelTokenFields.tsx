import { Button, InputNumber } from "@agentscope-ai/design";
import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelInfo } from "../../../../../api/types";

interface TokenFieldProps {
  showHint?: boolean;
  value: number | null;
  onChange: (value: number | null) => void;
}

const labelStyle = {
  fontSize: 13,
  color: "var(--app-text)",
  marginBottom: 4,
};
const hintStyle = {
  fontSize: 11,
  color: "var(--app-text-quaternary)",
  marginTop: 2,
};

export function ContextLengthField({
  value,
  onChange,
  showHint = true,
}: TokenFieldProps) {
  const { t } = useTranslation();
  return (
    <div>
      <div style={labelStyle}>{t("models.maxInputLengthLabel")}</div>
      <InputNumber
        aria-label={t("models.maxInputLengthLabel")}
        style={{ width: "100%" }}
        min={1000}
        step={1024}
        value={value}
        placeholder="131072"
        onChange={onChange}
      />
      {showHint && (
        <div style={hintStyle}>{t("models.maxInputLengthHint")}</div>
      )}
    </div>
  );
}

export function OutputTokenLimitField({
  value,
  onChange,
  model,
  showHint = true,
}: TokenFieldProps & {
  model?: Pick<ModelInfo, "max_output_length" | "max_output_length_source">;
}) {
  const { t, i18n } = useTranslation();
  return (
    <div>
      <div
        style={{
          ...labelStyle,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span>{t("models.maxTokensLabel")}</span>
        {value !== null && (
          <Button
            type="text"
            size="small"
            icon={<RotateCcw size={14} />}
            aria-label={t("models.resetMaxTokens")}
            title={t("models.resetMaxTokens")}
            onClick={() => onChange(null)}
          />
        )}
      </div>
      <InputNumber
        aria-label={t("models.maxTokensLabel")}
        style={{ width: "100%" }}
        min={1}
        max={model?.max_output_length ?? undefined}
        step={1024}
        value={value}
        placeholder={t("models.providerDefault")}
        onChange={onChange}
      />
      {showHint && (
        <div style={hintStyle}>
          {t("models.maxTokensHint")}
          <br />
          {t("models.maxOutputCapabilityLabel")}:{" "}
          {model?.max_output_length?.toLocaleString(i18n.language) ??
            t("models.unknown")}
          {model?.max_output_length_source &&
            model.max_output_length_source !== "unknown" && (
              <> · {model.max_output_length_source}</>
            )}
        </div>
      )}
    </div>
  );
}
