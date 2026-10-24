import type { ReactNode } from "react";
import { Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import type { BaseUrlOption } from "../../../../../api/types";
import { validateApiKey } from "../../apiKeyValidation";

interface ProviderConnectionFieldsProps {
  canEditBaseUrl: boolean;
  baseUrlOptions: BaseUrlOption[];
  baseUrlExtra?: ReactNode;
  baseUrlPlaceholder: string;
  apiKeyLabel: ReactNode;
  apiKeyPlaceholder: string;
  validApiKeyPrefixes: string[];
  authMode?: "api_key" | "auth_token";
  requireApiKey?: boolean;
}

export function ProviderConnectionFields({
  canEditBaseUrl,
  baseUrlOptions,
  baseUrlExtra,
  baseUrlPlaceholder,
  apiKeyLabel,
  apiKeyPlaceholder,
  validApiKeyPrefixes,
  authMode = "api_key",
  requireApiKey = false,
}: ProviderConnectionFieldsProps) {
  const { t } = useTranslation();
  const useBaseUrlSelect = canEditBaseUrl && baseUrlOptions.length > 0;
  return (
    <>
      {/* Base URL */}
      <Form.Item
        name="base_url"
        label={t("models.baseURL")}
        rules={
          canEditBaseUrl
            ? [
                ...(canEditBaseUrl
                  ? [
                      {
                        required: true,
                        message: t("models.pleaseEnterBaseURL"),
                      },
                    ]
                  : []),
                {
                  validator: (_: unknown, value: string) => {
                    if (!value || !value.trim()) return Promise.resolve();
                    try {
                      const url = new URL(value.trim());
                      if (!["http:", "https:"].includes(url.protocol)) {
                        return Promise.reject(
                          new Error(t("models.pleaseEnterValidURL")),
                        );
                      }
                      return Promise.resolve();
                    } catch {
                      return Promise.reject(
                        new Error(t("models.pleaseEnterValidURL")),
                      );
                    }
                  },
                },
              ]
            : []
        }
        extra={baseUrlExtra}
      >
        {useBaseUrlSelect ? (
          <Select
            options={baseUrlOptions.map((option) => ({
              label: `${option.label} — ${option.value}`,
              value: option.value,
            }))}
            placeholder={t("models.selectBaseURL")}
          />
        ) : (
          <Input placeholder={baseUrlPlaceholder} disabled={!canEditBaseUrl} />
        )}
      </Form.Item>

      {/* API Key */}
      <Form.Item
        name="api_key"
        label={apiKeyLabel}
        rules={[
          { required: requireApiKey, message: t("models.apiKey") },
          {
            validator: (_, value) => {
              const result = validateApiKey(
                value,
                validApiKeyPrefixes,
                authMode,
              );
              if (!result.valid) {
                return Promise.reject(
                  new Error(
                    t("models.apiKeyShouldStart", {
                      prefix: result.prefix,
                    }),
                  ),
                );
              }
              return Promise.resolve();
            },
          },
        ]}
      >
        <Input.Password placeholder={apiKeyPlaceholder} />
      </Form.Item>
    </>
  );
}
