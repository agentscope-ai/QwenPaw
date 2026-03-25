import { useEffect, useState } from "react";
import { Button, Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentConfig } from "./useAgentConfig.tsx";
import {
  PageHeader,
  ReactAgentCard,
  LlmRetryCard,
  ContextManagementCard,
  KnowledgeMaintenanceCard,
} from "./components";
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

  const [contextCompactThreshold, setContextCompactThreshold] = useState(0);
  const [contextCompactReserveThreshold, setContextCompactReserveThreshold] =
    useState(0);
  const llmRetryEnabled = Form.useWatch("llm_retry_enabled", form) ?? true;

  const updateCalculatedValues = (values: Record<string, unknown>) => {
    const maxInputLength = Number(values.max_input_length ?? 0);
    const memoryCompactRatio = Number(values.memory_compact_ratio ?? 0);
    const memoryReserveRatio = Number(values.memory_reserve_ratio ?? 0);
    setContextCompactThreshold(
      Math.floor(maxInputLength * memoryCompactRatio),
    );
    setContextCompactReserveThreshold(
      Math.floor(maxInputLength * memoryReserveRatio),
    );
  };

  const handleValuesChange = (_: unknown, allValues: Record<string, unknown>) => {
    updateCalculatedValues(allValues);
  };

  useEffect(() => {
    if (loading) return;
    const values = form.getFieldsValue([
      "max_input_length",
      "memory_compact_ratio",
      "memory_reserve_ratio",
    ]);
    updateCalculatedValues(values);
  }, [form, loading]);

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
      <PageHeader />

      {loading && (
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      )}

      <Form
        form={form}
        layout="vertical"
        className={styles.form}
        onValuesChange={handleValuesChange}
        style={{ display: loading ? "none" : undefined }}
      >
        <ReactAgentCard
          language={language}
          savingLang={savingLang}
          onLanguageChange={handleLanguageChange}
          timezone={timezone}
          savingTimezone={savingTimezone}
          onTimezoneChange={handleTimezoneChange}
        />

        <ContextManagementCard
          contextCompactThreshold={contextCompactThreshold}
          contextCompactReserveThreshold={contextCompactReserveThreshold}
        />

        <LlmRetryCard llmRetryEnabled={llmRetryEnabled} />
        <KnowledgeMaintenanceCard />
      </Form>

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
