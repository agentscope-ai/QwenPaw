import InlineHelp from "../../../../../components/InlineHelp";
import { ThinkingControl } from "@/features/thinking/ThinkingControl";
import type { ThinkingLevel } from "@/features/thinking/types";
import { ThinkingCapabilityFields } from "./ThinkingCapabilityFields";
import type { ThinkingControlSpec } from "@/features/thinking/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Switch } from "@agentscope-ai/design";
import type { ModelInfo, ProviderInfo } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { ContextLengthField, OutputTokenLimitField } from "./ModelTokenFields";
import { JsonConfigEditor } from "./JsonConfigEditor";
import {
  ModelCapabilitiesFields,
  type CapabilityOverrides,
} from "./ModelCapabilitiesFields";

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
  thinkingParamStyle?: "budget" | "effort" | null;
  reasoningEffortOptions?: string[];
  thinkingBudgetRange?: [number, number];
  chatModel?: string;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const [thinkingDeclaration, setThinkingDeclaration] = useState<
    ThinkingControlSpec | null | undefined
  >();
  const [capabilities, setCapabilities] = useState<CapabilityOverrides>({});
  const configuredMaxTokens = requestMaxTokens(model);

  const [maxTokens, setMaxTokens] = useState<number | null>(
    configuredMaxTokens,
  );
  const resolvedContext =
    model.effective_max_input_length ?? model.max_input_length;
  const [maxInputLength, setMaxInputLength] = useState<number | null>(
    resolvedContext,
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
    setCapabilities({});
    setThinkingDeclaration(undefined);
    setText(initialText);
    setMaxTokens(configuredMaxTokens);
    setMaxInputLength(resolvedContext);
    setMaxInputLengthDirty(false);
    setRelayReasoning(model.relay_reasoning ?? true);
    setThinkingEnabled(model.thinking_enabled ?? null);
    setThinkingBudget(model.thinking_budget ?? null);
    setReasoningEffort(model.reasoning_effort ?? null);
    setDirty(false);
  }, [
    initialText,
    configuredMaxTokens,
    resolvedContext,
    model.relay_reasoning,
    model.thinking_enabled,
    model.thinking_budget,
    model.reasoning_effort,
  ]);

  const effectiveMaxInputLength =
    maxInputLength ?? model.automatic_max_input_length ?? resolvedContext;

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
        ...capabilities,
        ...(thinkingDeclaration !== undefined
          ? { thinking_control: thinkingDeclaration }
          : {}),
        ...(maxInputLengthDirty ? { max_input_length: maxInputLength } : {}),
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

  return (
    <div style={{ padding: "8px 0 4px" }}>
      <ThinkingCapabilityFields
        value={
          thinkingDeclaration === undefined
            ? model.thinking_control
            : thinkingDeclaration
        }
        onChange={(next) => {
          setThinkingDeclaration(next);
          setDirty(true);
        }}
      />
      <ModelCapabilitiesFields
        model={model}
        changes={capabilities}
        onChange={(value) => {
          setCapabilities(value);
          setDirty(true);
        }}
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 16,
          marginBottom: 12,
        }}
      >
        <OutputTokenLimitField
          value={maxTokens}
          onChange={handleMaxTokensChange}
          model={model}
          chatModel={chatModel}
        />
        <ContextLengthField
          value={effectiveMaxInputLength}
          onChange={handleMaxInputLengthChange}
          source={
            maxInputLengthDirty && maxInputLength !== null
              ? "user"
              : maxInputLength === null
              ? "automatic"
              : model.context_length_source
          }
          onReset={
            model.max_input_length_configured ||
            (maxInputLengthDirty && maxInputLength !== null)
              ? () => handleMaxInputLengthChange(null)
              : undefined
          }
        />
      </div>
      {(model.thinking_control || thinkingParamStyle) && (
        <ThinkingControl
          control={
            model.thinking_control ?? {
              kind: thinkingParamStyle === "budget" ? "budget" : "effort",
              supports_off: true,
              efforts: (
                reasoningEffortOptions ?? ["low", "medium", "high"]
              ).filter((v) => v !== "none") as ThinkingLevel[],
              budget_min: thinkingBudgetRange[0],
              budget_max: thinkingBudgetRange[1],
            }
          }
          value={
            thinkingEnabled === false || reasoningEffort === "none"
              ? { level: "off" }
              : thinkingBudget != null
              ? { level: "budget", budget_tokens: thinkingBudget }
              : { level: (reasoningEffort || "inherit") as ThinkingLevel }
          }
          onChange={(next) => {
            setThinkingEnabled(
              next.level === "inherit" ? null : next.level !== "off",
            );
            setThinkingBudget(
              next.level === "budget" ? next.budget_tokens ?? null : null,
            );
            setReasoningEffort(
              next.level !== "inherit" &&
                next.level !== "off" &&
                next.level !== "budget"
                ? next.level
                : null,
            );
            setDirty(true);
          }}
        />
      )}
      <details style={{ marginTop: 16 }}>
        <summary>{t("common.advancedSettings")}</summary>
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
                  color: "var(--app-text)",
                }}
              >
                {t("models.relayReasoningLabel")}
              </span>
              <InlineHelp>{t("models.relayReasoningHint")}</InlineHelp>
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

        <InlineHelp>{t("models.modelGenerateConfigHint")}</InlineHelp>
        <JsonConfigEditor
          value={text}
          onChange={handleChange}
          placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  }\n}`}
        />
      </details>
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
