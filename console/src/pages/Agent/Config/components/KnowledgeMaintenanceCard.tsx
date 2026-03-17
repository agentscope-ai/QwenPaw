import { Card, Form, InputNumber, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function KnowledgeMaintenanceCard() {
  const { t } = useTranslation();
  const knowledgeEnabled = Form.useWatch("knowledge_enabled");
  const autoCollectLongText = Form.useWatch("knowledge_auto_collect_long_text");

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.knowledgeMaintenanceTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.knowledgeEnabled")}
        name="knowledge_enabled"
        valuePropName="checked"
        tooltip={t("agentConfig.knowledgeEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoCollectChatFiles")}
        name="knowledge_auto_collect_chat_files"
        valuePropName="checked"
        tooltip={t("agentConfig.autoCollectChatFilesTooltip")}
      >
        <Switch disabled={!knowledgeEnabled} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoCollectChatUrls")}
        name="knowledge_auto_collect_chat_urls"
        valuePropName="checked"
        tooltip={t("agentConfig.autoCollectChatUrlsTooltip")}
      >
        <Switch disabled={!knowledgeEnabled} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoCollectLongText")}
        name="knowledge_auto_collect_long_text"
        valuePropName="checked"
        tooltip={t("agentConfig.autoCollectLongTextTooltip")}
      >
        <Switch disabled={!knowledgeEnabled} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.longTextMinChars")}
        name="knowledge_long_text_min_chars"
        rules={[
          {
            required: true,
            message: t("agentConfig.longTextMinCharsRequired"),
          },
          {
            type: "number",
            min: 200,
            message: t("agentConfig.longTextMinCharsMin"),
          },
        ]}
        tooltip={t("agentConfig.longTextMinCharsTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={200}
          max={20000}
          step={100}
          disabled={!knowledgeEnabled || !autoCollectLongText}
          placeholder={t("agentConfig.longTextMinCharsPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.knowledgeChunkSize")}
        name="knowledge_chunk_size"
        rules={[
          {
            required: true,
            message: t("agentConfig.knowledgeChunkSizeRequired"),
          },
          {
            type: "number",
            min: 200,
            message: t("agentConfig.knowledgeChunkSizeMin"),
          },
        ]}
        tooltip={t("agentConfig.knowledgeChunkSizeTooltip")}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={200}
          max={8000}
          step={100}
          disabled={!knowledgeEnabled}
          placeholder={t("agentConfig.knowledgeChunkSizePlaceholder")}
        />
      </Form.Item>

    </Card>
  );
}
