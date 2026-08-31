import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Select } from "@agentscope-ai/design";
import { SaveOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import { providerApi } from "@/api/modules/provider";
import type { ActiveModelsInfo, ProviderInfo } from "@/api/types";
import { useAppMessage } from "@/hooks/useAppMessage";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import {
  buildEligibleProviders,
  type EligibleProvider,
} from "../../../Chat/ModelSelector/modelSelectorModels";
import { AgentModelSettings } from "../../../Chat/ModelSelector/AgentModelSettings";
import styles from "../index.module.less";

interface ModelRoutingCardProps {
  agentId: string;
  onModelSaved?: () => void;
}

function modelList(provider: ProviderInfo | undefined) {
  return [...(provider?.models ?? []), ...(provider?.extra_models ?? [])];
}

export function ModelRoutingCard({
  agentId,
  onModelSaved,
}: ModelRoutingCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [selectedProviderId, setSelectedProviderId] = useState<string>();
  const [selectedModel, setSelectedModel] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligibleProviders = useMemo<EligibleProvider[]>(
    () => buildEligibleProviders(providers),
    [providers],
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [providerData, activeData] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels({ scope: "effective", agent_id: agentId }),
      ]);
      setProviders(providerData);
      setActiveModels(activeData);
      setSelectedProviderId(activeData.active_llm?.provider_id);
      setSelectedModel(activeData.active_llm?.model);
    } catch (err) {
      const text =
        err instanceof Error ? err.message : t("agentConfig.modelLoadFailed");
      setError(text);
    } finally {
      setLoading(false);
    }
  }, [agentId, t]);

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
  };

  const handleSave = async () => {
    if (!selectedProviderId || !selectedModel || saving) return;
    const provider = providers.find((item) => item.id === selectedProviderId);
    const model = modelList(provider).find((item) => item.id === selectedModel);
    if (provider && model) {
      const confirmed = await confirmFreeModelSwitch({ provider, model, t });
      if (!confirmed) return;
    }

    setSaving(true);
    try {
      const updated = await providerApi.setActiveLlm({
        provider_id: selectedProviderId,
        model: selectedModel,
        scope: "agent",
        agent_id: agentId,
      });
      setActiveModels(updated);
      message.success(t("agentConfig.modelSaved"));
      onModelSaved?.();
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("agentConfig.modelSaveFailed"),
      );
    } finally {
      setSaving(false);
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
            onChange={setSelectedModel}
          />
        </div>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          disabled={
            !selectedProviderId ||
            !selectedModel ||
            (activeModels?.active_llm?.provider_id === selectedProviderId &&
              activeModels?.active_llm?.model === selectedModel)
          }
          onClick={() => void handleSave()}
        >
          {t("common.save")}
        </Button>
      </div>
      <AgentModelSettings
        agentId={agentId}
        providers={eligibleProviders}
        activeProviderId={selectedProviderId}
        activeModelId={selectedModel}
      />
    </Card>
  );
}
