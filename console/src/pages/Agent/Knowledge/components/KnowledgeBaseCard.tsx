import { useEffect, useState } from "react";
import { Button, Card, Form, Input, InputNumber, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { KnowledgeBaseSummary } from "../../../../api/types";

export function KnowledgeBaseCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [options, setOptions] = useState<KnowledgeBaseSummary[]>([]);
  const items = Form.useWatch("knowledge_base_config", form) || [];

  useEffect(() => {
    const run = async () => {
      try {
        const response = await api.listKnowledgeBases();
        setOptions(response.items);
      } catch {
        setOptions([]);
      }
    };
    run();
  }, []);

  return (
    <Card title={t("agentConfig.knowledgeBaseTitle")}>
      <div style={{ marginBottom: 16, color: "rgba(20,20,19,0.65)" }}>
        {t("agentConfig.knowledgeBaseDescription")}
      </div>

      <Form.List name="knowledge_base_config">
        {(fields, { add, remove }) => (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {fields.map((field, index) => (
              <Card
                key={field.key}
                size="small"
                title={t("agentConfig.knowledgeBaseItemTitle", { index: index + 1 })}
                extra={
                  <Button danger size="small" onClick={() => remove(field.name)}>
                    {t("common.delete")}
                  </Button>
                }
              >
                <Form.Item
                  label={t("agentConfig.knowledgeBaseSelect")}
                  name={[field.name, "id"]}
                  rules={[{ required: true, message: t("agentConfig.knowledgeBaseSelectRequired") }]}
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    options={options.map((item) => ({
                      label: `${item.name} (${item.id})`,
                      value: item.id,
                    }))}
                  />
                </Form.Item>
                <Form.Item label={t("agentConfig.knowledgeBasePriority")} name={[field.name, "priority"]}>
                  <InputNumber min={1} max={99} style={{ width: "100%" }} />
                </Form.Item>
                <Form.Item label={t("agentConfig.knowledgeBaseTrigger")} name={[field.name, "trigger"]}>
                  <Select
                    options={[
                      { label: t("agentConfig.knowledgeBaseTriggerAlways"), value: "always" },
                      { label: t("agentConfig.knowledgeBaseTriggerKeyword"), value: "keyword" },
                    ]}
                  />
                </Form.Item>
                <Form.Item label={t("agentConfig.knowledgeBaseTopK")} name={[field.name, "retrieval_top_k"]}>
                  <InputNumber min={1} max={20} style={{ width: "100%" }} />
                </Form.Item>
                <Form.Item label={t("agentConfig.knowledgeBaseUsageRule")} name={[field.name, "usage_rule"]}>
                  <Input.TextArea rows={3} />
                </Form.Item>
                <Form.Item label={t("agentConfig.knowledgeBaseKeywords")}>
                  <Input
                    value={(items[index]?.keywords || []).join(", ")}
                    placeholder={t("agentConfig.knowledgeBaseKeywordsPlaceholder")}
                    onChange={(event) => {
                      const nextItems = [...items];
                      nextItems[index] = {
                        ...nextItems[index],
                        keywords: event.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      };
                      form.setFieldsValue({ knowledge_base_config: nextItems });
                    }}
                  />
                </Form.Item>
              </Card>
            ))}

            <Button
              onClick={() =>
                add({
                  priority: fields.length + 1,
                  trigger: "always",
                  retrieval_top_k: 3,
                  usage_rule: "",
                  keywords: [],
                })
              }
            >
              {t("agentConfig.knowledgeBaseAdd")}
            </Button>
          </div>
        )}
      </Form.List>
    </Card>
  );
}