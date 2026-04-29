import { useState, useEffect, useCallback } from "react";
import { Card, Form, Switch, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  progressObservingApi,
  type ProgressObservingConfigResponse,
} from "../../../../api/modules/progressObserving";
import styles from "../index.module.less";

const HOOK_TYPE_OPTIONS = [
  { value: "post_acting", label: "post_acting" },
  { value: "pre_acting", label: "pre_acting" },
  { value: "post_reply", label: "post_reply" },
  { value: "pre_reply", label: "pre_reply" },
  { value: "post_reasoning", label: "post_reasoning" },
  { value: "pre_reasoning", label: "pre_reasoning" },
  { value: "plan_change", label: "plan_change" },
];

const DEFAULT_CONFIG: ProgressObservingConfigResponse = {
  enabled: false,
  hook_type: "post_acting",
};

export function ProgressObservingCard() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [config, setConfig] =
    useState<ProgressObservingConfigResponse>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    progressObservingApi
      .getConfig()
      .then((cfg) => {
        if (!cancelled) setConfig(cfg);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  const handleToggle = useCallback(
    async (checked: boolean) => {
      setLoading(true);
      const prev = config;
      const next = { ...config, enabled: checked };
      setConfig(next);
      try {
        const res = await progressObservingApi.updateConfig(next);
        setConfig(res);
      } catch {
        setConfig(prev);
      } finally {
        setLoading(false);
      }
    },
    [config],
  );

  const handleHookTypeChange = useCallback(
    async (value: string) => {
      if (!config.enabled) return;
      setLoading(true);
      const prev = config;
      const next = { ...config, hook_type: value };
      setConfig(next);
      try {
        const res = await progressObservingApi.updateConfig(next);
        setConfig(res);
      } catch {
        setConfig(prev);
      } finally {
        setLoading(false);
      }
    },
    [config],
  );

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.progressObservingTitle")}
    >
      <Form.Item
        label={t("agentConfig.progressObservingEnabled")}
        tooltip={t("agentConfig.progressObservingEnabledTooltip")}
      >
        <Switch
          checked={config.enabled}
          loading={loading}
          onChange={handleToggle}
        />
      </Form.Item>

      {config.enabled && (
        <Form.Item
          label={t("agentConfig.progressObservingHookType")}
          tooltip={t("agentConfig.progressObservingHookTypeTooltip")}
        >
          <Select
            value={config.hook_type}
            options={HOOK_TYPE_OPTIONS}
            onChange={handleHookTypeChange}
            loading={loading}
            disabled={loading}
            style={{ width: 220 }}
          />
        </Form.Item>
      )}
    </Card>
  );
}
