import React, { useState, useEffect, useMemo } from "react";
import { SaveOutlined } from "@ant-design/icons";
import { Select, Button } from "@agentscope-ai/design";
import { agentsApi } from "../../../../../api";
import type { ModelInfo, ProviderInfo } from "../../../../../api/types";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { useAgentStore } from "../../../../../stores/agentStore";
import { getIsConfigured } from "../../utils";
import styles from "../../index.module.less";

interface VisualModelSectionProps {
  providers: ProviderInfo[];
  onSaved: () => void;
}

function isMultimodalModel(m: ModelInfo): boolean {
  return !!(m.supports_image || m.supports_video || m.supports_multimodal);
}

export const VisualModelSection = React.memo(function VisualModelSection({
  providers,
  onSaved,
}: VisualModelSectionProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const [saving, setSaving] = useState(false);
  const [providerId, setProviderId] = useState<string>();
  const [modelId, setModelId] = useState<string>();
  const [dirty, setDirty] = useState(false);
  const [agentDisplayName, setAgentDisplayName] = useState(selectedAgent);

  const eligible = useMemo(
    () =>
      providers.filter(
        (p) =>
          getIsConfigured(p) &&
          p.models.length + p.extra_models.length > 0 &&
          [...p.models, ...p.extra_models].some(isMultimodalModel),
      ),
    [providers],
  );

  useEffect(() => {
    let cancelled = false;
    setAgentDisplayName(selectedAgent);
    agentsApi.getAgent(selectedAgent).then((config) => {
      if (cancelled) return;
      setAgentDisplayName(config.name || selectedAgent);
      setProviderId(config.visual_model?.provider_id || undefined);
      setModelId(config.visual_model?.model || undefined);
      setDirty(false);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  const chosenProvider = providers.find((p) => p.id === providerId);
  const modelOptions = chosenProvider
    ? [...chosenProvider.models, ...chosenProvider.extra_models].filter(
        isMultimodalModel,
      )
    : [];

  const handleSave = async () => {
    setSaving(true);
    try {
      await agentsApi.updateAgent(selectedAgent, {
        id: selectedAgent,
        name: agentDisplayName,
        visual_model:
          providerId && modelId
            ? { provider_id: providerId, model: modelId }
            : null,
      });
      message.success(t("models.visualModelUpdated"));
      setDirty(false);
      onSaved();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("models.failedToSave"),
      );
    } finally {
      setSaving(false);
    }
  };

  const canSave =
    dirty && ((providerId && modelId) || (!providerId && !modelId));

  return (
    <div className={styles.defaultLlmBody}>
      <p className={styles.slotDescription}>
        {t("models.visualModelDescription", {
          agentName: agentDisplayName,
        })}
      </p>
      <p className={styles.slotDescription}>
        {t("models.visualModelBillingHint")}
      </p>
      <div className={styles.slotForm}>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.provider")}</label>
          <Select
            style={{ width: "100%" }}
            allowClear
            placeholder={t("models.selectProvider")}
            value={providerId}
            onChange={(pid?: string) => {
              setProviderId(pid);
              setModelId(undefined);
              setDirty(true);
            }}
            options={eligible.map((p) => ({ value: p.id, label: p.name }))}
          />
        </div>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.model")}</label>
          <Select
            style={{ width: "100%" }}
            allowClear
            placeholder={t("models.selectModel")}
            disabled={!providerId || !modelOptions.length}
            showSearch
            optionFilterProp="label"
            value={modelId}
            onChange={(mid?: string) => {
              setModelId(mid);
              setDirty(true);
            }}
            options={modelOptions.map((m) => ({
              value: m.id,
              label: `${m.name} (${m.id})`,
            }))}
          />
        </div>
        <div className={[styles.slotField, styles.slotActionField].join(" ")}>
          <label
            className={[styles.slotLabel, styles.visuallyHiddenLabel].join(" ")}
          >
            {t("models.actions")}
          </label>
          <Button
            type="primary"
            loading={saving}
            disabled={!canSave}
            onClick={handleSave}
            block
            icon={<SaveOutlined />}
          >
            {dirty ? t("models.save") : t("models.saved")}
          </Button>
        </div>
      </div>
    </div>
  );
});
