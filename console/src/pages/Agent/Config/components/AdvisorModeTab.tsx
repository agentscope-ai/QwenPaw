import { Form, InputNumber, Select, Switch } from "@agentscope-ai/design";
import {
  Bot,
  HelpCircle,
  LifeBuoy,
  ListChecks,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  advisorModeApi,
  type AdvisorModeUpdate,
} from "../../../../api/modules/advisorMode";
import { providerApi } from "../../../../api/modules/provider";
import type { ModelSlotConfig } from "../../../../api/types";
import { buildEligibleProviders } from "../../../Chat/ModelSelector/modelSelectorModels";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  useAdvisorMode,
  useAdvisorModeStore,
} from "../../../../stores/advisorModeStore";
import styles from "../index.module.less";
import loopStyles from "./AgentLoopCard.module.less";
import { BuiltInIntro, LockedGateCard } from "./LoopModeShared";

type Slot = ModelSlotConfig | null | undefined;

/** "" stands for the default slot in the two model selects. */
const DEFAULT_KEY = "";

function slotKey(slot: Slot): string {
  return slot ? `${slot.provider_id}:${slot.model}` : DEFAULT_KEY;
}

function slotLabel(slot: Slot): string {
  return slot ? `${slot.provider_id} / ${slot.model}` : "";
}

interface ModelOption {
  value: string;
  label: string;
  slot: ModelSlotConfig;
}

/** Every model of a usable provider, as select options. */
function useModelOptions(): ModelOption[] {
  const [options, setOptions] = useState<ModelOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    providerApi
      .listProviders()
      .then((providers) => {
        if (cancelled) return;
        setOptions(
          buildEligibleProviders(providers).flatMap((provider) =>
            provider.models.map((model) => ({
              value: slotKey({ provider_id: provider.id, model: model.id }),
              label: `${provider.name} / ${model.name || model.id}`,
              slot: { provider_id: provider.id, model: model.id },
            })),
          ),
        );
      })
      .catch(() => {
        // The selects still work with the current value and the default.
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return options;
}

/**
 * The "Advisor" loop template in Agent Loop Settings. Laid out like the
 * other built-in templates: the agent-level default switch, then one card
 * per stage of the advisor pipeline (models, opening plan, mid-run
 * intervention, on-demand consultation). Every control saves straight to
 * agent.json through /api/advisor-mode.
 */
export function AdvisorModeTab() {
  const { t } = useTranslation();
  const { state } = useAdvisorMode();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const setAdvisorMode = useAdvisorModeStore((s) => s.setAdvisorMode);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [maxConsults, setMaxConsults] = useState<number | null>(null);
  const options = useModelOptions();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await advisorModeApi.get();
      setAdvisorMode(selectedAgent, next);
      setMaxConsults(next.max_consults);
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
      setMaxConsults(next.max_consults);
    } finally {
      setSaving(false);
    }
  };

  const busy = loading || saving;
  const slotByKey = useMemo(
    () => new Map(options.map((option) => [option.value, option.slot])),
    [options],
  );
  const selectOptions = (current: Slot, defaultLabel: string) => {
    const items = [
      { value: DEFAULT_KEY, label: defaultLabel },
      ...options.map(({ value, label }) => ({ value, label })),
    ];
    // Keep a stored override selectable even when its provider is gone.
    if (current && !slotByKey.has(slotKey(current))) {
      items.push({ value: slotKey(current), label: slotLabel(current) });
    }
    return items;
  };
  const pickSlot = (value: string): ModelSlotConfig | null =>
    value === DEFAULT_KEY ? null : slotByKey.get(value) ?? null;

  const teacherDefault = t("agentConfig.advisorModeMainModel", {
    model: slotLabel(state.main_model) || "-",
  });
  const studentDefault = state.subagent_model
    ? t("agentConfig.advisorModeSubagentModel", {
        model: slotLabel(state.subagent_model),
      })
    : t("agentConfig.advisorModeNoStudent");
  const modelSummary = t("agentConfig.advisorModeModels", {
    teacher: slotLabel(state.teacher_model) || "-",
    student:
      slotLabel(state.student_model) ||
      t("agentConfig.advisorModeSameAsTeacher"),
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

  const commitMaxConsults = () => {
    if (
      maxConsults === null ||
      maxConsults < 0 ||
      maxConsults === state.max_consults
    ) {
      return;
    }
    void update({ max_consults: maxConsults });
  };

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
      <div className={loopStyles.pipelineHeader}>
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
          <Form.Item label={t("agentConfig.advisorModeTeacherModel")}>
            <Select
              showSearch
              optionFilterProp="label"
              aria-label={t("agentConfig.advisorModeTeacherModel")}
              data-testid="advisor-teacher-model"
              disabled={busy}
              value={slotKey(state.teacher_model_override)}
              options={selectOptions(
                state.teacher_model_override,
                teacherDefault,
              )}
              onChange={(value: string) =>
                void update({ teacher_model: pickSlot(value) })
              }
            />
          </Form.Item>
          <Form.Item label={t("agentConfig.advisorModeStudentModel")}>
            <Select
              showSearch
              optionFilterProp="label"
              aria-label={t("agentConfig.advisorModeStudentModel")}
              data-testid="advisor-student-model"
              disabled={busy}
              value={slotKey(state.student_model_override)}
              options={selectOptions(
                state.student_model_override,
                studentDefault,
              )}
              onChange={(value: string) =>
                void update({ student_model: pickSlot(value) })
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
        extra={toggle("followup_enabled", t("agentConfig.advisorModeFollowup"))}
      >
        <p className={loopStyles.readOnlyCopy}>
          {t("agentConfig.advisorModeFollowupHelp")}
        </p>
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
          <InputNumber
            min={0}
            max={50}
            style={{ width: 220 }}
            aria-label={t("agentConfig.advisorModeMaxConsults")}
            disabled={busy}
            value={maxConsults}
            onChange={(value) =>
              setMaxConsults(typeof value === "number" ? value : null)
            }
            onBlur={commitMaxConsults}
            onPressEnter={commitMaxConsults}
          />
        </Form.Item>
      </LockedGateCard>
    </div>
  );
}
