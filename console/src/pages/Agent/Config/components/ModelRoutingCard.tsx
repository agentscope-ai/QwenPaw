import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Card, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

import { providerApi } from "@/api/modules/provider";
import type { AgentModelRoutingDraft, ProviderInfo } from "@/api/types";
import {
  buildEligibleProviders,
  type EligibleProvider,
} from "../../../Chat/ModelSelector/modelSelectorModels";
import { AgentModelSettings } from "../../../Chat/ModelSelector/AgentModelSettings";
import styles from "../index.module.less";

interface ModelRoutingCardProps {
  modelRouting: AgentModelRoutingDraft;
  onModelRoutingChange: (routing: AgentModelRoutingDraft) => void;
  draftResetToken: number;
}

function modelList(provider: ProviderInfo | undefined) {
  return [...(provider?.models ?? []), ...(provider?.extra_models ?? [])];
}

export function ModelRoutingCard({
  modelRouting,
  onModelRoutingChange,
  draftResetToken,
}: ModelRoutingCardProps) {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string>();
  const [selectedModel, setSelectedModel] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const modelRoutingRef = useRef(modelRouting);
  modelRoutingRef.current = modelRouting;

  const eligibleProviders = useMemo<EligibleProvider[]>(
    () => buildEligibleProviders(providers),
    [providers],
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const providerData = await providerApi.listProviders();
      setProviders(providerData);
    } catch (err) {
      const text =
        err instanceof Error ? err.message : t("agentConfig.modelLoadFailed");
      setError(text);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    setSelectedProviderId(modelRoutingRef.current.active_model?.provider_id);
    setSelectedModel(modelRoutingRef.current.active_model?.model);
  }, [draftResetToken]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const selectedProvider = providers.find(
    (provider) => provider.id === selectedProviderId,
  );
  const modelOptions = modelList(selectedProvider).map((model) => ({
    value: model.id,
    label: `${model.name || model.id} (${model.id})`,
  }));

  const handleProviderChange = (providerId: string) => {
    setSelectedProviderId(providerId);
    setSelectedModel(undefined);
    onModelRoutingChange({
      ...modelRouting,
      active_model: null,
    });
  };

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    if (selectedProviderId) {
      onModelRoutingChange({
        ...modelRouting,
        active_model: { provider_id: selectedProviderId, model },
      });
    }
  };

  if (loading) {
    return (
      <Card className={styles.formCard} title={t("agentConfig.modelTitle")}>
        {t("common.loading")}
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={styles.formCard} title={t("agentConfig.modelTitle")}>
        <div className={styles.modelError} role="alert">
          <span>{error}</span>
          <Button size="small" onClick={() => void fetchData()}>
            {t("environments.retry")}
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card className={styles.formCard} title={t("agentConfig.modelTitle")}>
      <p className={styles.modelDescription}>
        {t("agentConfig.modelDescription")}
      </p>
      <div className={styles.modelPrimaryRow}>
        <div className={styles.modelField}>
          <label htmlFor="agent-config-model-provider">
            {t("models.provider")}
          </label>
          <Select
            id="agent-config-model-provider"
            value={selectedProviderId}
            placeholder={t("models.selectProvider")}
            options={eligibleProviders.map((provider) => ({
              value: provider.id,
              label: provider.name,
            }))}
            onChange={handleProviderChange}
          />
        </div>
        <div className={styles.modelField}>
          <label htmlFor="agent-config-model">{t("models.model")}</label>
          <Select
            id="agent-config-model"
            value={selectedModel}
            placeholder={t("models.selectModel")}
            disabled={!selectedProviderId || modelOptions.length === 0}
            options={modelOptions}
            showSearch
            optionFilterProp="label"
            onChange={handleModelChange}
          />
        </div>
      </div>
      <AgentModelSettings
        providers={eligibleProviders}
        activeProviderId={selectedProviderId}
        activeModelId={selectedModel}
        initialConfig={modelRouting}
        draftResetToken={draftResetToken}
        onDraftChange={(settings) =>
          onModelRoutingChange({ ...modelRouting, ...settings })
        }
      />
    </Card>
  );
}
