import { useState, useEffect, useMemo } from "react";
import {
  Form,
  Select,
  Card,
  Button,
  InputNumber,
  Checkbox,
} from "@agentscope-ai/design";
import { Space, Typography } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ProviderInfo, ModelInfo } from "../../../../api/types";
import styles from "../index.module.less";

const { Text } = Typography;

interface ModelFallbackCardProps {
  providers: ProviderInfo[];
}

export function ModelFallbackCard({ providers }: ModelFallbackCardProps) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [selectedProviders, setSelectedProviders] = useState<
    Record<number, string>
  >({});

  // Initialize selectedProviders from existing form values
  useEffect(() => {
    const fallbacks =
      form.getFieldValue(["fallback_config", "fallbacks"]) || [];
    const initialProviders: Record<number, string> = {};
    fallbacks.forEach((fb: { provider_id?: string }, index: number) => {
      if (fb.provider_id) {
        initialProviders[index] = fb.provider_id;
      }
    });
    setSelectedProviders(initialProviders);
  }, [form]);

  // Get available models for a provider
  const getModelsForProvider = (providerId: string): ModelInfo[] => {
    const provider = providers.find((p) => p.id === providerId);
    if (!provider) return [];
    return [...provider.models, ...provider.extra_models];
  };

  // Build provider options
  const providerOptions = useMemo(
    () =>
      providers.map((p) => ({
        value: p.id,
        label: p.name,
      })),
    [providers],
  );

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.modelFallbackTitle")}
      style={{ marginTop: 16 }}
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        {t("agentConfig.modelFallbackDescription")}
      </Text>

      <Form.List name={["fallback_config", "fallbacks"]}>
        {(fields, { add, remove }) => (
          <>
            {fields.map(({ key, name, ...restField }) => {
              const providerId = selectedProviders[name];
              const modelOptions = providerId
                ? getModelsForProvider(providerId).map((m) => ({
                    value: m.id,
                    label: m.name,
                  }))
                : [];

              return (
                <Space
                  key={key}
                  style={{ display: "flex", marginBottom: 8 }}
                  align="baseline"
                >
                  <Form.Item
                    {...restField}
                    name={[name, "provider_id"]}
                    rules={[
                      {
                        required: true,
                        message: t("agentConfig.fallbackProviderRequired"),
                      },
                    ]}
                    style={{ marginBottom: 0 }}
                  >
                    <Select
                      placeholder={t("agentConfig.fallbackProvider")}
                      options={providerOptions}
                      style={{ width: 180 }}
                      onChange={(value) => {
                        setSelectedProviders((prev) => ({
                          ...prev,
                          [name]: value as string,
                        }));
                        // Reset model when provider changes
                        form.setFieldValue(
                          ["fallback_config", "fallbacks", name, "model"],
                          undefined,
                        );
                      }}
                    />
                  </Form.Item>

                  <Form.Item
                    {...restField}
                    name={[name, "model"]}
                    rules={[
                      {
                        required: true,
                        message: t("agentConfig.fallbackModelRequired"),
                      },
                    ]}
                    style={{ marginBottom: 0 }}
                  >
                    <Select
                      placeholder={t("agentConfig.fallbackModel")}
                      options={modelOptions}
                      style={{ width: 180 }}
                      disabled={!providerId}
                    />
                  </Form.Item>

                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => {
                      remove(name);
                      setSelectedProviders((prev) => {
                        const newState = { ...prev };
                        delete newState[name];
                        return newState;
                      });
                    }}
                  />
                </Space>
              );
            })}

            <Form.Item>
              <Button
                type="dashed"
                onClick={() => add()}
                icon={<PlusOutlined />}
                disabled={fields.length >= 10}
              >
                {t("agentConfig.addFallback")}
              </Button>
            </Form.Item>
          </>
        )}
      </Form.List>

      <Form.Item
        name={["fallback_config", "cooldown_enabled"]}
        valuePropName="checked"
      >
        <Checkbox>{t("agentConfig.cooldownEnabled")}</Checkbox>
      </Form.Item>

      <Form.Item
        label={t("agentConfig.maxFallbacks")}
        name={["fallback_config", "max_fallbacks"]}
        rules={[
          { required: true, message: t("agentConfig.maxFallbacksRequired") },
        ]}
      >
        <InputNumber min={1} max={10} style={{ width: 120 }} />
      </Form.Item>
    </Card>
  );
}
