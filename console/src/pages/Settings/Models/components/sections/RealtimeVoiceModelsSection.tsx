import { useEffect, useMemo, useState } from "react";
import { Button, Select } from "@agentscope-ai/design";
import { SaveOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ActiveModelsInfo, ProviderInfo } from "../../../../../api/types";
import { providerApi } from "../../../../../api/modules/provider";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import styles from "../../index.module.less";

interface Props {
  providers: ProviderInfo[];
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
}

export function RealtimeVoiceModelsSection({
  providers,
  activeModels,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const current = activeModels?.active_realtime_voice;
  const [providerId, setProviderId] = useState(current?.provider_id);
  const [modelId, setModelId] = useState(current?.model);
  const [saving, setSaving] = useState(false);
  const eligible = useMemo(
    () =>
      providers.filter(
        (provider) =>
          provider.realtime_voice && provider.realtime_models.length > 0,
      ),
    [providers],
  );

  useEffect(() => {
    setProviderId(current?.provider_id);
    setModelId(current?.model);
  }, [current?.model, current?.provider_id]);

  const selectedProvider = eligible.find((item) => item.id === providerId);
  const save = async () => {
    if (!providerId || !modelId) return;
    setSaving(true);
    try {
      await providerApi.setActiveRealtimeVoice({
        provider_id: providerId,
        model: modelId,
        scope: "global",
      });
      message.success(t("realtimeVoice.saved"));
      onSaved();
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.defaultLlmBody}>
      <p className={styles.llmDescription}>
        {t("realtimeVoice.settingsInfoDescription")}
      </p>
      <div className={styles.slotForm}>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.provider")}</label>
          <Select
            value={providerId}
            options={eligible.map((provider) => ({
              value: provider.id,
              label: provider.name,
            }))}
            onChange={(next) => {
              setProviderId(next);
              setModelId(undefined);
            }}
          />
        </div>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("realtimeVoice.model")}</label>
          <Select
            value={modelId}
            disabled={!selectedProvider}
            options={(selectedProvider?.realtime_models || []).map((model) => ({
              value: model.id,
              label: `${model.name} (${model.id})`,
            }))}
            onChange={setModelId}
          />
        </div>
      </div>
      <div className={styles.slotActions}>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          disabled={!providerId || !modelId}
          onClick={() => void save()}
        >
          {t("models.save")}
        </Button>
      </div>
    </div>
  );
}
