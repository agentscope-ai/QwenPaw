import { Form, InputNumber, Select, Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { TIMEZONE_OPTIONS } from "../../../../constants/timezone";
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
  return (
    <Card className={styles.formCard} title={t("agentConfig.reactAgentTitle")}>
      <Form.Item
        label={t("agentConfig.language")}
        tooltip={t("agentConfig.languageTooltip")}
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
          options={TIMEZONE_OPTIONS}
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
          {
            type: "number",
            min: 1,
            message: t("agentConfig.maxItersMin"),
          },
        ]}
        tooltip={t("agentConfig.maxItersTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={1}
          placeholder={t("agentConfig.maxItersPlaceholder")}
        />
      </Form.Item>
    </Card>
  );
}
