import { useState } from "react";
import { Form, Select, Button, Card, Input } from "@agentscope-ai/design";
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
    hasFivemanageApiKey,
    fetchConfig,
    handleSave,
    handleLanguageChange,
  } = useAgentConfig();

  const handleReset = () => fetchConfig();

  // Calculate derived values from form
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
      contextCompactReserveThreshold: Math.floor(
        maxInputLength * memoryReserveRatio,
      ),
      contextCompactThreshold: Math.floor(maxInputLength * memoryCompactRatio),
    };
  };

  // Force re-render when form values change
  const [, forceUpdate] = useState({});

  const handleValuesChange = () => {
    forceUpdate({});
  };

  const { contextCompactReserveThreshold, contextCompactThreshold } =
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

        <Card
          className={styles.formCard}
          title={t("agentConfig.imageUploadConfigTitle")}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label={t("agentConfig.imageUploadProvider")}
            name="image_upload_provider"
            tooltip={t("agentConfig.imageUploadProviderTooltip")}
          >
            <Select style={{ width: "100%" }}>
              <Select.Option value="none">
                {t("agentConfig.imageUploadProviderNone")}
              </Select.Option>
              <Select.Option value="fivemanage">
                {t("agentConfig.imageUploadProviderFivemanage")}
              </Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) =>
              prevValues.image_upload_provider !==
              currentValues.image_upload_provider
            }
          >
            {({ getFieldValue }) =>
              getFieldValue("image_upload_provider") === "fivemanage" ? (
                <Form.Item
                  label={t("agentConfig.fivemanageApiKey")}
                  name="fivemanage_api_key"
                  rules={[
                    {
                      validator: (_, value) => {
                        const hasNewValue =
                          typeof value === "string" && value.trim().length > 0;
                        if (hasNewValue || hasFivemanageApiKey) {
                          return Promise.resolve();
                        }
                        return Promise.reject(
                          new Error(t("agentConfig.fivemanageApiKeyRequired")),
                        );
                      },
                    },
                  ]}
                  tooltip={
                    <span>
                      {t("agentConfig.fivemanageApiKeyTooltip")}{" "}
                      <a
                        href="https://docs.fivemanage.com/api-reference/introduction"
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: "#1890ff" }}
                      >
                        {t("agentConfig.officialDocs")}
                      </a>
                    </span>
                  }
                >
                  <Input.Password
                    placeholder={
                      hasFivemanageApiKey
                        ? t("agentConfig.fivemanageApiKeyMaskedPlaceholder")
                        : t("agentConfig.fivemanageApiKeyPlaceholder")
                    }
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Card>

        <Form.Item className={styles.buttonGroup}>
          <Button
            onClick={handleReset}
            disabled={saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button type="primary" onClick={handleSave} loading={saving}>
            {t("common.save")}
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
}

export default AgentConfigPage;
