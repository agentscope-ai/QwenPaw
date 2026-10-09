import { Form, InputNumber, Select, Switch } from "@agentscope-ai/design";
import {
  Bot,
  HelpCircle,
  LifeBuoy,
  ListChecks,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  advisorModeApi,
  slotLabel,
  type AdvisorInterventionConfig,
  type AdvisorModeUpdate,
  type AdvisorThinking,
} from "../../../../api/modules/advisorMode";
import { useAgentStore } from "../../../../stores/agentStore";
import { fetchAvailableLoopModes } from "../../../../stores/loopStore";
import {
  useAdvisorMode,
  useAdvisorModeStore,
} from "../../../../stores/advisorModeStore";
import { useSyncAdvisorMode } from "../../../../stores/useSyncAdvisorMode";
import styles from "../index.module.less";
import loopStyles from "./AgentLoopCard.module.less";
import tabStyles from "./AdvisorModeTab.module.less";
import { BuiltInIntro, LockedGateCard } from "./LoopModeShared";

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
  useSyncAdvisorMode();
  const { state, initialized } = useAdvisorMode();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const setAdvisorMode = useAdvisorModeStore((s) => s.setAdvisorMode);
  const loading = !initialized;
  const [saving, setSaving] = useState(false);

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
  const modelSummary = t("agentConfig.loopMode.advisorModels", {
    advisor: slotLabel(state.advisor_model) || "-",
    worker:
      slotLabel(state.worker_model) ||
      t("agentConfig.loopMode.advisorSameAsAdvisor"),
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
      <BuiltInIntro
        description={t("agentConfig.loopMode.advisorDescription")}
      />
      <LockedGateCard
        icon={<Sparkles size={15} />}
        title={t("agentConfig.loopMode.advisor")}
        description={t("agentConfig.loopMode.advisorEnableDescription")}
        extra={toggle("enabled", t("agentConfig.loopMode.advisor"))}
      >
        <p className={loopStyles.readOnlyCopy}>
          {t("agentConfig.loopMode.advisorEnableHelp")}
        </p>
      </LockedGateCard>
      {!loading && state.enabled ? (
        <>
          <div
            className={`${loopStyles.pipelineHeader} ${tabStyles.pipelineHeader}`}
          >
            {t("agentConfig.loopMode.advisorPipeline", "Advisor pipeline")}
          </div>
          <LockedGateCard
            icon={<Bot size={15} />}
            title={t("agentConfig.loopMode.advisorModelsTitle")}
            description={modelSummary}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.loopMode.advisorModelsHelp")}
            </p>
            <div
              className={`${loopStyles.fieldGrid} ${tabStyles.thresholdGrid}`}
            >
              <Form.Item
                label={t("agentConfig.loopMode.advisorThinking")}
                tooltip={t("agentConfig.loopMode.advisorThinkingTooltip")}
              >
                <Select
                  aria-label={t("agentConfig.loopMode.advisorThinking")}
                  data-testid="advisor-thinking"
                  disabled={busy}
                  value={state.advisor_thinking}
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
            title={t("agentConfig.loopMode.advisorPlanTitle")}
            description={t("agentConfig.loopMode.advisorPlanDescription")}
            extra={toggle(
              "plan_enabled",
              t("agentConfig.loopMode.advisorPlanTitle"),
            )}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.loopMode.advisorPlanHelp")}
            </p>
          </LockedGateCard>
          <LockedGateCard
            icon={<LifeBuoy size={15} />}
            title={t("agentConfig.loopMode.advisorFollowupTitle")}
            description={t("agentConfig.loopMode.advisorFollowupDescription")}
            extra={toggle(
              "followup_enabled",
              t("agentConfig.loopMode.advisorFollowupTitle"),
            )}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.loopMode.advisorFollowupHelp")}
            </p>
            <div
              className={`${loopStyles.fieldGrid} ${tabStyles.thresholdGrid}`}
            >
              {INTERVENTION_FIELDS.map(({ key, min, max }) => (
                <Form.Item
                  key={key}
                  label={t(`agentConfig.loopMode.advisorIntervention.${key}`)}
                  tooltip={t(
                    `agentConfig.loopMode.advisorIntervention.${key}Tooltip`,
                  )}
                >
                  <CommittedNumber
                    value={intervention[key]}
                    min={min}
                    max={max}
                    label={t(`agentConfig.loopMode.advisorIntervention.${key}`)}
                    testId={`advisor-intervention-${key}`}
                    disabled={busy}
                    onCommit={(value) =>
                      void update({ intervention: { [key]: value } })
                    }
                  />
                </Form.Item>
              ))}
            </div>
          </LockedGateCard>
          <LockedGateCard
            icon={<HelpCircle size={15} />}
            title={t("agentConfig.loopMode.advisorOnDemandTitle")}
            description={t("agentConfig.loopMode.advisorOnDemandDescription")}
            extra={toggle(
              "on_demand_enabled",
              t("agentConfig.loopMode.advisorOnDemandTitle"),
            )}
          >
            <p className={loopStyles.readOnlyCopy}>
              {t("agentConfig.loopMode.advisorOnDemandHelp")}
            </p>
            <Form.Item
              label={t("agentConfig.loopMode.advisorMaxConsults")}
              tooltip={t("agentConfig.loopMode.advisorMaxConsultsTooltip")}
            >
              <div style={{ maxWidth: 220 }}>
                <CommittedNumber
                  value={state.max_consults}
                  min={0}
                  max={200}
                  label={t("agentConfig.loopMode.advisorMaxConsults")}
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
