import { Bot } from "lucide-react";
import { Popover, Select } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { advisorModeApi } from "../../api/modules/advisorMode";
import { providerApi } from "../../api/modules/provider";
import type { ModelSlotConfig } from "../../api/types";
import {
  buildEligibleProviders,
  type EligibleProvider,
} from "../../pages/Chat/ModelSelector/modelSelectorModels";
import { useAdvisorMode } from "../../stores/advisorModeStore";
import styles from "./index.module.less";

/** Loop-catalog id of Advisor Mode (`plugin:<mode name>`). */
export const ADVISOR_LOOP_MODE_ID = "plugin:advisor";

const DEFAULT_KEY = "";

type Slot = ModelSlotConfig | null | undefined;

function slotKey(slot: Slot): string {
  return slot ? `${slot.provider_id}:${slot.model}` : DEFAULT_KEY;
}

function slotLabel(slot: Slot): string {
  return slot ? `${slot.provider_id} / ${slot.model}` : "";
}

interface AdvisorSetupPopoverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  compact?: boolean;
}

/**
 * The two models of an Advisor conversation, offered right where the mode
 * is picked: the composer opens this once Advisor is chosen from the
 * loop-mode menu, and the button stays next to the mode pill so it can be
 * reopened while the conversation runs. Defaults follow the agent's main
 * model (advisor) and sub-agent model (worker); a choice here is saved for
 * the agent through /api/advisor-mode, the same setting the Advisor loop
 * template shows.
 */
export function AdvisorSetupPopover({
  open,
  onOpenChange,
  compact = false,
}: AdvisorSetupPopoverProps) {
  const { t } = useTranslation();
  const { state, setAdvisorMode } = useAdvisorMode();
  const [providers, setProviders] = useState<EligibleProvider[] | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || providers !== null) return;
    let cancelled = false;
    providerApi
      .listProviders()
      .then((list) => {
        if (!cancelled) setProviders(buildEligibleProviders(list));
      })
      .catch(() => {
        if (!cancelled) setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, providers]);

  const options = useMemo(
    () =>
      (providers ?? []).flatMap((provider) =>
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

  const withDefault = (current: Slot, defaultLabel: string) => {
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
    setSaving(true);
    try {
      setAdvisorMode(await advisorModeApi.update({ [field]: slot }));
    } finally {
      setSaving(false);
    }
  };

  // Show the default slots the way the options are named (provider display
  // name + model name) and put the model first, so a truncated label still
  // shows which model it is.
  const displayName = (slot: Slot) => {
    if (!slot) return "-";
    const key = slotKey(slot);
    return (
      options.find((option) => option.value === key)?.label ?? slotLabel(slot)
    );
  };
  const advisorDefault = t("loop.advisorSetup.mainModelDefault", {
    model: displayName(state.main_model),
  });
  const workerDefault = state.subagent_model
    ? t("loop.advisorSetup.subagentDefault", {
        model: displayName(state.subagent_model),
      })
    : t("loop.advisorSetup.noSubagent");

  const content = (
    <div className={styles.advisorSetup} data-testid="advisor-setup">
      <div className={styles.advisorSetupTitle}>
        {t("loop.advisorSetup.title")}
      </div>
      <div className={styles.advisorSetupHint}>
        {t("loop.advisorSetup.hint")}
      </div>
      <label className={styles.advisorRow}>
        <span>{t("loop.advisorSetup.advisorModel")}</span>
        <Select
          aria-label={t("loop.advisorSetup.advisorModel")}
          className={styles.advisorSelect}
          disabled={saving}
          loading={providers === null}
          optionFilterProp="label"
          options={withDefault(state.advisor_model_override, advisorDefault)}
          showSearch
          value={slotKey(state.advisor_model_override)}
          onChange={(value: string) => void save("advisor_model", value)}
        />
      </label>
      <label className={styles.advisorRow}>
        <span>{t("loop.advisorSetup.workerModel")}</span>
        <Select
          aria-label={t("loop.advisorSetup.workerModel")}
          className={styles.advisorSelect}
          disabled={saving}
          loading={providers === null}
          optionFilterProp="label"
          options={withDefault(state.worker_model_override, workerDefault)}
          showSearch
          value={slotKey(state.worker_model_override)}
          onChange={(value: string) => void save("worker_model", value)}
        />
      </label>
      <div className={styles.advisorSummary}>
        {t("loop.advisorSetup.summary", {
          advisor: slotLabel(state.advisor_model) || "-",
          worker:
            slotLabel(state.worker_model) ||
            t("loop.advisorSetup.sameAsAdvisor"),
        })}
      </div>
    </div>
  );

  return (
    <Popover
      arrow={false}
      content={content}
      onOpenChange={onOpenChange}
      open={open}
      overlayClassName={styles.modePopover}
      placement="topLeft"
      trigger="click"
    >
      <button
        aria-expanded={open}
        aria-label={t("loop.advisorSetup.openAria")}
        className={styles.modelsButton}
        type="button"
      >
        <Bot size={14} />
        {!compact && <span>{t("loop.advisorSetup.button")}</span>}
      </button>
    </Popover>
  );
}
