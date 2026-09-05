import { Popover, Select } from "antd";
import type { TooltipPlacement } from "antd/es/tooltip";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  advisorModeApi,
  slotKey,
  slotLabel,
  type Slot,
} from "../../api/modules/advisorMode";
import { useEligibleProviders } from "../../pages/Chat/ModelSelector/useEligibleProviders";
import { useAdvisorMode } from "../../stores/advisorModeStore";
import { useSyncAdvisorMode } from "../../stores/useSyncAdvisorMode";
import styles from "./index.module.less";

const DEFAULT_KEY = "";

interface AdvisorSetupPopoverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The element the panel is anchored to (an invisible anchor by default). */
  children?: ReactNode;
  placement?: TooltipPlacement;
}

/**
 * The two models of an Advisor conversation. The chat input opens this
 * right after Advisor is picked from the Loop mode menu. In an Advisor
 * conversation the chat header's model pill shows the pair and reopens
 * it. Defaults follow the agent's primary model (advisor) and sub-agent
 * model (worker). A choice here is saved for the agent through
 * /api/advisor-mode, the same setting the Advisor loop template shows.
 */
export function AdvisorSetupPopover({
  open,
  onOpenChange,
  children,
  placement = "topLeft",
}: AdvisorSetupPopoverProps) {
  const { t } = useTranslation();
  useSyncAdvisorMode();
  const { state, setAdvisorMode } = useAdvisorMode();
  const providers = useEligibleProviders(open);
  const [saving, setSaving] = useState(false);

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

  // Name the default slots the way the options are named (provider
  // display name and model name).
  const displayName = (slot: Slot) => {
    if (!slot) return "-";
    const key = slotKey(slot);
    return (
      options.find((option) => option.value === key)?.label ?? slotLabel(slot)
    );
  };
  const advisorDefault = t("loop.advisorSetup.primaryModelDefault", {
    model: displayName(state.main_model),
  });
  const workerDefault = state.subagent_model
    ? t("loop.advisorSetup.subagentDefault", {
        model: displayName(state.subagent_model),
      })
    : t("loop.advisorSetup.noSubagent");

  const content = (
    // Escape closes it like the mode menu. Clicking the chat input does too.
    <div
      className={styles.advisorSetup}
      data-testid="advisor-setup"
      onKeyDown={(event) => {
        if (event.key === "Escape") onOpenChange(false);
      }}
    >
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
    </div>
  );

  return (
    <Popover
      arrow={false}
      content={content}
      onOpenChange={onOpenChange}
      open={open}
      overlayClassName={styles.modePopover}
      placement={placement}
      trigger="click"
    >
      {children ?? <span className={styles.advisorAnchor} aria-hidden />}
    </Popover>
  );
}
