import { Button, Card, Form, Select, Switch } from "@agentscope-ai/design";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "@/api";
import type { ModelSlotConfig, ProviderInfo } from "@/api/types";
import styles from "../index.module.less";

interface ProviderOption {
  value: string;
  label: string;
}

function modelOptionsForProvider(
  providers: ProviderInfo[],
  providerId?: string,
): ProviderOption[] {
  const provider = providers.find((item) => item.id === providerId);
  return provider ? allModelOptions(provider) : [];
}

function allModelOptions(provider: ProviderInfo): ProviderOption[] {
  return [...(provider.models ?? []), ...(provider.extra_models ?? [])].map(
    (model) => ({
      value: model.id,
      label: model.name || model.id,
    }),
  );
}

function hasAvailableModels(provider: ProviderInfo): boolean {
  return allModelOptions(provider).length > 0;
}

function isConfiguredProvider(provider: ProviderInfo): boolean {
  if (!hasAvailableModels(provider)) return false;
  if (provider.require_api_key === false) return Boolean(provider.base_url);
  if (provider.is_custom || provider.is_local)
    return Boolean(provider.base_url);
  if (provider.require_api_key ?? true) return Boolean(provider.api_key);
  return true;
}

export function LlmFallbackCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const fallbackEnabled = Form.useWatch("llm_fallback_enabled", form) ?? false;
  const watchedFallbackModels = Form.useWatch("llm_fallback_models", form) as
    | ModelSlotConfig[]
    | undefined;
  const fallbackModels = useMemo(
    () => watchedFallbackModels ?? [],
    [watchedFallbackModels],
  );
  const [providers, setProviders] = useState<ProviderInfo[]>([]);

  useEffect(() => {
    api
      .listProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, []);

  const providerOptions = useMemo(() => {
    const selectedProviderIds = new Set(
      (fallbackModels ?? [])
        .map((model) => model.provider_id)
        .filter((providerId): providerId is string => Boolean(providerId)),
    );
    return providers
      .filter(
        (provider) =>
          isConfiguredProvider(provider) ||
          selectedProviderIds.has(provider.id),
      )
      .map((provider) => ({
        value: provider.id,
        label: provider.name || provider.id,
      }));
  }, [fallbackModels, providers]);

  return (
    <Card className={styles.formCard} title={t("agentConfig.llmFallbackTitle")}>
      <Form.Item
        name="llm_fallback_enabled"
        label={t("agentConfig.llmFallbackEnabled")}
        valuePropName="checked"
        tooltip={t("agentConfig.llmFallbackEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.List name="llm_fallback_models">
        {(fields, { add, remove, move }) => (
          <div className={styles.llmFallbackList}>
            {fields.map((field, index) => {
              const providerId = fallbackModels?.[index]?.provider_id;
              return (
                <div className={styles.llmFallbackRow} key={field.key}>
                  <Form.Item
                    {...field}
                    name={[field.name, "provider_id"]}
                    label={t("agentConfig.llmFallbackProvider")}
                    rules={[
                      {
                        validator: async (_, value) => {
                          const model = fallbackModels?.[index]?.model;
                          if (fallbackEnabled && model && !value) {
                            throw new Error(
                              t("agentConfig.llmFallbackProviderRequired"),
                            );
                          }
                        },
                      },
                    ]}
                    className={styles.llmFallbackField}
                  >
                    <Select
                      disabled={!fallbackEnabled}
                      options={providerOptions}
                      placeholder={t(
                        "agentConfig.llmFallbackProviderPlaceholder",
                      )}
                      onChange={(value) => {
                        const next = [...(fallbackModels ?? [])];
                        next[index] = {
                          ...(next[index] ?? {}),
                          provider_id: value,
                          model: "",
                        };
                        form.setFieldValue("llm_fallback_models", next);
                      }}
                    />
                  </Form.Item>

                  <Form.Item
                    {...field}
                    name={[field.name, "model"]}
                    label={t("agentConfig.llmFallbackModel")}
                    rules={[
                      {
                        validator: async (_, value) => {
                          const provider = fallbackModels?.[index]?.provider_id;
                          if (fallbackEnabled && provider && !value) {
                            throw new Error(
                              t("agentConfig.llmFallbackModelRequired"),
                            );
                          }
                        },
                      },
                    ]}
                    className={styles.llmFallbackField}
                  >
                    <Select
                      disabled={!fallbackEnabled || !providerId}
                      options={modelOptionsForProvider(providers, providerId)}
                      placeholder={t("agentConfig.llmFallbackModelPlaceholder")}
                    />
                  </Form.Item>

                  <div className={styles.llmFallbackActions}>
                    <Button
                      disabled={!fallbackEnabled || index === 0}
                      onClick={() => move(index, index - 1)}
                    >
                      {t("agentConfig.llmFallbackMoveUp")}
                    </Button>
                    <Button
                      disabled={!fallbackEnabled || index === fields.length - 1}
                      onClick={() => move(index, index + 1)}
                    >
                      {t("agentConfig.llmFallbackMoveDown")}
                    </Button>
                    <Button
                      disabled={!fallbackEnabled}
                      onClick={() => remove(field.name)}
                    >
                      {t("common.delete")}
                    </Button>
                  </div>
                </div>
              );
            })}

            <Button
              disabled={!fallbackEnabled}
              onClick={() => add({ provider_id: "", model: "" })}
            >
              {t("agentConfig.llmFallbackAdd")}
            </Button>
          </div>
        )}
      </Form.List>
      <div className={styles.llmFallbackHint}>
        {t("agentConfig.llmFallbackReloadHint")}
      </div>
    </Card>
  );
}
