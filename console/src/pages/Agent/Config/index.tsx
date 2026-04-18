import { useState } from "react";
import { Button, Form, Tabs } from "@agentscope-ai/design";
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
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

function AgentConfigPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("reactAgent");
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

      <div className={styles.content}>
        <Form form={form} layout="vertical" className={styles.form}>
          <Tabs
            className={styles.mainTabs}
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              {
                key: "reactAgent",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.reactAgentTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <ReactAgentCard
                      language={language}
                      savingLang={savingLang}
                      onLanguageChange={handleLanguageChange}
                      timezone={timezone}
                      savingTimezone={savingTimezone}
                      onTimezoneChange={handleTimezoneChange}
                    />
                  </div>
                ),
              },
              {
                key: "llmRetry",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.llmRetryTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <LlmRetryCard llmRetryEnabled={llmRetryEnabled} />
                  </div>
                ),
              },
              {
                key: "llmRateLimiter",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.llmRateLimiterTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <LlmRateLimiterCard />
                  </div>
                ),
              },
              {
                key: "contextCompact",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.contextCompactTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <ContextCompactCard maxInputLength={maxInputLength} />
                  </div>
                ),
              },
              {
                key: "toolResultCompact",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.toolResultCompactTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <ToolResultCompactCard />
                  </div>
                ),
              },
              {
                key: "memorySummary",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.memorySummaryTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <MemorySummaryCard />
                  </div>
                ),
              },
              {
                key: "embeddingConfig",
                label: (
                  <span className={styles.tabLabel}>
                    {t("agentConfig.embeddingConfigTitle")}
                  </span>
                ),
                children: (
                  <div className={styles.tabContent}>
                    <EmbeddingConfigCard />
                  </div>
                ),
              },
            ]}
          />
        </Form>
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
