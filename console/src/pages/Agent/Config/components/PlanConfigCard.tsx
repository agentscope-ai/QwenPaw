import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Form,
  InputNumber,
  Switch,
  message,
} from "@agentscope-ai/design";
import { Radio, Spin, Typography } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { PlanConfig } from "../../../../api/types";
import styles from "../index.module.less";

const { Text } = Typography;

export function PlanConfigCard() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<PlanConfig>({
    enabled: false,
    max_subtasks: null,
    storage_type: "memory",
    storage_path: null,
    agent_managed: true,
  });

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getPlanConfig();
      setConfig(data);
    } catch {
      // Plan config not available — keep defaults
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const save = useCallback(
    async (updated: PlanConfig) => {
      setSaving(true);
      try {
        const result = await api.updatePlanConfig(updated);
        setConfig(result);
        message.success(
          t("agentConfig.planSaveSuccess", "Plan settings saved"),
        );
      } catch (err) {
        const errMsg =
          err instanceof Error ? err.message : "Failed to save plan config";
        message.error(errMsg);
      } finally {
        setSaving(false);
      }
    },
    [t],
  );

  const handleToggle = useCallback(
    (checked: boolean) => {
      const updated = { ...config, enabled: checked };
      setConfig(updated);
      save(updated);
    },
    [config, save],
  );

  const handleMaxSubtasksChange = useCallback(
    (value: number | null) => {
      const updated = { ...config, max_subtasks: value };
      setConfig(updated);
    },
    [config],
  );

  const handleStorageTypeChange = useCallback(
    (e: { target: { value?: string } }) => {
      const value = (e.target.value ?? "memory") as "memory" | "file";
      const updated = { ...config, storage_type: value };
      setConfig(updated);
      save(updated);
    },
    [config, save],
  );

  const handleAgentManagedToggle = useCallback(
    (checked: boolean) => {
      const updated = { ...config, agent_managed: checked };
      setConfig(updated);
      save(updated);
    },
    [config, save],
  );

  const handleMaxSubtasksBlur = useCallback(() => {
    save(config);
  }, [config, save]);

  if (loading) {
    return (
      <Card
        className={styles.formCard}
        title={t("agentConfig.planTitle", "Planning")}
        style={{ marginTop: 16 }}
      >
        <Spin />
      </Card>
    );
  }

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.planTitle", "Planning")}
      style={{ marginTop: 16 }}
    >
      <Form layout="vertical">
        <Form.Item label={t("agentConfig.planEnabled", "Enable Plan Mode")}>
          <Switch
            checked={config.enabled}
            onChange={handleToggle}
            loading={saving}
          />
          <Text
            type="secondary"
            style={{ display: "block", marginTop: 4, fontSize: 12 }}
          >
            {t(
              "agentConfig.planEnabledDesc",
              "When enabled, the agent will break down complex tasks into structured subtasks and execute them step by step.",
            )}
          </Text>
        </Form.Item>

        <Form.Item label={t("agentConfig.planMaxSubtasks", "Max Subtasks")}>
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={1}
            value={config.max_subtasks}
            onChange={handleMaxSubtasksChange}
            onBlur={handleMaxSubtasksBlur}
            disabled={!config.enabled || saving}
            placeholder={t(
              "agentConfig.planMaxSubtasksPlaceholder",
              "None (Unlimited)",
            )}
          />
        </Form.Item>

        <Form.Item label={t("agentConfig.planStorageType", "Plan Storage")}>
          <Radio.Group
            value={config.storage_type}
            onChange={handleStorageTypeChange}
            disabled={!config.enabled || saving}
          >
            <Radio value="memory">
              {t(
                "agentConfig.planStorageMemory",
                "In Memory (resets on restart)",
              )}
            </Radio>
            <Radio value="file">
              {t("agentConfig.planStorageFile", "Persistent (saved to disk)")}
            </Radio>
          </Radio.Group>
        </Form.Item>

        <Form.Item
          label={t(
            "agentConfig.planAgentManaged",
            "Agent can create plans autonomously",
          )}
        >
          <Switch
            checked={config.agent_managed}
            onChange={handleAgentManagedToggle}
            disabled={!config.enabled || saving}
          />
        </Form.Item>
      </Form>
    </Card>
  );
}
