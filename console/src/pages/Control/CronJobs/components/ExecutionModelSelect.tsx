import { useEffect, useState } from "react";
import { Alert, Select } from "antd";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../../api/modules/provider";
import {
  buildEligibleProviders,
  type EligibleProvider,
} from "../../../Chat/ModelSelector/modelSelectorModels";

interface ModelSlot {
  provider_id: string;
  model: string;
}
interface Props {
  value?: ModelSlot | string | null;
  onChange?: (value: ModelSlot | null) => void;
  id?: string;
}

export function ExecutionModelSelect({ value, onChange, id }: Props) {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<EligibleProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    providerApi
      .listProviders()
      .then((providers) => {
        if (!active) return;
        setProviders(
          buildEligibleProviders(providers).filter(
            (provider) => provider.models.length > 0,
          ),
        );
      })
      .catch(() => {
        if (active) setFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  const slot =
    typeof value === "string"
      ? {
          provider_id: value.split(":", 1)[0],
          model: value.slice(value.indexOf(":") + 1),
        }
      : value;
  const providerId = slot?.provider_id || "";
  const modelId = slot?.model || "";
  const selectedProvider = providers.find(
    (provider) => provider.id === providerId,
  );
  const providerOptions = [
    { value: "", label: t("cronJobs.executionModelDefault") },
    ...providers.map((provider) => ({
      value: provider.id,
      label: provider.name,
    })),
  ];
  if (providerId && !selectedProvider) {
    providerOptions.push({ value: providerId, label: providerId });
  }
  const modelOptions = [
    ...new Map(
      (selectedProvider?.models || []).map((model) => [
        model.id,
        {
          value: model.id,
          label:
            model.name && model.name !== model.id
              ? `${model.name} (${model.id})`
              : model.id,
        },
      ]),
    ).values(),
  ];
  if (modelId && !modelOptions.some((model) => model.value === modelId)) {
    modelOptions.push({ value: modelId, label: modelId });
  }
  if (!providerId) {
    modelOptions.push({
      value: "",
      label: t("cronJobs.executionModelDefault"),
    });
  }
  return (
    <>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <div>
          <label
            htmlFor={id}
            style={{
              display: "block",
              marginBottom: 8,
              color: "var(--ant-color-text-secondary, #888)",
            }}
          >
            {t("models.provider")}
          </label>
          <Select
            id={id}
            aria-label={t("models.provider")}
            style={{ width: "100%" }}
            value={providerId}
            loading={loading}
            showSearch
            optionFilterProp="label"
            options={providerOptions}
            onChange={(key: string) => {
              if (!key) {
                onChange?.(null);
                return;
              }
              const firstModel = providers.find(
                (provider) => provider.id === key,
              )?.models[0];
              if (firstModel)
                onChange?.({ provider_id: key, model: firstModel.id });
            }}
          />
        </div>
        <div>
          <label
            htmlFor={id ? `${id}_model` : undefined}
            style={{
              display: "block",
              marginBottom: 8,
              color: "var(--ant-color-text-secondary, #888)",
            }}
          >
            {t("models.model")}
          </label>
          <Select
            id={id ? `${id}_model` : undefined}
            aria-label={t("models.model")}
            style={{ width: "100%" }}
            value={modelId}
            disabled={!providerId}
            loading={loading}
            showSearch
            optionFilterProp="label"
            options={modelOptions}
            onChange={(model: string) =>
              onChange?.({ provider_id: providerId, model })
            }
          />
        </div>
      </div>
      {failed && (
        <Alert type="error" message={t("cronJobs.executionModelsLoadFailed")} />
      )}
    </>
  );
}
