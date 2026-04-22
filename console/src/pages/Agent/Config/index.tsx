import { useState, useMemo, useEffect } from "react";
import { Button, Form, Tabs } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentConfig } from "./useAgentConfig.tsx";
import {
  ReactAgentCard,
  LlmRetryCard,
  LlmRateLimiterCard,
  ToolExecutionLevelCard,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
} from "@/constants/backendMappings";
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
  const contextBackend =
    Form.useWatch("context_manager_backend", form) || "light";
  const memoryBackend =
    Form.useWatch("memory_manager_backend", form) || "remelight";

  const dynamicTabs = useMemo(() => {
    const baseTabs = [
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
    ];

    const contextMapping = CONTEXT_MANAGER_BACKEND_MAPPINGS[contextBackend];
    if (contextMapping) {
      const ContextComponent = contextMapping.component;
      baseTabs.push({
        key: contextMapping.tabKey,
        label: (
          <span className={styles.tabLabel}>
            {t(`agentConfig.${contextMapping.tabKey}Title`)}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <ContextComponent maxInputLength={maxInputLength} />
          </div>
        ),
      });
    }

    const memoryMapping = MEMORY_MANAGER_BACKEND_MAPPINGS[memoryBackend];
    if (memoryMapping) {
      const MemoryComponent = memoryMapping.component;
      baseTabs.push({
        key: memoryMapping.tabKey,
        label: (
          <span className={styles.tabLabel}>
            {t(`agentConfig.${memoryMapping.tabKey}Title`)}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <MemoryComponent />
          </div>
        ),
      });
    }

    // Add Tool Execution Level tab
    baseTabs.push({
      key: "toolExecutionLevel",
      label: (
        <span className={styles.tabLabel}>
          {t("agentConfig.toolExecutionLevelTitle")}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          <ToolExecutionLevelCard />
        </div>
      ),
    });

    return baseTabs;
  }, [
    t,
    language,
    savingLang,
    timezone,
    savingTimezone,
    handleLanguageChange,
    handleTimezoneChange,
    llmRetryEnabled,
    maxInputLength,
    contextBackend,
    memoryBackend,
  ]);

  useEffect(() => {
    const tabKeys = dynamicTabs.map((t) => t.key);
    if (!tabKeys.includes(activeTab)) {
      setActiveTab(tabKeys[0] ?? "reactAgent");
    }
  }, [dynamicTabs, activeTab]);

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
            items={dynamicTabs}
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
