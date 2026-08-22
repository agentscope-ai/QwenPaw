import { Form, Switch } from "@agentscope-ai/design";
import { LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { advisorModeApi } from "../../../../api/modules/advisorMode";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  useAdvisorMode,
  useAdvisorModeStore,
} from "../../../../stores/advisorModeStore";
import styles from "../index.module.less";

function AdvisorModeSetting() {
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

  const update = async (patch: {
    enabled?: boolean;
    plan_enabled?: boolean;
    followup_enabled?: boolean;
    on_demand_enabled?: boolean;
  }) => {
    setSaving(true);
    try {
      const next = await advisorModeApi.update(patch);
      setAdvisorMode(selectedAgent, next);
    } finally {
      setSaving(false);
    }
  };

  const slotLabel = (slot: { provider_id: string; model: string } | null) =>
    slot ? `${slot.provider_id} / ${slot.model}` : "";
  const teacher = slotLabel(state.teacher_model) || "-";
  const student =
    slotLabel(state.student_model) || t("agentConfig.advisorModeNoStudent");

  return (
    <Form.Item className={styles.reactAgentWideField}>
      <div className={styles.advisorModeSetting}>
        <div className={styles.advisorModeModels}>
          {t("agentConfig.advisorModeTooltip")}
        </div>
        <div className={styles.switchSetting}>
          <span>{t("agentConfig.advisorModeDescription")}</span>
          {loading ? (
            <LoaderCircle className={styles.spin} size={16} />
          ) : (
            <Switch
              checked={state.enabled}
              loading={saving}
              onChange={(enabled) => void update({ enabled })}
              aria-label={t("agentConfig.advisorMode")}
            />
          )}
        </div>
        {!loading && state.enabled && (
          <>
            <div className={styles.switchSetting}>
              <span>{t("agentConfig.advisorModePlan")}</span>
              <Switch
                checked={state.plan_enabled}
                loading={saving}
                onChange={(plan_enabled) => void update({ plan_enabled })}
                aria-label={t("agentConfig.advisorModePlan")}
              />
            </div>
            <div className={styles.switchSetting}>
              <span>{t("agentConfig.advisorModeFollowup")}</span>
              <Switch
                checked={state.followup_enabled}
                loading={saving}
                onChange={(followup_enabled) =>
                  void update({ followup_enabled })
                }
                aria-label={t("agentConfig.advisorModeFollowup")}
              />
            </div>
            <div className={styles.switchSetting}>
              <span>{t("agentConfig.advisorModeOnDemand")}</span>
              <Switch
                checked={state.on_demand_enabled}
                loading={saving}
                onChange={(on_demand_enabled) =>
                  void update({ on_demand_enabled })
                }
                aria-label={t("agentConfig.advisorModeOnDemand")}
              />
            </div>
            <div className={styles.advisorModeModels}>
              {t("agentConfig.advisorModeModels", { teacher, student })}
            </div>
          </>
        )}
      </div>
    </Form.Item>
  );
}

/**
 * The "Advisor" entry of the loop templates in Agent Loop Settings. Advisor
 * Mode is selectable from the chat composer like /goal; this panel holds
 * the agent-level default plus the three capability switches.
 */
export function AdvisorModeTab() {
  return <AdvisorModeSetting />;
}
