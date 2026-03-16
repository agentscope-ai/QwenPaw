import { Card, Form, InputNumber, Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function KnowledgeMaintenanceCard() {
  const { t } = useTranslation();
  const autoCollectLongText = Form.useWatch("auto_collect_long_text");

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.knowledgeMaintenanceTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.autoCollectChatFiles")}
        name="auto_collect_chat_files"
        valuePropName="checked"
        tooltip={t("agentConfig.autoCollectChatFilesTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoCollectChatUrls")}
        name="auto_collect_chat_urls"
        valuePropName="checked"
        tooltip={t("agentConfig.autoCollectChatUrlsTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.autoCollectLongText")}
        name="auto_collect_long_text"
        valuePropName="checked"
        tooltip={t("agentConfig.autoCollectLongTextTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.longTextMinChars")}
        name="long_text_min_chars"
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
          disabled={!autoCollectLongText}
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
          placeholder={t("agentConfig.knowledgeChunkSizePlaceholder")}
        />
      </Form.Item>

    </Card>
  );
}
