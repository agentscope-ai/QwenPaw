import { Bot, ChevronDown } from "lucide-react";
import { Tooltip } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { slotKey, type Slot } from "@/api/modules/advisorMode";
import { AdvisorSetupPopover } from "@/components/LoopInput/AdvisorSetupPopover";
import { useAdvisorMode } from "@/stores/advisorModeStore";
import { ADVISOR_LOOP_MODE_ID } from "@/constants/loopMode";
import { useLoopStore } from "@/stores/loopStore";
import { useEligibleProviders } from "./useEligibleProviders";

import styles from "./index.module.less";
import pillStyles from "./AdvisorModelsPill.module.less";

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
 * Replaces the chat header's model pill in an Advisor conversation. The
 * single "current model" would only be the advisor's default while the
 * worker runs on another model, so the pill shows the pair and opens the
 * same Advisor models panel the chat input uses.
 */
export function AdvisorModelsPill() {
  const { t } = useTranslation();
  const { state } = useAdvisorMode();
  const [open, setOpen] = useState(false);
  const providers = useEligibleProviders(true);

  const label = useMemo(() => {
    const names = new Map<string, string>();
    (providers ?? []).forEach((provider) =>
      provider.models.forEach((model) =>
        names.set(
          slotKey({ provider_id: provider.id, model: model.id }),
          model.name || model.id,
        ),
      ),
    );
    const name = (slot: Slot) =>
      slot ? names.get(slotKey(slot)) ?? slot.model : "-";
    const advisor = name(state.advisor_model);
    const worker = state.worker_model ? name(state.worker_model) : advisor;
    return `${advisor} \u2192 ${worker}`;
  }, [providers, state.advisor_model, state.worker_model]);

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
          aria-label={t("loop.advisorSetup.title")}
          className={[
            styles.trigger,
            pillStyles.pair,
            open ? styles.triggerActive : "",
          ].join(" ")}
          data-testid="advisor-models-pill"
        >
          <Bot size={16} />
          <span className={`${styles.triggerName} ${pillStyles.pairName}`}>
            {label}
          </span>
          <ChevronDown size={14} />
        </button>
      </Tooltip>
    </AdvisorSetupPopover>
  );
}
