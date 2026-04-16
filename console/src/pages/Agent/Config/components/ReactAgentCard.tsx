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
import styles from "../index.module.less";

const LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];

const MEMORY_MANAGER_BACKEND_OPTIONS = [
  { value: "remelight", label: "ReMeLight" },
  // Additional backends can be registered via plugins.
  // The dropdown will be dynamically populated from the API in the future.
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
        label={t("agentConfig.memoryManagerBackend")}
        name="memory_manager_backend"
        tooltip={t("agentConfig.memoryManagerBackendTooltip")}
      >
        <Select
          options={MEMORY_MANAGER_BACKEND_OPTIONS}
          style={{ width: "100%" }}
        />
      </Form.Item>
      <Alert
        type="warning"
        showIcon
        message={t("agentConfig.memoryManagerBackendRestartWarning")}
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
    </Card>
  );
}
