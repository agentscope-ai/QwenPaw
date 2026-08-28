import {
  ArrowDown,
  ArrowUp,
  GitBranch,
  LoaderCircle,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { Select, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

import { agentsApi } from "@/api/modules/agents";
import { providerApi } from "@/api/modules/provider";
import type {
  AgentProfileConfig,
  ModelInfo,
  ModelSlotConfig,
} from "@/api/types";
import type { ProviderInfo } from "@/api/types/provider";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import { buildEligibleProviders } from "../../../Chat/ModelSelector/modelSelectorModels";
import styles from "../index.module.less";

export interface FallbackModelCardHandle {
  save: () => Promise<void>;
  reset: () => Promise<void>;
}

export interface FallbackModelCardStatus {
  loading: boolean;
  saving: boolean;
}

interface FallbackModelCardProps {
  onStatusChange?: (status: FallbackModelCardStatus) => void;
}

interface FallbackOption {
  key: string;
  label: string;
  providerId: string;
  modelId: string;
}

const EMPTY_KEY = "";

function slotKey(providerId: string, modelId: string): string {
  return `${providerId}:${modelId}`;
}

function modelLabel(provider: { name: string }, model: ModelInfo): string {
  return `${provider.name} / ${model.name || model.id}`;
}

export const FallbackModelCard = forwardRef<
  FallbackModelCardHandle,
  FallbackModelCardProps
>(function FallbackModelCard({ onStatusChange }, ref) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [profile, setProfile] = useState<AgentProfileConfig | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModel, setActiveModel] = useState<ModelSlotConfig | null>(null);
  const [fallbackEnabled, setFallbackEnabled] = useState(true);
  const [fallbackScope, setFallbackScope] = useState<
    "configured" | "free_only"
  >("configured");
  const [fallbackKeys, setFallbackKeys] = useState<string[]>([]);
  const [pendingFallback, setPendingFallback] = useState(EMPTY_KEY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadRevision = useRef(0);
  const saveRevision = useRef(0);
  const selectedAgentRef = useRef(selectedAgent || "default");
  selectedAgentRef.current = selectedAgent || "default";

  const eligibleProviders = useMemo(
    () => buildEligibleProviders(providers),
    [providers],
  );
  const options = useMemo<FallbackOption[]>(
    () =>
      eligibleProviders.flatMap((provider) =>
        provider.models.map((model) => ({
          key: slotKey(provider.id, model.id),
          label: modelLabel(provider, model),
          providerId: provider.id,
          modelId: model.id,
        })),
      ),
    [eligibleProviders],
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
    (profile?.fallback_models ?? []).forEach((slot) => {
      slots.set(slotKey(slot.provider_id, slot.model), slot);
    });
    return slots;
  }, [options, profile]);
  const activeKey = activeModel
    ? slotKey(activeModel.provider_id, activeModel.model)
    : EMPTY_KEY;
  const fallbackOptions = useMemo(
    () => [
      {
        label: t("agentConfig.fallbackChooseModel"),
        value: EMPTY_KEY,
      },
      ...options
        .filter(
          (option) =>
            option.key !== activeKey && !fallbackKeys.includes(option.key),
        )
        .map((option) => ({
          label: option.label,
          value: option.key,
        })),
    ],
    [activeKey, fallbackKeys, options, t],
  );

  const labelForKey = useCallback(
    (key: string) => {
      const option = optionByKey.get(key);
      if (option) return option.label;
      const slot = slotByKey.get(key);
      return slot ? `${slot.provider_id} / ${slot.model}` : key;
    },
    [optionByKey, slotByKey],
  );

  const applyProfile = useCallback((next: AgentProfileConfig) => {
    setProfile(next);
    setFallbackEnabled(next.fallback_policy?.enabled ?? true);
    setFallbackScope(next.fallback_policy?.target_scope ?? "configured");
    setFallbackKeys(
      Array.from(
        new Set(
          (next.fallback_models ?? []).map((slot) =>
            slotKey(slot.provider_id, slot.model),
          ),
        ),
      ),
    );
  }, []);

  const load = useCallback(async () => {
    const targetAgentId = selectedAgent || "default";
    const revision = ++loadRevision.current;
    setLoading(true);
    setLoadError(null);
    try {
      const [nextProfile, nextProviders, nextActive] = await Promise.all([
        agentsApi.getAgent(targetAgentId),
        providerApi.listProviders(),
        providerApi.getActiveModels({
          scope: "effective",
          agent_id: targetAgentId,
        }),
      ]);
      if (
        revision !== loadRevision.current ||
        targetAgentId !== selectedAgentRef.current
      ) {
        return;
      }
      applyProfile(nextProfile);
      setProviders(nextProviders);
      setActiveModel(
        nextActive?.active_llm ?? nextProfile.active_model ?? null,
      );
    } catch (error) {
      if (
        revision !== loadRevision.current ||
        targetAgentId !== selectedAgentRef.current
      ) {
        return;
      }
      const text =
        error instanceof Error
          ? error.message
          : t("agentConfig.fallbackLoadFailed");
      setLoadError(text);
      message.error(text);
    } finally {
      if (
        revision === loadRevision.current &&
        targetAgentId === selectedAgentRef.current
      ) {
        setLoading(false);
      }
    }
  }, [applyProfile, message, selectedAgent, t]);

  const moveFallback = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= fallbackKeys.length) return;
    setFallbackKeys((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const addFallback = () => {
    if (!pendingFallback || fallbackKeys.includes(pendingFallback)) return;
    setFallbackKeys((current) => [...current, pendingFallback]);
    setPendingFallback(EMPTY_KEY);
  };

  const save = useCallback(async () => {
    if (!profile || saving) return;
    const targetAgentId = selectedAgent || "default";
    const revision = ++saveRevision.current;
    setSaving(true);
    try {
      const fallbackModels = fallbackKeys.flatMap((key) => {
        const slot = slotByKey.get(key);
        return slot ? [slot] : [];
      });
      const updated = await agentsApi.updateModelSettings(targetAgentId, {
        fallback_models: fallbackModels,
        fallback_policy: {
          enabled: fallbackEnabled,
          target_scope: fallbackScope,
        },
      });
      if (
        revision !== saveRevision.current ||
        targetAgentId !== selectedAgentRef.current
      ) {
        return;
      }
      applyProfile(updated);
      message.success(t("agentConfig.fallbackSaveSuccess"));
    } catch (error) {
      if (
        revision !== saveRevision.current ||
        targetAgentId !== selectedAgentRef.current
      ) {
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("agentConfig.fallbackSaveFailed"),
      );
    } finally {
      if (revision === saveRevision.current) setSaving(false);
    }
  }, [
    applyProfile,
    fallbackEnabled,
    fallbackKeys,
    fallbackScope,
    message,
    profile,
    saving,
    selectedAgent,
    slotByKey,
    t,
  ]);

  const reset = useCallback(async () => {
    await load();
  }, [load]);

  useImperativeHandle(ref, () => ({ save, reset }), [reset, save]);

  useEffect(() => {
    loadRevision.current += 1;
    saveRevision.current += 1;
    setProfile(null);
    setProviders([]);
    setActiveModel(null);
    setFallbackKeys([]);
    setPendingFallback(EMPTY_KEY);
    void load();
  }, [load]);

  useEffect(() => {
    onStatusChange?.({ loading, saving });
  }, [loading, onStatusChange, saving]);

  if (loading) {
    return (
      <div className={styles.fallbackState} role="status">
        <LoaderCircle size={18} className={styles.spinning} />
        <span>{t("agentConfig.fallbackLoading")}</span>
      </div>
    );
  }

  if (loadError || !profile) {
    return (
      <div className={styles.fallbackError} role="alert">
        <span>{loadError ?? t("agentConfig.fallbackLoadFailed")}</span>
        <button type="button" onClick={() => void load()}>
          <RefreshCw size={14} />
          {t("agentConfig.fallbackRetry")}
        </button>
      </div>
    );
  }

  const primaryLabel = activeKey
    ? labelForKey(activeKey)
    : t("agentConfig.fallbackPrimaryUnavailable");

  return (
    <div className={styles.fallbackCard}>
      <section className={styles.fallbackOverview}>
        <div className={styles.fallbackOverviewHeader}>
          <div className={styles.fallbackTitleGroup}>
            <span className={styles.fallbackIcon}>
              <GitBranch size={18} />
            </span>
            <div>
              <h3>{t("agentConfig.fallbackOverviewTitle")}</h3>
              <p>{t("agentConfig.fallbackOverviewDescription")}</p>
            </div>
          </div>
          <label className={styles.fallbackToggle}>
            <span>{t("agentConfig.fallbackEnabled")}</span>
            <Switch checked={fallbackEnabled} onChange={setFallbackEnabled} />
          </label>
        </div>
        <div className={styles.fallbackSummary}>
          <div>
            <span>{t("agentConfig.fallbackPrimaryModel")}</span>
            <strong title={primaryLabel}>{primaryLabel}</strong>
          </div>
          <div>
            <span>{t("agentConfig.fallbackChain")}</span>
            <strong>
              {t("agentConfig.fallbackChainCount", {
                count: fallbackKeys.length,
              })}
            </strong>
          </div>
          <div>
            <span>{t("agentConfig.fallbackScope")}</span>
            <strong>
              {fallbackScope === "free_only"
                ? t("agentConfig.fallbackFreeModelsOnly")
                : t("agentConfig.fallbackConfiguredModels")}
            </strong>
          </div>
        </div>
      </section>

      <div className={styles.fallbackConfigGrid}>
        <section className={styles.fallbackConfigPanel}>
          <div className={styles.fallbackSectionHeader}>
            <span>01</span>
            <div>
              <h4>{t("agentConfig.fallbackPolicyTitle")}</h4>
              <p>{t("agentConfig.fallbackPolicyDescription")}</p>
            </div>
          </div>
          <label className={styles.fallbackField}>
            <span>{t("agentConfig.fallbackScope")}</span>
            <Select
              aria-label={t("agentConfig.fallbackScope")}
              value={fallbackScope}
              options={[
                {
                  label: t("agentConfig.fallbackConfiguredModels"),
                  value: "configured",
                },
                {
                  label: t("agentConfig.fallbackFreeModelsOnly"),
                  value: "free_only",
                },
              ]}
              onChange={(value) =>
                setFallbackScope(value as typeof fallbackScope)
              }
            />
          </label>
          <p className={styles.fallbackHint}>
            {t("agentConfig.fallbackScopeDescription")}
          </p>
        </section>

        <section className={styles.fallbackConfigPanel}>
          <div className={styles.fallbackSectionHeader}>
            <span>02</span>
            <div>
              <h4>{t("agentConfig.fallbackChain")}</h4>
              <p>{t("agentConfig.fallbackChainDescription")}</p>
            </div>
          </div>
          <div className={styles.fallbackComposer}>
            <Select
              aria-label={t("agentConfig.fallbackChooseModel")}
              value={pendingFallback}
              options={fallbackOptions}
              showSearch
              optionFilterProp="label"
              listHeight={280}
              popupMatchSelectWidth={320}
              onChange={setPendingFallback}
            />
            <button
              type="button"
              className={styles.fallbackIconButton}
              aria-label={t("agentConfig.fallbackAddModel")}
              title={t("agentConfig.fallbackAddModel")}
              disabled={!pendingFallback}
              onClick={addFallback}
            >
              <Plus size={16} />
            </button>
          </div>
          {fallbackKeys.length === 0 ? (
            <div className={styles.fallbackEmpty}>
              <GitBranch size={16} />
              <span>{t("agentConfig.fallbackNoModels")}</span>
            </div>
          ) : (
            <div className={styles.fallbackList}>
              {fallbackKeys.map((key, index) => {
                const label = labelForKey(key);
                return (
                  <div key={key} className={styles.fallbackListItem}>
                    <span className={styles.fallbackOrder}>{index + 1}</span>
                    <span className={styles.fallbackModelName} title={label}>
                      {label}
                    </span>
                    <button
                      type="button"
                      className={styles.fallbackIconButton}
                      aria-label={t("agentConfig.fallbackMoveUp", {
                        model: label,
                      })}
                      title={t("agentConfig.fallbackMoveUp", { model: label })}
                      disabled={index === 0}
                      onClick={() => moveFallback(index, -1)}
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      type="button"
                      className={styles.fallbackIconButton}
                      aria-label={t("agentConfig.fallbackMoveDown", {
                        model: label,
                      })}
                      title={t("agentConfig.fallbackMoveDown", {
                        model: label,
                      })}
                      disabled={index === fallbackKeys.length - 1}
                      onClick={() => moveFallback(index, 1)}
                    >
                      <ArrowDown size={14} />
                    </button>
                    <button
                      type="button"
                      className={styles.fallbackIconButton}
                      aria-label={t("agentConfig.fallbackRemoveModel", {
                        model: label,
                      })}
                      title={t("agentConfig.fallbackRemoveModel", {
                        model: label,
                      })}
                      onClick={() =>
                        setFallbackKeys((current) =>
                          current.filter((item) => item !== key),
                        )
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
});
