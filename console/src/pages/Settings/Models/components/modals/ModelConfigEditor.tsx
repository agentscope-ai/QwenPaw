import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, InputNumber, Switch } from "@agentscope-ai/design";
import type { ModelInfo, ProviderInfo } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { JsonConfigEditor } from "./JsonConfigEditor";

export function ModelConfigEditor({
  providerId,
  model,
  onSaved,
  onProviderUpdated,
  onClose,
  isDark,
  chatModel,
}: {
  providerId: string;
  model: ModelInfo;
  onSaved: () => void | Promise<void>;
  onProviderUpdated?: (provider: ProviderInfo) => void;
  onClose: () => void;
  isDark: boolean;
  chatModel?: string;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);

  const [maxTokens, setMaxTokens] = useState<number | null>(
    model.max_tokens ?? 8192,
  );
  const [maxInputLength, setMaxInputLength] = useState<number | null>(
    model.max_input_length ?? 131072,
  );
  const [maxInputLengthDirty, setMaxInputLengthDirty] = useState(false);
  const [relayReasoning, setRelayReasoning] = useState<boolean>(
    model.relay_reasoning ?? true,
  );

  const initialText = useMemo(
    () =>
      model.generate_kwargs && Object.keys(model.generate_kwargs).length > 0
        ? JSON.stringify(model.generate_kwargs, null, 2)
        : "",
    [model.generate_kwargs],
  );

  const [text, setText] = useState(initialText);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setText(initialText);
    setMaxTokens(model.max_tokens ?? 8192);
    setMaxInputLength(model.max_input_length ?? 131072);
    setMaxInputLengthDirty(false);
    setRelayReasoning(model.relay_reasoning ?? true);
    setDirty(false);
  }, [
    initialText,
    model.max_tokens,
    model.max_input_length,
    model.relay_reasoning,
  ]);

  const effectiveMaxTokens = maxTokens ?? 8192;
  const effectiveMaxInputLength = maxInputLength ?? 131072;

  const handleChange = useCallback((val: string) => {
    setText(val);
    setDirty(true);
  }, []);

  const handleMaxTokensChange = useCallback((val: number | null) => {
    setMaxTokens(val);
    setDirty(true);
  }, []);

  const handleMaxInputLengthChange = useCallback((val: number | null) => {
    setMaxInputLength(val);
    setMaxInputLengthDirty(true);
    setDirty(true);
  }, []);

  const handleSave = async () => {
    const trimmed = text.trim();
    let parsed: Record<string, unknown> = {};
    if (trimmed) {
      try {
        const obj = JSON.parse(trimmed);
        if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
          message.error(t("models.generateConfigMustBeObject"));
          return;
        }
        parsed = obj;
      } catch {
        message.error(t("models.generateConfigInvalidJson"));
        return;
      }
    }

    setSaving(true);
    try {
      const updated = await api.configureModel(providerId, model.id, {
        max_tokens: effectiveMaxTokens,
        ...(maxInputLengthDirty
          ? { max_input_length: effectiveMaxInputLength }
          : {}),
        generate_kwargs: parsed,
        relay_reasoning: relayReasoning,
      });
      message.success(t("models.modelConfigSaved", { name: model.name }));
      setDirty(false);
      setMaxInputLengthDirty(false);
      onProviderUpdated?.(updated);
      await onSaved();
      onClose();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.modelConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 13,
    color: isDark ? "rgba(255,255,255,0.85)" : "#333",
    marginBottom: 4,
  };

  return (
    <div style={{ padding: "8px 0 4px" }}>
      <div style={{ display: "flex", gap: 16, marginBottom: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={labelStyle}>
            {t("models.maxTokensLabel", "Max Tokens")}
          </div>
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={1024}
            value={maxTokens}
            placeholder="8192"
            onChange={handleMaxTokensChange}
          />
          <div
            style={{
              fontSize: 11,
              color: isDark ? "rgba(255,255,255,0.35)" : "#999",
              marginTop: 2,
            }}
          >
            {t("models.maxTokensHint", "每次响应的最大输出 token 数")}
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={labelStyle}>
            {t("models.maxInputLengthLabel", "Max Context Length")}
          </div>
          <InputNumber
            style={{ width: "100%" }}
            min={1000}
            step={1024}
            value={maxInputLength}
            placeholder="131072"
            onChange={handleMaxInputLengthChange}
          />
          <div
            style={{
              fontSize: 11,
              color: isDark ? "rgba(255,255,255,0.35)" : "#999",
              marginTop: 2,
            }}
          >
            {t(
              "models.maxInputLengthHint",
              "模型上下文窗口大小，控制上下文压缩阈值（≥1000）",
            )}
          </div>
        </div>
      </div>
      {chatModel !== "OpenAIResponseModel" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 8,
            padding: "6px 0",
          }}
        >
          <div>
            <span
              style={{
                fontSize: 13,
                color: isDark ? "rgba(255,255,255,0.85)" : "#333",
              }}
            >
              {t("models.relayReasoningLabel")}
            </span>
            <div
              style={{
                fontSize: 11,
                color: isDark ? "rgba(255,255,255,0.35)" : "#999",
                marginTop: 2,
              }}
            >
              {t("models.relayReasoningHint")}
            </div>
          </div>
          <Switch
            checked={relayReasoning}
            onChange={(checked) => {
              setRelayReasoning(checked);
              setDirty(true);
            }}
          />
        </div>
      )}

      <div
        style={{
          fontSize: 12,
          color: isDark ? "rgba(255,255,255,0.45)" : "#888",
          marginBottom: 4,
        }}
      >
        {t("models.modelGenerateConfigHint")}
      </div>
      <JsonConfigEditor
        value={text}
        onChange={handleChange}
        placeholder={`Example:\n{\n  "top_p": 0.9,\n  "temperature": 0.7\n}`}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginTop: 8,
          gap: 8,
        }}
      >
        <Button
          type="primary"
          size="small"
          loading={saving}
          disabled={!dirty}
          onClick={handleSave}
        >
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}
