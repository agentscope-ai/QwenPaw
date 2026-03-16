import { Form, InputNumber, Select, Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
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
}

export function ReactAgentCard({
  language,
  savingLang,
  onLanguageChange,
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
