import { useState } from "react";
import { Button, Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentConfig } from "./useAgentConfig.tsx";
import {
  PageHeader,
  ReactAgentCard,
  ContextManagementCard,
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
    fetchConfig,
    handleSave,
    handleLanguageChange,
  } = useAgentConfig();

  // Force re-render when form values change to refresh derived threshold values
  const [, forceUpdate] = useState({});
  const handleValuesChange = () => forceUpdate({});

  const getCalculatedValues = () => {
    const values = form.getFieldsValue([
      "max_input_length",
      "memory_compact_ratio",
      "memory_reserve_ratio",
    ]);
    const maxInputLength = values.max_input_length ?? 0;
    const memoryCompactRatio = values.memory_compact_ratio ?? 0;
    const memoryReserveRatio = values.memory_reserve_ratio ?? 0;
    return {
      contextCompactThreshold: Math.floor(maxInputLength * memoryCompactRatio),
      contextCompactReserveThreshold: Math.floor(
        maxInputLength * memoryReserveRatio,
      ),
    };
  };

  const { contextCompactThreshold, contextCompactReserveThreshold } =
    getCalculatedValues();

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
      <PageHeader />

      <Form
        form={form}
        layout="vertical"
        className={styles.form}
        onValuesChange={handleValuesChange}
      >
        <ReactAgentCard
          language={language}
          savingLang={savingLang}
          onLanguageChange={handleLanguageChange}
        />

        <ContextManagementCard
          contextCompactThreshold={contextCompactThreshold}
          contextCompactReserveThreshold={contextCompactReserveThreshold}
        />
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
