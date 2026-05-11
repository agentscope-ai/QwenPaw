import { useCallback, useEffect, useState } from "react";
import {
  Form,
  InputNumber,
  Select,
  Card,
  Alert,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import { planApi } from "../../../../api/modules/plan";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  CONTEXT_MANAGER_BACKEND_OPTIONS,
  MEMORY_MANAGER_BACKEND_OPTIONS,
} from "../../../../constants/backendMappings";
import styles from "../index.module.less";

const LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];

interface ReactAgentCardProps {
  language: string;
  savingLang: boolean;
  onLanguageChange: (value: string) => void;
  timezone: string;
  savingTimezone: boolean;
  onTimezoneChange: (value: string) => void;
}

export function ReactAgentCard({
  language,
  savingLang,
  onLanguageChange,
  timezone,
  savingTimezone,
  onTimezoneChange,
}: ReactAgentCardProps) {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [planEnabled, setPlanEnabled] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig()
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  const handlePlanToggle = useCallback(
    async (checked: boolean) => {
      setPlanLoading(true);
      const prev = planEnabled;
      setPlanEnabled(checked);
      try {
        const res = await planApi.updatePlanConfig({ enabled: checked });
        setPlanEnabled(res.enabled);
      } catch {
        setPlanEnabled(prev);
      } finally {
        setPlanLoading(false);
      }
    },
    [planEnabled],
  );

  return (
    <Card className={styles.formCard} title={t("agentConfig.reactAgentTitle")}>
      <div className={styles.reactAgentRow}>
        <Form.Item
          label={t("agentConfig.language")}
          tooltip={t("agentConfig.languageTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            value={language}
            options={LANGUAGE_OPTIONS}
            onChange={onLanguageChange}
            loading={savingLang}
            disabled={savingLang}
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.timezone")}
          tooltip={t("agentConfig.timezoneTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            showSearch
            value={timezone}
            placeholder={t("agentConfig.selectTimezone")}
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            options={useTimezoneOptions()}
            onChange={onTimezoneChange}
            loading={savingTimezone}
            disabled={savingTimezone}
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.maxIters")}
          name="max_iters"
          rules={[
            { required: true, message: t("agentConfig.maxItersRequired") },
            { type: "number", min: 1, message: t("agentConfig.maxItersMin") },
          ]}
          tooltip={t("agentConfig.maxItersTooltip")}
          className={styles.reactAgentField}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            placeholder={t("agentConfig.maxItersPlaceholder")}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.shellCommandTimeout")}
          name="shell_command_timeout"
          rules={[
            {
              required: true,
              message: t("agentConfig.shellCommandTimeoutRequired"),
            },
            {
              type: "number",
              min: 1,
              message: t("agentConfig.shellCommandTimeoutMin"),
            },
          ]}
          tooltip={t("agentConfig.shellCommandTimeoutTooltip")}
          className={styles.reactAgentField}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={10}
            placeholder={t("agentConfig.shellCommandTimeoutPlaceholder")}
          />
        </Form.Item>
      </div>

      <Form.Item
        label={t("agentConfig.autoContinueOnTextOnly")}
        name="auto_continue_on_text_only"
        valuePropName="checked"
        tooltip={t("agentConfig.autoContinueOnTextOnlyTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoGenerateSessionTitle")}
        name={["auto_title_config", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.autoGenerateSessionTitleTooltip")}
      >
        <Switch />
      </Form.Item>

      <div className={styles.reactAgentRow}>
        <Form.Item
          label={t("agentConfig.contextManagerBackend")}
          name="context_manager_backend"
          tooltip={t("agentConfig.contextManagerBackendTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            options={CONTEXT_MANAGER_BACKEND_OPTIONS}
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.memoryManagerBackend")}
          name="memory_manager_backend"
          tooltip={t("agentConfig.memoryManagerBackendTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            options={MEMORY_MANAGER_BACKEND_OPTIONS}
            style={{ width: "100%" }}
          />
        </Form.Item>
      </div>
      <Alert
        type="warning"
        showIcon
        message={t("agentConfig.backendRestartWarning")}
        style={{ marginBottom: 16 }}
      />

      <Form.Item
        label={t("agentConfig.maxContextLength")}
        name="max_input_length"
        rules={[
          {
            required: true,
            message: t("agentConfig.maxContextLengthRequired"),
          },
          {
            type: "number",
            min: 1000,
            message: t("agentConfig.maxContextLengthMin"),
          },
        ]}
        tooltip={t("agentConfig.maxContextLengthTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1000}
          step={1024}
          placeholder={t("agentConfig.maxContextLengthPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.planMode", "Plan Mode")}
        tooltip={t(
          "agentConfig.planModeTooltip",
          "Enable plan mode to use /plan <description> for structured task planning",
        )}
      >
        <Switch
          checked={planEnabled}
          loading={planLoading}
          onChange={handlePlanToggle}
        />
      </Form.Item>
    </Card>
  );
}
