import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, InputNumber, Slider, Switch } from "@agentscope-ai/design";
import { Segmented } from "antd";
import { RotateCcw } from "lucide-react";
import type { ModelInfo, ProviderInfo } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { JsonConfigEditor } from "./JsonConfigEditor";

function requestMaxTokens(model: ModelInfo): number | null {
  const value = model.generate_kwargs?.max_tokens;
  return typeof value === "number" ? value : null;
}

function editableGenerateConfig(
  generateKwargs: Record<string, unknown>,
): Record<string, unknown> {
  const config = { ...generateKwargs };
  delete config.max_tokens;
  return config;
}

export function ModelConfigEditor({
  providerId,
  model,
  onSaved,
  onProviderUpdated,
  onClose,
  isDark,
  thinkingParamStyle,
  reasoningEffortOptions,
  thinkingBudgetRange = [1, 81920],
  chatModel,
}: {
  providerId: string;
  model: ModelInfo;
  onSaved: () => void | Promise<void>;
  onProviderUpdated?: (provider: ProviderInfo) => void;
  onClose: () => void;
  isDark: boolean;
  thinkingParamStyle?: "budget" | "effort" | null;
  reasoningEffortOptions?: string[];
  thinkingBudgetRange?: [number, number];
  chatModel?: string;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const configuredMaxTokens = requestMaxTokens(model);

  const [maxTokens, setMaxTokens] = useState<number | null>(
    configuredMaxTokens,
  );
  const [maxInputLength, setMaxInputLength] = useState<number | null>(
    model.max_input_length ?? 131072,
  );
  const [maxInputLengthDirty, setMaxInputLengthDirty] = useState(false);
  const [relayReasoning, setRelayReasoning] = useState<boolean>(
    model.relay_reasoning ?? true,
  );
  const [thinkingEnabled, setThinkingEnabled] = useState<boolean | null>(
    model.thinking_enabled ?? null,
  );
  const [thinkingBudget, setThinkingBudget] = useState<number | null>(
    model.thinking_budget ?? null,
  );
  const [reasoningEffort, setReasoningEffort] = useState<string | null>(
    model.reasoning_effort ?? null,
  );

  const initialText = useMemo(() => {
    const config = editableGenerateConfig(model.generate_kwargs);
    return Object.keys(config).length > 0
      ? JSON.stringify(config, null, 2)
      : "";
  }, [model.generate_kwargs]);

  const [text, setText] = useState(initialText);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setText(initialText);
    setMaxTokens(configuredMaxTokens);
    setMaxInputLength(model.max_input_length ?? 131072);
    setMaxInputLengthDirty(false);
    setRelayReasoning(model.relay_reasoning ?? true);
    setThinkingEnabled(model.thinking_enabled ?? null);
    setThinkingBudget(model.thinking_budget ?? null);
    setReasoningEffort(model.reasoning_effort ?? null);
    setDirty(false);
  }, [
    initialText,
    configuredMaxTokens,
    model.max_input_length,
    model.relay_reasoning,
    model.thinking_enabled,
    model.thinking_budget,
    model.reasoning_effort,
  ]);

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
        delete parsed.max_tokens;
      } catch {
        message.error(t("models.generateConfigInvalidJson"));
        return;
      }
    }
    if (maxTokens !== null) {
      parsed.max_tokens = maxTokens;
    }

    setSaving(true);
    try {
      const updated = await api.configureModel(providerId, model.id, {
        ...(maxInputLengthDirty
          ? { max_input_length: effectiveMaxInputLength }
          : {}),
        generate_kwargs: parsed,
        relay_reasoning: relayReasoning,
        thinking_enabled: thinkingEnabled,
        thinking_budget: thinkingBudget,
        reasoning_effort: reasoningEffort,
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
          <div
            style={{
              ...labelStyle,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span>{t("models.maxTokensLabel", "Max Tokens")}</span>
            {maxTokens !== null && (
              <Button
                type="text"
                size="small"
                icon={<RotateCcw size={14} />}
                aria-label={t("models.resetMaxTokens", "Reset to auto")}
                title={t("models.resetMaxTokens", "Reset to auto")}
                onClick={() => handleMaxTokensChange(null)}
              />
            )}
          </div>
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={1024}
            value={maxTokens}
            placeholder={t("models.providerDefault", "Provider default")}
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
            <br />
            {t("models.maxOutputCapabilityLabel", "Model capability")}:{" "}
            {model.max_output_length?.toLocaleString() ??
              t("models.unknown", "Unknown")}
            {model.max_output_length_source &&
              model.max_output_length_source !== "unknown" && (
                <> · {model.max_output_length_source}</>
              )}
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
      {/* Enable Thinking (only for providers that support thinking config) */}
      {thinkingParamStyle && (
        <>
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
                {t("models.thinkingModeLabel")}
              </span>
              <div
                style={{
                  fontSize: 11,
                  color: isDark ? "rgba(255,255,255,0.35)" : "#999",
                  marginTop: 2,
                }}
              >
                {t("models.thinkingModeHint")}
              </div>
            </div>
            <Switch
              checked={thinkingEnabled === true}
              onChange={(checked) => {
                setThinkingEnabled(checked);
                setDirty(true);
              }}
            />
          </div>

          {thinkingEnabled === true && (
            <div style={{ marginBottom: 12 }}>
              {thinkingParamStyle === "budget" ? (
                <div>
                  <div
                    style={{
                      ...labelStyle,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <span>{t("models.thinkingBudgetLabel")}</span>
                    <a
                      style={{ fontSize: 11, cursor: "pointer" }}
                      onClick={() => {
                        setThinkingBudget(
                          thinkingBudget === null
                            ? thinkingBudgetRange[0]
                            : null,
                        );
                        setDirty(true);
                      }}
                    >
                      {thinkingBudget === null
                        ? t("models.switchToManual")
                        : t("models.switchToAuto")}
                    </a>
                  </div>
                  {thinkingBudget !== null ? (
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 12 }}
                    >
                      <div style={{ flex: 1 }}>
                        <Slider
                          min={thinkingBudgetRange[0]}
                          max={thinkingBudgetRange[1]}
                          step={1024}
                          value={thinkingBudget}
                          onChange={(val: number) => {
                            setThinkingBudget(val);
                            setDirty(true);
                          }}
                        />
                      </div>
                      <InputNumber
                        style={{ width: 100 }}
                        min={thinkingBudgetRange[0]}
                        max={thinkingBudgetRange[1]}
                        step={1024}
                        value={thinkingBudget}
                        onChange={(val) => {
                          setThinkingBudget(val);
                          setDirty(true);
                        }}
                      />
                    </div>
                  ) : (
                    <div
                      style={{
                        fontSize: 11,
                        color: isDark ? "rgba(255,255,255,0.35)" : "#999",
                        marginTop: 2,
                      }}
                    >
                      {t("models.thinkingBudgetHint")}
                    </div>
                  )}
                </div>
              ) : (
                <div>
                  <div style={labelStyle}>
                    {t("models.reasoningEffortLabel")}
                  </div>
                  <Segmented
                    block
                    value={reasoningEffort ?? "__auto__"}
                    onChange={(val) => {
                      const v = val as string;
                      setReasoningEffort(v === "__auto__" ? null : v);
                      setDirty(true);
                    }}
                    options={[
                      { label: t("models.switchToAuto"), value: "__auto__" },
                      ...(
                        reasoningEffortOptions ?? [
                          "none",
                          "minimal",
                          "low",
                          "medium",
                          "high",
                          "xhigh",
                        ]
                      ).map((v) => ({
                        label: v.charAt(0).toUpperCase() + v.slice(1),
                        value: v,
                      })),
                    ]}
                  />
                </div>
              )}
            </div>
          )}
        </>
      )}
      {/* Responses API models handle reasoning via native reasoning items
         that the API requires to be echoed back; relay_reasoning has no
         effect, so hide the toggle to avoid confusion. */}
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
        placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  }\n}`}
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
