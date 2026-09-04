import { Bot, ChevronDown } from "lucide-react";
import { Tooltip } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { providerApi } from "@/api/modules/provider";
import type { ModelSlotConfig } from "@/api/types";
import { AdvisorSetupPopover } from "@/components/LoopInput";
import { useAdvisorMode } from "@/stores/advisorModeStore";
import { useLoopStore } from "@/stores/loopStore";
import { buildEligibleProviders } from "./modelSelectorModels";

import styles from "./index.module.less";

export const ADVISOR_LOOP_MODE_ID = "plugin:advisor";

/** Whether the current chat is an Advisor conversation (running, or a new
 * one with Advisor picked in the composer). */
export function useIsAdvisorConversation(): boolean {
  return useLoopStore(
    (s) =>
      (s.sessionState !== "idle" &&
        s.activeMode?.id === ADVISOR_LOOP_MODE_ID) ||
      s.selectedModeId === ADVISOR_LOOP_MODE_ID,
  );
}

/**
 * Replaces the chat header's model pill in an Advisor conversation: the
 * single "current model" would only be the advisor's default while the
 * worker runs on another model, so the pill shows the pair and opens the
 * same Advisor models panel the composer uses.
 */
export function AdvisorModelsPill() {
  const { t } = useTranslation();
  const { state } = useAdvisorMode();
  const [open, setOpen] = useState(false);
  const [names, setNames] = useState<Map<string, string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    providerApi
      .listProviders()
      .then((list) => {
        if (cancelled) return;
        const map = new Map<string, string>();
        buildEligibleProviders(list).forEach((provider) =>
          provider.models.forEach((model) =>
            map.set(`${provider.id}:${model.id}`, model.name || model.id),
          ),
        );
        setNames(map);
      })
      .catch(() => {
        if (!cancelled) setNames(new Map());
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const label = useMemo(() => {
    const name = (slot: ModelSlotConfig | null | undefined) =>
      slot
        ? names?.get(`${slot.provider_id}:${slot.model}`) ?? slot.model
        : "-";
    const advisor = name(state.advisor_model);
    const worker = state.worker_model ? name(state.worker_model) : advisor;
    return `${advisor} \u2192 ${worker}`;
  }, [names, state.advisor_model, state.worker_model]);

  return (
    <AdvisorSetupPopover
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
    >
      <Tooltip title={t("loop.advisorSetup.pairTooltip")} mouseEnterDelay={0.5}>
        <button
          type="button"
          aria-expanded={open}
          aria-label={t("loop.advisorSetup.openAria")}
          className={[
            styles.trigger,
            styles.advisorPair,
            open ? styles.triggerActive : "",
          ].join(" ")}
          data-testid="advisor-models-pill"
        >
          <Bot size={16} />
          <span className={`${styles.triggerName} ${styles.advisorPairName}`}>
            {label}
          </span>
          <ChevronDown size={14} />
        </button>
      </Tooltip>
    </AdvisorSetupPopover>
  );
}
