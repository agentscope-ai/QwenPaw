import { Button, Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentConfig } from "./useAgentConfig.tsx";
import {
  ReactAgentCard,
  LlmRetryCard,
  LlmRateLimiterCard,
  ContextCompactCard,
  ToolResultCompactCard,
  MemorySummaryCard,
  EmbeddingConfigCard,
  ADBPGConfigCard,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

function AgentConfigPage() {
  const { t } = useTranslation();
  const {
    form,
    loading,
    saving,
    error,
    language,
    savingLang,
    timezone,
    savingTimezone,
    fetchConfig,
    handleSave,
    handleLanguageChange,
    handleTimezoneChange,
  } = useAgentConfig();

  const llmRetryEnabled = Form.useWatch("llm_retry_enabled", form) ?? true;
  const maxInputLength = Form.useWatch("max_input_length", form) ?? 0;

  if (loading) {
    return (
      <div className={styles.configPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.configPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchConfig} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.configPage}>
      <PageHeader parent={t("nav.agent")} current={t("agentConfig.title")} />
      <div className={styles.pageContent}>
        <div className={styles.formContainer}>
          <Form form={form} layout="vertical" className={styles.form}>
            <ReactAgentCard
              language={language}
              savingLang={savingLang}
              onLanguageChange={handleLanguageChange}
              timezone={timezone}
              savingTimezone={savingTimezone}
              onTimezoneChange={handleTimezoneChange}
            />

            <LlmRetryCard llmRetryEnabled={llmRetryEnabled} />

            <LlmRateLimiterCard />

            <ContextCompactCard maxInputLength={maxInputLength} />

            <ToolResultCompactCard />

            <MemorySummaryCard />

            <EmbeddingConfigCard />

            <ADBPGConfigCard />
          </Form>
        </div>
      </div>

      <div className={styles.footerActions}>
        <Button
          onClick={fetchConfig}
          disabled={saving}
          style={{ marginRight: 8 }}
        >
          {t("common.reset")}
        </Button>
        <Button type="primary" onClick={handleSave} loading={saving}>
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default AgentConfigPage;
