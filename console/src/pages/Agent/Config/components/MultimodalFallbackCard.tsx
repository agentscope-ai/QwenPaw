import { useEffect, useMemo, useState } from "react";
import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Collapse,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { ProviderInfo } from "../../../../api/types";
import { getIsConfigured } from "../../../Settings/Models/utils";
import styles from "../index.module.less";

export function MultimodalFallbackCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);

  const enabled =
    Form.useWatch(["multimodal_fallback", "enabled"], form) ?? false;

  useEffect(() => {
    setLoadingProviders(true);
    api
      .listProviders()
      .then(setProviders)
      .catch(() => setProviders([]))
      .finally(() => setLoadingProviders(false));
  }, []);

  const selectedProviderId = Form.useWatch(
    ["multimodal_fallback", "vision_provider"],
    form,
  );

  const visionProviders = useMemo(() => {
    return providers
      .filter((p) =>
        [...(p.models ?? []), ...(p.extra_models ?? [])].some(
          (m) => m.supports_image === true || m.supports_multimodal === true,
        ),
      )
      .map((p) => {
        // Vision models (e.g. qwen-vl-max) are usually paid and need an
        // API key. Disable providers without configured credentials so
        // the user cannot pick one that would fail at request time.
        const configured = getIsConfigured(p);
        return {
          label: configured
            ? p.name
            : `${p.name} ${t("agentConfig.multimodalFallbackProviderNoKey")}`,
          value: p.id,
          disabled: !configured,
        };
      });
  }, [providers, t]);

  const visionModels = useMemo(() => {
    const provider = providers.find((p) => p.id === selectedProviderId);
    if (!provider) return [];
    return [...(provider.models ?? []), ...(provider.extra_models ?? [])]
      .filter(
        (m) => m.supports_image === true || m.supports_multimodal === true,
      )
      .map((m) => ({ label: m.name, value: m.id }));
  }, [providers, selectedProviderId]);

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.multimodalFallbackTitle")}
    >
      <Form.Item
        name={["multimodal_fallback", "enabled"]}
        valuePropName="checked"
        label={t("agentConfig.multimodalFallbackEnabled")}
        tooltip={t("agentConfig.multimodalFallbackEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <div className={styles.reactAgentRow}>
        <Form.Item
          label={t("agentConfig.multimodalFallbackVisionProvider")}
          name={["multimodal_fallback", "vision_provider"]}
          rules={[
            {
              required: enabled,
              message: t(
                "agentConfig.multimodalFallbackVisionProviderRequired",
              ),
            },
          ]}
          tooltip={t("agentConfig.multimodalFallbackVisionProviderTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            style={{ width: "100%" }}
            loading={loadingProviders}
            disabled={!enabled || loadingProviders}
            placeholder={t(
              "agentConfig.multimodalFallbackVisionProviderPlaceholder",
            )}
            options={visionProviders}
            showSearch
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            onChange={() => {
              // Reset model when provider changes. Guard against a
              // null/undefined form value (before defaults populate) so
              // spreading does not drop the other fields.
              form.setFieldsValue({
                multimodal_fallback: {
                  ...(form.getFieldValue("multimodal_fallback") ?? {}),
                  vision_model: undefined,
                },
              });
            }}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.multimodalFallbackVisionModel")}
          name={["multimodal_fallback", "vision_model"]}
          dependencies={[["multimodal_fallback", "vision_provider"]]}
          rules={[
            {
              required: enabled,
              message: t("agentConfig.multimodalFallbackVisionModelRequired"),
            },
          ]}
          tooltip={t("agentConfig.multimodalFallbackVisionModelTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            style={{ width: "100%" }}
            disabled={!enabled || !selectedProviderId}
            loading={loadingProviders}
            placeholder={t(
              "agentConfig.multimodalFallbackVisionModelPlaceholder",
            )}
            options={visionModels}
            showSearch
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
          />
        </Form.Item>
      </div>

      <Collapse
        ghost
        items={[
          {
            key: "advanced",
            label: t("agentConfig.multimodalFallbackAdvanced"),
            children: (
              <div className={styles.reactAgentRow}>
                <Form.Item
                  label={t(
                    "agentConfig.multimodalFallbackMaxImageDescriptions",
                  )}
                  name={["multimodal_fallback", "max_image_descriptions"]}
                  rules={[
                    {
                      required: enabled,
                      message: t(
                        "agentConfig.multimodalFallbackMaxImageDescriptionsRequired",
                      ),
                    },
                    {
                      type: "number",
                      min: 1,
                      message: t(
                        "agentConfig.multimodalFallbackMaxImageDescriptionsMin",
                      ),
                    },
                  ]}
                  tooltip={t(
                    "agentConfig.multimodalFallbackMaxImageDescriptionsTooltip",
                  )}
                  className={styles.reactAgentField}
                >
                  <InputNumber
                    style={{ width: "100%" }}
                    min={1}
                    max={50}
                    step={1}
                    disabled={!enabled}
                    placeholder={t(
                      "agentConfig.multimodalFallbackMaxImageDescriptionsPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t(
                    "agentConfig.multimodalFallbackDescriptionMaxTokens",
                  )}
                  name={["multimodal_fallback", "description_max_tokens"]}
                  rules={[
                    {
                      required: enabled,
                      message: t(
                        "agentConfig.multimodalFallbackDescriptionMaxTokensRequired",
                      ),
                    },
                    {
                      type: "number",
                      min: 1,
                      message: t(
                        "agentConfig.multimodalFallbackDescriptionMaxTokensMin",
                      ),
                    },
                  ]}
                  tooltip={t(
                    "agentConfig.multimodalFallbackDescriptionMaxTokensTooltip",
                  )}
                  className={styles.reactAgentField}
                >
                  <InputNumber
                    style={{ width: "100%" }}
                    min={1}
                    max={4096}
                    step={1}
                    disabled={!enabled}
                    placeholder={t(
                      "agentConfig.multimodalFallbackDescriptionMaxTokensPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.multimodalFallbackSystemPrompt")}
                  name={["multimodal_fallback", "system_prompt"]}
                  tooltip={t(
                    "agentConfig.multimodalFallbackSystemPromptTooltip",
                  )}
                  className={styles.reactAgentField}
                >
                  <Input.TextArea
                    rows={3}
                    disabled={!enabled}
                    placeholder={t(
                      "agentConfig.multimodalFallbackSystemPromptPlaceholder",
                    )}
                  />
                </Form.Item>
              </div>
            ),
          },
        ]}
      />
    </Card>
  );
}
