import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  LoaderCircle,
  Save,
  Settings2,
  Trash2,
} from "lucide-react";
import { Segmented, Select } from "antd";
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
  agentId?: string;
  providers: SettingsProvider[];
  activeProviderId?: string;
  activeModelId?: string;
  showThinking?: boolean;
  initialConfig?: Pick<
    AgentProfileConfig,
    "fallback_models" | "fallback_policy" | "subagent_model"
  >;
  draftResetToken?: number;
  onDraftChange?: (
    settings: Pick<
      AgentProfileConfig,
      "fallback_models" | "fallback_policy" | "subagent_model"
    >,
  ) => void;
}

interface ModelOption {
  key: string;
  label: string;
  providerId: string;
  modelId: string;
  supportsThinking: boolean;
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
  const [fallbackScope, setFallbackScope] = useState<
    "configured" | "free_only"
  >("configured");
  const [fallbackKeys, setFallbackKeys] = useState<string[]>([]);
  const [subagentKey, setSubagentKey] = useState(EMPTY_KEY);
  const [thinkingLevel, setThinkingLevel] = useState<
    "inherit" | "off" | "low" | "medium" | "high"
  >("inherit");
  const loadRevision = useRef(0);
  const saveRevision = useRef(0);
  const configAgentId = useRef<string | null>(null);
  const agentIdRef = useRef(agentId);
  agentIdRef.current = agentId;
  const bodyId = useId();
  const thinkingSelectId = `${bodyId}-thinking-level`;
  const subagentSelectId = `${bodyId}-subagent-model`;
  const fallbackScopeSelectId = `${bodyId}-fallback-scope`;
  const fallbackSelectId = `${bodyId}-fallback-model`;
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
  const activeKey = activeOption?.key ?? EMPTY_KEY;
  const thinkingSupported = activeOption?.supportsThinking ?? false;
  const modelSelectOptions = useMemo(
    () =>
      options.map((option) => ({
        label: option.label,
        value: option.key,
      })),
    [options],
  );
  const subagentOptions = useMemo(() => {
    const items = [
      {
        label: t("modelSelector.sameAsPrimary"),
        value: EMPTY_KEY,
      },
    ];
    if (subagentKey && !optionByKey.has(subagentKey)) {
      items.push({ label: subagentKey, value: subagentKey });
    }
    return [...items, ...modelSelectOptions];
  }, [modelSelectOptions, optionByKey, subagentKey, t]);
  const fallbackOptions = useMemo(
    () => [
      {
        label: t("modelSelector.chooseFallback"),
        value: EMPTY_KEY,
      },
      ...modelSelectOptions.filter(
        (option) =>
          option.value !== activeKey && !fallbackKeys.includes(option.value),
      ),
    ],
    [activeKey, fallbackKeys, modelSelectOptions, t],
  );

  function applyConfig(next: AgentProfileConfig, targetAgentId: string): void {
    configAgentId.current = targetAgentId;
    setConfig(next);
    setFallbackEnabled(next.fallback_policy?.enabled ?? true);
    setFallbackScope(next.fallback_policy?.target_scope ?? "configured");
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
    setThinkingLevel(next.thinking_level ?? "inherit");
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

  const moveFallback = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= fallbackKeys.length) return;
    const nextFallbackKeys = [...fallbackKeys];
    [nextFallbackKeys[index], nextFallbackKeys[target]] = [
      nextFallbackKeys[target],
      nextFallbackKeys[index],
    ];
    setFallbackKeys(nextFallbackKeys);
    notifyDraft({ fallbackKeys: nextFallbackKeys });
  };

  const addFallback = (fallbackKey: string) => {
    if (!fallbackKey || fallbackKeys.includes(fallbackKey)) return;
    const nextFallbackKeys = [...fallbackKeys, fallbackKey];
    setFallbackKeys(nextFallbackKeys);
    notifyDraft({ fallbackKeys: nextFallbackKeys });
  };

  function notifyDraft({
    fallbackEnabled: nextFallbackEnabled = fallbackEnabled,
    fallbackKeys: nextFallbackKeys = fallbackKeys,
    fallbackScope: nextFallbackScope = fallbackScope,
    subagentKey: nextSubagentKey = subagentKey,
  }: {
    fallbackEnabled?: boolean;
    fallbackKeys?: string[];
    fallbackScope?: typeof fallbackScope;
    subagentKey?: string;
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
        target_scope: nextFallbackScope,
      },
      subagent_model: slotByKey.get(nextSubagentKey) ?? null,
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
          target_scope: fallbackScope,
        },
        subagent_model: subagentSlot ?? null,
        ...(showThinking && thinkingSupported
          ? { thinking_level: thinkingLevel }
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
                <>
                  <label
                    className={styles.settingsRow}
                    htmlFor={thinkingSelectId}
                  >
                    <span>{t("modelSelector.thinkingLevel")}</span>
                    <Select
                      id={thinkingSelectId}
                      aria-label={t("modelSelector.thinkingLevel")}
                      className={styles.agentSelect}
                      classNames={{
                        popup: { root: styles.agentSelectDropdown },
                      }}
                      value={thinkingLevel}
                      disabled={!thinkingSupported}
                      options={(
                        ["inherit", "off", "low", "medium", "high"] as const
                      ).map((level) => ({
                        label: t(`modelSelector.thinking.${level}`),
                        value: level,
                      }))}
                      onChange={(value) =>
                        setThinkingLevel(value as typeof thinkingLevel)
                      }
                    />
                  </label>
                  {!thinkingSupported && (
                    <p className={styles.settingsHint}>
                      {t("modelSelector.thinkingUnsupported")}
                    </p>
                  )}
                </>
              )}
              <div className={styles.settingsSection}>
                <div className={styles.settingsSectionHeader}>
                  <span className={styles.settingsSectionTitle}>
                    {t("modelSelector.subagentModel")}
                  </span>
                </div>
                <label
                  className={styles.settingsControl}
                  htmlFor={subagentSelectId}
                >
                  <Select
                    id={subagentSelectId}
                    aria-label={t("modelSelector.subagentModel")}
                    className={styles.agentSelect}
                    classNames={{
                      popup: { root: styles.agentSelectDropdown },
                    }}
                    value={subagentKey}
                    options={subagentOptions}
                    showSearch
                    optionFilterProp="label"
                    listHeight={280}
                    popupMatchSelectWidth={320}
                    onChange={(value) => {
                      setSubagentKey(value);
                      notifyDraft({ subagentKey: value });
                    }}
                  />
                </label>
              </div>
              <div className={styles.settingsSection}>
                <label className={styles.settingsCheckRow}>
                  <input
                    type="checkbox"
                    checked={fallbackEnabled}
                    onChange={(event) => {
                      const nextFallbackEnabled = event.target.checked;
                      setFallbackEnabled(nextFallbackEnabled);
                      notifyDraft({ fallbackEnabled: nextFallbackEnabled });
                    }}
                  />
                  <span>{t("modelSelector.enableFallback")}</span>
                </label>
                {fallbackEnabled && (
                  <div className={styles.fallbackSettings}>
                    <div className={styles.settingsField}>
                      <span className={styles.settingsFieldLabel}>
                        {t("modelSelector.fallbackScope")}
                      </span>
                      {showThinking ? (
                        <Select
                          id={fallbackScopeSelectId}
                          aria-label={t("modelSelector.fallbackScope")}
                          className={styles.agentSelect}
                          classNames={{
                            popup: { root: styles.agentSelectDropdown },
                          }}
                          value={fallbackScope}
                          options={[
                            {
                              label: t("modelSelector.configuredModels"),
                              value: "configured",
                            },
                            {
                              label: t("modelSelector.freeModelsOnly"),
                              value: "free_only",
                            },
                          ]}
                          onChange={(value) => {
                            const nextFallbackScope =
                              value as typeof fallbackScope;
                            setFallbackScope(nextFallbackScope);
                            notifyDraft({ fallbackScope: nextFallbackScope });
                          }}
                        />
                      ) : (
                        <Segmented
                          aria-label={t("modelSelector.fallbackScope")}
                          className={styles.fallbackScope}
                          block
                          value={fallbackScope}
                          options={[
                            {
                              label: t("modelSelector.configuredModels"),
                              value: "configured",
                            },
                            {
                              label: t("modelSelector.freeModelsOnly"),
                              value: "free_only",
                            },
                          ]}
                          onChange={(value) => {
                            const nextFallbackScope =
                              value as typeof fallbackScope;
                            setFallbackScope(nextFallbackScope);
                            notifyDraft({ fallbackScope: nextFallbackScope });
                          }}
                        />
                      )}
                    </div>
                    <div className={styles.settingsField}>
                      <span className={styles.settingsFieldLabel}>
                        {t("modelSelector.chooseFallback")}
                      </span>
                      <div className={styles.fallbackComposer}>
                        <label
                          className={styles.srOnly}
                          htmlFor={fallbackSelectId}
                        >
                          {t("modelSelector.chooseFallback")}
                        </label>
                        <Select
                          id={fallbackSelectId}
                          aria-label={t("modelSelector.chooseFallback")}
                          className={styles.agentSelect}
                          classNames={{
                            popup: { root: styles.agentSelectDropdown },
                          }}
                          value={EMPTY_KEY}
                          options={fallbackOptions}
                          showSearch
                          optionFilterProp="label"
                          listHeight={280}
                          popupMatchSelectWidth={320}
                          onChange={addFallback}
                        />
                      </div>
                    </div>
                    <div className={styles.fallbackList}>
                      {fallbackKeys.map((key, index) => (
                        <div key={key}>
                          <span title={optionByKey.get(key)?.label ?? key}>
                            {optionByKey.get(key)?.label ?? key}
                          </span>
                          <button
                            type="button"
                            aria-label={t("modelSelector.moveFallbackUp", {
                              model: optionByKey.get(key)?.label ?? key,
                            })}
                            disabled={index === 0}
                            onClick={() => moveFallback(index, -1)}
                          >
                            <ChevronUp size={13} />
                          </button>
                          <button
                            type="button"
                            aria-label={t("modelSelector.moveFallbackDown", {
                              model: optionByKey.get(key)?.label ?? key,
                            })}
                            disabled={index === fallbackKeys.length - 1}
                            onClick={() => moveFallback(index, 1)}
                          >
                            <ChevronDown size={13} />
                          </button>
                          <button
                            type="button"
                            aria-label={t("modelSelector.removeFallback", {
                              model: optionByKey.get(key)?.label ?? key,
                            })}
                            onClick={() =>
                              (() => {
                                const nextFallbackKeys = fallbackKeys.filter(
                                  (item) => item !== key,
                                );
                                setFallbackKeys(nextFallbackKeys);
                                notifyDraft({
                                  fallbackKeys: nextFallbackKeys,
                                });
                              })()
                            }
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
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
