import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Form,
  InputNumber,
  Switch,
  message,
} from "@agentscope-ai/design";
import { Input } from "antd";
import { Radio, Spin, Typography } from "antd";
import type { RadioChangeEvent } from "antd/es/radio";
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
    (e: RadioChangeEvent) => {
      const value = (e.target.value ?? "memory") as "memory" | "file";
      const updated = { ...config, storage_type: value };
      setConfig(updated);
      save(updated);
    },
    [config, save],
  );

  const handleStoragePathChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = e.target.value.trim();
      setConfig((prev) => ({
        ...prev,
        storage_path: v === "" ? null : v,
      }));
    },
    [],
  );

  const handleMaxSubtasksBlur = useCallback(() => {
    save(config);
  }, [config, save]);

  const handleStoragePathBlur = useCallback(() => {
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
            value={config.max_subtasks ?? undefined}
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

        {config.storage_type === "file" && (
          <Form.Item
            label={t("agentConfig.planStoragePath", "Plan storage file path")}
          >
            <Input
              value={config.storage_path ?? ""}
              onChange={handleStoragePathChange}
              onBlur={handleStoragePathBlur}
              disabled={!config.enabled || saving}
              placeholder={t(
                "agentConfig.planStoragePathPlaceholder",
                "Leave empty to use the server default path",
              )}
            />
            <Text
              type="secondary"
              style={{ display: "block", marginTop: 4, fontSize: 12 }}
            >
              {t(
                "agentConfig.planStoragePathDesc",
                "Relative paths are resolved under the agent workspace.",
              )}
            </Text>
          </Form.Item>
        )}
      </Form>
    </Card>
  );
}
