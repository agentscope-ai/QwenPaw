import InlineHelp from "../../../../../components/InlineHelp";
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

export function ContextLengthField({
  value,
  onChange,
  showHint = true,
  source,
  onReset,
}: TokenFieldProps & { source?: string | null; onReset?: () => void }) {
  const { t } = useTranslation();
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
        <span>
          {t("models.maxInputLengthLabel")}
          {showHint && (
            <InlineHelp>
              {t("models.maxInputLengthHint")}
              {source && (
                <>
                  <br />
                  {t(`models.metadataSource.${source}`)}
                </>
              )}
            </InlineHelp>
          )}
        </span>
        {onReset && (
          <Button
            type="text"
            size="small"
            icon={<RotateCcw size={14} />}
            aria-label={t("models.resetContextLength")}
            title={t("models.resetContextLength")}
            onClick={onReset}
          />
        )}
      </div>
      <InputNumber
        aria-label={t("models.maxInputLengthLabel")}
        style={{ width: "100%" }}
        min={1000}
        step={1024}
        value={value}
        placeholder={t("models.automatic")}
        onChange={onChange}
      />
    </div>
  );
}

export function OutputTokenLimitField({
  value,
  onChange,
  model,
  showHint = true,
  chatModel,
}: TokenFieldProps & {
  chatModel?: string;
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
        <span>
          {t("models.maxTokensLabel")}
          {showHint && (
            <InlineHelp>
              {t(
                chatModel === "AnthropicChatModel"
                  ? "models.anthropicOutputHint"
                  : "models.maxTokensHint",
              )}
              <br />
              {t("models.maxOutputCapabilityLabel")}:{" "}
              {model?.max_output_length?.toLocaleString(i18n.language) ??
                t("models.unknown")}
              {model?.max_output_length_source &&
                model.max_output_length_source !== "unknown" && (
                  <>
                    {" "}
                    ·{" "}
                    {t(
                      `models.metadataSource.${model.max_output_length_source}`,
                    )}
                  </>
                )}
            </InlineHelp>
          )}
        </span>
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
        placeholder={
          model?.max_output_length
            ? t("models.pool.outputDefault", {
                value: model.max_output_length.toLocaleString(i18n.language),
              })
            : t("models.providerDefault")
        }
        onChange={onChange}
      />
    </div>
  );
}
