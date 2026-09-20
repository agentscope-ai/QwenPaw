import { ModelChoice } from "./ModelChoice";
import { ThinkingControl } from "@/features/thinking/ThinkingControl";
import type {
  ThinkingPreference,
  ThinkingControlSpec,
} from "@/features/thinking/types";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  LoaderCircle,
  Save,
  Settings2,
  RotateCcw,
} from "lucide-react";
import { Switch } from "antd";
import { useTranslation } from "react-i18next";

import { agentsApi } from "@/api/modules/agents";
import type {
  AgentProfileConfig,
  ModelInfo,
  ModelSlotConfig,
} from "@/api/types";
import { useAppMessage } from "@/hooks/useAppMessage";

import styles from "./index.module.less";

interface SettingsProvider {
  id: string;
  name: string;
  models: ModelInfo[];
}

interface AgentModelSettingsProps {
  expanded?: boolean;
  agentId?: string;
  providers: SettingsProvider[];
  activeProviderId?: string;
  activeModelId?: string;
  showThinking?: boolean;
  initialConfig?: Pick<
    AgentProfileConfig,
    | "fallback_models"
    | "fallback_policy"
    | "subagent_model"
    | "thinking_level"
    | "thinking_budget"
  >;
  draftResetToken?: number;
  onDraftChange?: (
    settings: Pick<
      AgentProfileConfig,
      | "fallback_models"
      | "fallback_policy"
      | "subagent_model"
      | "thinking_level"
      | "thinking_budget"
    >,
  ) => void;
}

interface ModelOption {
  key: string;
  label: string;
  providerId: string;
  modelId: string;
  supportsThinking: boolean;
  thinkingControl?: ThinkingControlSpec | null;
}

const EMPTY_KEY = "";

function slotKey(providerId: string, modelId: string): string {
  return `${providerId}:${modelId}`;
}

function supportsThinking(_provider: SettingsProvider, model: ModelInfo) {
  return model.supports_agent_thinking === true;
}

export function AgentModelSettings({
  agentId,
  expanded = false,
  providers,
  activeProviderId,
  activeModelId,
  showThinking = true,
  initialConfig,
  draftResetToken,
  onDraftChange,
}: AgentModelSettingsProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [open, setOpen] = useState(!agentId);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<AgentProfileConfig | null>(null);
  const [fallbackEnabled, setFallbackEnabled] = useState(true);
  const [fallbackKeys, setFallbackKeys] = useState<string[]>([]);
  const [subagentKey, setSubagentKey] = useState(EMPTY_KEY);
  const [thinking, setThinking] = useState<ThinkingPreference>({
    level: "inherit",
  });
  const loadRevision = useRef(0);
  const saveRevision = useRef(0);
  const configAgentId = useRef<string | null>(null);
  const agentIdRef = useRef(agentId);
  agentIdRef.current = agentId;
  const bodyId = useId();
  const draftTokenRef = useRef<number | undefined>();

  const options = useMemo<ModelOption[]>(
    () =>
      providers.flatMap((provider) =>
        provider.models.map((model) => ({
          key: slotKey(provider.id, model.id),
          label: `${provider.name} / ${model.name || model.id}`,
          providerId: provider.id,
          modelId: model.id,
          supportsThinking: supportsThinking(provider, model),
          thinkingControl: model.thinking_control,
        })),
      ),
    [providers],
  );
  const optionByKey = useMemo(
    () => new Map(options.map((option) => [option.key, option])),
    [options],
  );
  const slotByKey = useMemo(() => {
    const slots = new Map<string, ModelSlotConfig>();
    options.forEach((option) => {
      slots.set(option.key, {
        provider_id: option.providerId,
        model: option.modelId,
      });
    });
    (config?.fallback_models ?? []).forEach((slot) => {
      slots.set(slotKey(slot.provider_id, slot.model), slot);
    });
    if (config?.subagent_model) {
      slots.set(
        slotKey(config.subagent_model.provider_id, config.subagent_model.model),
        config.subagent_model,
      );
    }
    return slots;
  }, [config, options]);
  const activeOption = optionByKey.get(
    slotKey(activeProviderId ?? "", activeModelId ?? ""),
  );
  const thinkingSupported = activeOption?.supportsThinking ?? false;
  function applyConfig(next: AgentProfileConfig, targetAgentId: string): void {
    configAgentId.current = targetAgentId;
    setConfig(next);
    setFallbackEnabled(next.fallback_policy?.enabled ?? true);
    setFallbackKeys(
      (next.fallback_models ?? []).map((slot) =>
        slotKey(slot.provider_id, slot.model),
      ),
    );
    setSubagentKey(
      next.subagent_model
        ? slotKey(next.subagent_model.provider_id, next.subagent_model.model)
        : EMPTY_KEY,
    );
    setThinking({
      level: next.thinking_level ?? "inherit",
      budget_tokens: next.thinking_budget,
    });
  }

  useEffect(() => {
    if (agentId) return;
    if (draftTokenRef.current === draftResetToken && config) return;
    draftTokenRef.current = draftResetToken;
    applyConfig(
      {
        id: "draft",
        name: "",
        ...initialConfig,
      } as AgentProfileConfig,
      "draft",
    );
    setOpen(true);
  }, [agentId, config, draftResetToken, initialConfig]);

  useEffect(() => {
    if (!agentId) return;
    loadRevision.current += 1;
    saveRevision.current += 1;
    configAgentId.current = null;
    setConfig(null);
    setLoadError(null);
    setLoading(false);
    setSaving(false);
    setOpen(false);
  }, [agentId]);

  const loadConfig = async (force = false) => {
    if (!agentId) return;
    if ((!force && config) || loading) return;
    const targetAgentId = agentId;
    const revision = ++loadRevision.current;
    setLoadError(null);
    setLoading(true);
    try {
      const next = await agentsApi.getAgent(targetAgentId);
      if (revision !== loadRevision.current || targetAgentId !== agentId) {
        return;
      }
      applyConfig(next, targetAgentId);
    } catch (error) {
      if (revision !== loadRevision.current || targetAgentId !== agentId) {
        return;
      }
      const text =
        error instanceof Error
          ? error.message
          : t("modelSelector.agentSettingsLoadFailed");
      setLoadError(text);
      message.error(text);
    } finally {
      if (revision === loadRevision.current && targetAgentId === agentId) {
        setLoading(false);
      }
    }
  };

  const toggleOpen = async () => {
    const next = !open;
    setOpen(next);
    if (next) await loadConfig(true);
  };

  const [choosingFallback, setChoosingFallback] = useState(false);
  useEffect(() => {
    if (expanded && agentId) {
      setOpen(true);
      void loadConfig(true);
    }
  }, [expanded, agentId]);
  const pickSlot = (slot: ModelSlotConfig) => {
    const key = slotKey(slot.provider_id, slot.model);
    slotByKey.set(key, slot);
    return key;
  };
  function notifyDraft({
    fallbackEnabled: nextFallbackEnabled = fallbackEnabled,
    fallbackKeys: nextFallbackKeys = fallbackKeys,
    subagentKey: nextSubagentKey = subagentKey,
    thinking: nextThinking = thinking,
  }: {
    fallbackEnabled?: boolean;
    fallbackKeys?: string[];
    subagentKey?: string;
    thinking?: ThinkingPreference;
  } = {}): void {
    if (agentId || !onDraftChange || !config) return;
    const fallbackModels = nextFallbackKeys.flatMap((key) => {
      const slot = slotByKey.get(key);
      return slot ? [slot] : [];
    });
    onDraftChange({
      fallback_models: fallbackModels,
      fallback_policy: {
        enabled: nextFallbackEnabled,
        target_scope: "configured",
      },
      subagent_model: slotByKey.get(nextSubagentKey) ?? null,
      thinking_level: nextThinking.level,
      thinking_budget: nextThinking.budget_tokens ?? null,
    });
  }

  const save = async () => {
    if (!agentId || !config || saving || configAgentId.current !== agentId) {
      return;
    }
    const targetAgentId = agentId;
    const revision = ++saveRevision.current;
    setSaving(true);
    try {
      const fallbackModels = fallbackKeys.flatMap((key) => {
        const slot = slotByKey.get(key);
        return slot ? [slot] : [];
      });
      const subagentSlot = slotByKey.get(subagentKey);
      const settings = {
        fallback_models: fallbackModels,
        fallback_policy: {
          enabled: fallbackEnabled,
          target_scope: "configured" as const,
        },
        subagent_model: subagentSlot ?? null,
        ...(showThinking && thinkingSupported
          ? {
              thinking_level: thinking.level,
              thinking_budget: thinking.budget_tokens ?? null,
            }
          : {}),
      };
      const updated = await agentsApi.updateModelSettings(
        targetAgentId,
        settings,
      );
      if (
        revision !== saveRevision.current ||
        targetAgentId !== agentIdRef.current
      ) {
        return;
      }
      applyConfig(updated, targetAgentId);
      message.success(t("modelSelector.agentSettingsSaved"));
    } catch (error) {
      if (
        revision !== saveRevision.current ||
        targetAgentId !== agentIdRef.current
      ) {
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("modelSelector.agentSettingsSaveFailed"),
      );
    } finally {
      if (revision === saveRevision.current) {
        setSaving(false);
      }
    }
  };

  return (
    <section className={styles.agentModelSettings}>
      {!expanded && (
        <button
          type="button"
          className={styles.agentSettingsToggle}
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={toggleOpen}
        >
          <Settings2 size={14} />
          <span>{t("modelSelector.agentModelSettings")}</span>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      )}
      {open && (
        <div id={bodyId} className={styles.agentSettingsBody}>
          {loading ? (
            <div className={styles.settingsStatus} role="status">
              <LoaderCircle size={16} className={styles.spinning} />
              <span>{t("modelSelector.loadingAgentSettings")}</span>
            </div>
          ) : loadError || !config ? (
            <div className={styles.settingsError} role="alert">
              <span>
                {loadError ?? t("modelSelector.agentSettingsLoadFailed")}
              </span>
              <button type="button" onClick={() => void loadConfig()}>
                {t("modelSelector.retry")}
              </button>
            </div>
          ) : (
            <>
              {showThinking && (
                <ThinkingControl
                  control={
                    activeOption?.thinkingControl ?? {
                      kind: "unknown",
                      efforts: [],
                      supports_off: false,
                    }
                  }
                  value={thinking}
                  onChange={(next) => {
                    setThinking(next);
                    notifyDraft({ thinking: next });
                  }}
                  disabled={saving}
                />
              )}
              <div className={styles.settingLine}>
                <span>{t("modelSelector.subagentModel")}</span>
                <ModelChoice
                  ariaLabel={t("modelSelector.subagentModel")}
                  value={slotByKey.get(subagentKey)}
                  label={
                    optionByKey.get(subagentKey)?.label ??
                    (subagentKey || t("modelSelector.sameAsPrimary"))
                  }
                  disabled={saving}
                  onChange={(slot) => {
                    const key = pickSlot(slot);
                    setSubagentKey(key);
                    notifyDraft({ subagentKey: key });
                  }}
                />
                <button
                  type="button"
                  aria-label={t("modelSelector.sameAsPrimary")}
                  disabled={!subagentKey || saving}
                  onClick={() => {
                    setSubagentKey(EMPTY_KEY);
                    notifyDraft({ subagentKey: EMPTY_KEY });
                  }}
                >
                  <RotateCcw size={15} />
                </button>
              </div>
              <div className={styles.settingLine}>
                <span>{t("modelSelector.enableFallback")}</span>
                <Switch
                  aria-label={t("modelSelector.enableFallback")}
                  size="small"
                  checked={fallbackEnabled}
                  disabled={saving}
                  onChange={(next) => {
                    if (next && !fallbackKeys.length) {
                      setChoosingFallback(true);
                      return;
                    }
                    setFallbackEnabled(next);
                    notifyDraft({ fallbackEnabled: next });
                  }}
                />
              </div>
              {(fallbackEnabled || choosingFallback) && (
                <div className={styles.settingLine}>
                  <span>{t("modelSelector.chooseFallback")}</span>
                  <ModelChoice
                    ariaLabel={t("modelSelector.chooseFallback")}
                    open={choosingFallback}
                    onOpenChange={setChoosingFallback}
                    value={slotByKey.get(fallbackKeys[0])}
                    label={
                      optionByKey.get(fallbackKeys[0])?.label ??
                      (fallbackKeys[0] || t("modelSelector.chooseFallback"))
                    }
                    disabled={saving}
                    onChange={(slot) => {
                      const keys = [pickSlot(slot)];
                      setFallbackKeys(keys);
                      setFallbackEnabled(true);
                      notifyDraft({
                        fallbackKeys: keys,
                        fallbackEnabled: true,
                      });
                    }}
                  />
                </div>
              )}
              {agentId && (
                <button
                  type="button"
                  className={styles.saveAgentSettings}
                  aria-label={t(
                    showThinking
                      ? "common.save"
                      : "modelSelector.saveAgentSettings",
                  )}
                  disabled={saving}
                  onClick={save}
                >
                  {saving ? (
                    <LoaderCircle size={14} className={styles.spinning} />
                  ) : (
                    <Save size={14} />
                  )}
                  {t(
                    showThinking
                      ? "common.save"
                      : "modelSelector.saveAgentSettings",
                  )}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
