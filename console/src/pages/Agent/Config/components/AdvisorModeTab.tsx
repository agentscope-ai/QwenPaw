import { Form, InputNumber, Select, Switch } from "@agentscope-ai/design";
import {
  Bot,
  HelpCircle,
  LifeBuoy,
  ListChecks,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  advisorModeApi,
  type AdvisorInterventionConfig,
  type AdvisorModeUpdate,
  type AdvisorThinking,
} from "../../../../api/modules/advisorMode";
import type { ModelSlotConfig } from "../../../../api/types";
import { useAgentStore } from "../../../../stores/agentStore";
import { fetchAvailableLoopModes } from "../../../../stores/loopStore";
import {
  useAdvisorMode,
  useAdvisorModeStore,
} from "../../../../stores/advisorModeStore";
import styles from "../index.module.less";
import loopStyles from "./AgentLoopCard.module.less";
import { BuiltInIntro, LockedGateCard } from "./LoopModeShared";

type Slot = ModelSlotConfig | null | undefined;

function slotLabel(slot: Slot): string {
  return slot ? `${slot.provider_id} / ${slot.model}` : "";
}

/**
 * A number field that saves when the user is done (blur / Enter) rather
 * than on every keystroke, so a value typed digit by digit is one write.
 */
function CommittedNumber({
  value,
  min,
  max,
  label,
  disabled,
  testId,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  label: string;
  disabled: boolean;
  testId: string;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState<number | null>(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);
  const commit = () => {
    if (draft === null || draft < min || draft > max || draft === value) {
      setDraft(value);
      return;
    }
    onCommit(draft);
  };
  return (
    <InputNumber
      min={min}
      max={max}
      style={{ width: "100%" }}
      aria-label={label}
      data-testid={testId}
      disabled={disabled}
      value={draft}
      onChange={(next) => setDraft(typeof next === "number" ? next : null)}
      onBlur={commit}
      onPressEnter={commit}
    />
  );
}

const THINKING_LEVELS: AdvisorThinking[] = [
  "inherit",
  "off",
  "low",
  "medium",
  "high",
];

const INTERVENTION_FIELDS: {
  key: keyof AdvisorInterventionConfig;
  min: number;
  max: number;
}[] = [
  { key: "consecutive_failures", min: 1, max: 50 },
  { key: "window_failures", min: 1, max: 50 },
  { key: "window_size", min: 1, max: 200 },
  { key: "max_interventions", min: 0, max: 50 },
  { key: "cooldown_steps", min: 0, max: 200 },
];

export function AdvisorModeTab() {
  const { t } = useTranslation();
  const { state } = useAdvisorMode();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const setAdvisorMode = useAdvisorModeStore((s) => s.setAdvisorMode);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await advisorModeApi.get();
      setAdvisorMode(selectedAgent, next);
    } finally {
      setLoading(false);
    }
  }, [selectedAgent, setAdvisorMode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const update = async (patch: AdvisorModeUpdate) => {
    setSaving(true);
    try {
      const next = await advisorModeApi.update(patch);
      setAdvisorMode(selectedAgent, next);
      if (patch.enabled !== undefined) {
        // The switch adds/removes Advisor in the composer's mode menu.
        void fetchAvailableLoopModes();
      }
    } finally {
      setSaving(false);
    }
  };

  const busy = loading || saving;
  const modelSummary = t("agentConfig.advisorModeModels", {
    advisor: slotLabel(state.advisor_model) || "-",
    worker:
      slotLabel(state.worker_model) ||
      t("agentConfig.advisorModeSameAsAdvisor"),
  });

  const toggle = (
    key: "enabled" | "plan_enabled" | "followup_enabled" | "on_demand_enabled",
    label: string,
  ) =>
    loading ? (
      <LoaderCircle className={styles.spin} size={16} aria-label={label} />
    ) : (
      <Switch
        checked={state[key]}
        loading={saving}
        onChange={(value) => void update({ [key]: value })}
        aria-label={label}
      />
    );

  const intervention = state.intervention;

  return (
    <div className={loopStyles.modeEditor}>
      <BuiltInIntro description={t("agentConfig.advisorModeTooltip")} />
      <LockedGateCard
        icon={<Sparkles size={15} />}
        title={t("agentConfig.advisorMode")}
        description={t("agentConfig.advisorModeDescription")}
        extra={toggle("enabled", t("agentConfig.advisorMode"))}
      >
        <p className={loopStyles.readOnlyCopy}>
          {t("agentConfig.advisorModeEnableHelp")}
        </p>
      </LockedGateCard>
      {!loading && state.enabled ? (
        <>
          <div
            className={`${loopStyles.pipelineHeader} ${loopStyles.pipelineHeaderAfterCard}`}
          >
            {t("agentConfig.loopMode.advisorPipeline", "Advisor pipeline")}
          </div>
          <LockedGateCard
            icon={<Bot size={15} />}
            title={t("agentConfig.advisorModeModelsTitle")}
            description={modelSummary}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.advisorModeModelsHelp")}
            </p>
            <div className={loopStyles.fieldGrid}>
              <Form.Item
                label={t("agentConfig.advisorModeThinking")}
                tooltip={t("agentConfig.advisorModeThinkingTooltip")}
              >
                <Select
                  aria-label={t("agentConfig.advisorModeThinking")}
                  data-testid="advisor-thinking"
                  disabled={busy}
                  value={state.advisor_thinking ?? "inherit"}
                  options={THINKING_LEVELS.map((level) => ({
                    value: level,
                    label: t(`modelSelector.thinking.${level}`),
                  }))}
                  onChange={(value: AdvisorThinking) =>
                    void update({ advisor_thinking: value })
                  }
                />
              </Form.Item>
            </div>
          </LockedGateCard>
          <LockedGateCard
            icon={<ListChecks size={15} />}
            title={t("agentConfig.advisorModePlanTitle")}
            description={t("agentConfig.advisorModePlanDescription")}
            extra={toggle("plan_enabled", t("agentConfig.advisorModePlan"))}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.advisorModePlanHelp")}
            </p>
          </LockedGateCard>
          <LockedGateCard
            icon={<LifeBuoy size={15} />}
            title={t("agentConfig.advisorModeFollowupTitle")}
            description={t("agentConfig.advisorModeFollowupDescription")}
            extra={toggle(
              "followup_enabled",
              t("agentConfig.advisorModeFollowup"),
            )}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.advisorModeFollowupHelp")}
            </p>
            {intervention ? (
              <div className={loopStyles.fieldGrid}>
                {INTERVENTION_FIELDS.map(({ key, min, max }) => (
                  <Form.Item
                    key={key}
                    label={t(`agentConfig.advisorIntervention.${key}`)}
                    tooltip={t(`agentConfig.advisorIntervention.${key}Tooltip`)}
                  >
                    <CommittedNumber
                      value={intervention[key]}
                      min={min}
                      max={max}
                      label={t(`agentConfig.advisorIntervention.${key}`)}
                      testId={`advisor-intervention-${key}`}
                      disabled={busy}
                      onCommit={(value) =>
                        void update({ intervention: { [key]: value } })
                      }
                    />
                  </Form.Item>
                ))}
              </div>
            ) : null}
          </LockedGateCard>
          <LockedGateCard
            icon={<HelpCircle size={15} />}
            title={t("agentConfig.advisorModeOnDemandTitle")}
            description={t("agentConfig.advisorModeOnDemandDescription")}
            extra={toggle(
              "on_demand_enabled",
              t("agentConfig.advisorModeOnDemand"),
            )}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.advisorModeOnDemandHelp")}
            </p>
            <Form.Item
              label={t("agentConfig.advisorModeMaxConsults")}
              tooltip={t("agentConfig.advisorModeMaxConsultsTooltip")}
            >
              <div style={{ maxWidth: 220 }}>
                <CommittedNumber
                  value={state.max_consults ?? 32}
                  min={0}
                  max={200}
                  label={t("agentConfig.advisorModeMaxConsults")}
                  testId="advisor-max-consults"
                  disabled={busy}
                  onCommit={(value) => void update({ max_consults: value })}
                />
              </div>
            </Form.Item>
          </LockedGateCard>
        </>
      ) : null}
    </div>
  );
}
