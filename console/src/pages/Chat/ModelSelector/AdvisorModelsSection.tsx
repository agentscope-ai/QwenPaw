import { useMemo } from "react";
import { Select } from "antd";
import { useTranslation } from "react-i18next";

import { advisorModeApi } from "@/api/modules/advisorMode";
import type { ModelSlotConfig } from "@/api/types";
import { useAdvisorMode } from "@/stores/advisorModeStore";
import { useLoopStore } from "@/stores/loopStore";
import type { EligibleProvider } from "./modelSelectorModels";

import styles from "./index.module.less";

const DEFAULT_KEY = "";

function slotKey(slot: ModelSlotConfig | null | undefined): string {
  return slot ? `${slot.provider_id}:${slot.model}` : DEFAULT_KEY;
}

function slotLabel(slot: ModelSlotConfig | null | undefined): string {
  return slot ? `${slot.provider_id} / ${slot.model}` : "";
}

/**
 * Advisor Mode's two models, right in the chat model selector: what the
 * advisor and the worker currently resolve to, and a way to pick either
 * without leaving the chat. Saved through /api/advisor-mode, the same
 * setting the Advisor loop template edits. Shown only for an Advisor
 * conversation: one already running in Advisor Mode, or a new one with
 * Advisor picked in the composer.
 */
export function AdvisorModelsSection({
  providers,
}: {
  providers: EligibleProvider[];
}) {
  const { t } = useTranslation();
  const { state, setAdvisorMode, initialized } = useAdvisorMode();
  const advisorConversation = useLoopStore(
    (s) =>
      (s.sessionState !== "idle" && s.activeMode?.id === "plugin:advisor") ||
      s.selectedModeId === "plugin:advisor",
  );

  const options = useMemo(
    () =>
      providers.flatMap((provider) =>
        provider.models.map((model) => ({
          value: slotKey({ provider_id: provider.id, model: model.id }),
          label: `${provider.name} / ${model.name || model.id}`,
          slot: { provider_id: provider.id, model: model.id },
        })),
      ),
    [providers],
  );
  const slotByKey = useMemo(
    () => new Map(options.map((option) => [option.value, option.slot])),
    [options],
  );

  if (!initialized || !state.enabled || !advisorConversation) return null;

  const withDefault = (
    current: ModelSlotConfig | null | undefined,
    defaultLabel: string,
  ) => {
    const items = [
      { value: DEFAULT_KEY, label: defaultLabel },
      ...options.map(({ value, label }) => ({ value, label })),
    ];
    if (current && !slotByKey.has(slotKey(current))) {
      items.push({ value: slotKey(current), label: slotLabel(current) });
    }
    return items;
  };
  const save = async (
    field: "advisor_model" | "worker_model",
    value: string,
  ) => {
    const slot = value === DEFAULT_KEY ? null : slotByKey.get(value) ?? null;
    setAdvisorMode(await advisorModeApi.update({ [field]: slot }));
  };

  const advisorDefault = t("agentConfig.advisorModeMainModel", {
    model: slotLabel(state.main_model) || "-",
  });
  const workerDefault = state.subagent_model
    ? t("agentConfig.advisorModeSubagentModel", {
        model: slotLabel(state.subagent_model),
      })
    : t("agentConfig.advisorModeNoStudent");

  return (
    <div className={styles.advisorSection} data-testid="advisor-models">
      <div className={styles.advisorSectionTitle}>
        {t("modelSelector.advisorSection")}
      </div>
      <p className={styles.settingsHint}>
        {t("agentConfig.advisorModeModels", {
          advisor: slotLabel(state.advisor_model) || "-",
          worker:
            slotLabel(state.worker_model) ||
            t("agentConfig.advisorModeSameAsAdvisor"),
        })}
      </p>
      <label className={styles.settingsRow}>
        <span>{t("agentConfig.advisorModeAdvisorModel")}</span>
        <Select
          aria-label={t("agentConfig.advisorModeAdvisorModel")}
          className={styles.agentSelect}
          classNames={{ popup: { root: styles.agentSelectDropdown } }}
          showSearch
          optionFilterProp="label"
          value={slotKey(state.advisor_model_override)}
          options={withDefault(state.advisor_model_override, advisorDefault)}
          onChange={(value: string) => void save("advisor_model", value)}
        />
      </label>
      <label className={styles.settingsRow}>
        <span>{t("agentConfig.advisorModeWorkerModel")}</span>
        <Select
          aria-label={t("agentConfig.advisorModeWorkerModel")}
          className={styles.agentSelect}
          classNames={{ popup: { root: styles.agentSelectDropdown } }}
          showSearch
          optionFilterProp="label"
          value={slotKey(state.worker_model_override)}
          options={withDefault(state.worker_model_override, workerDefault)}
          onChange={(value: string) => void save("worker_model", value)}
        />
      </label>
    </div>
  );
}
