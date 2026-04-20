import { Button } from "@agentscope-ai/design";
import { Alert, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useVoiceTranscription } from "./useVoiceTranscription";
import {
  AudioModeCard,
  ProviderTypeCard,
  ProviderSelectCard,
} from "./components";
import styles from "./index.module.less";

function VoiceTranscriptionPage() {
  const { t } = useTranslation();
  const {
    loading,
    saving,
    audioMode,
    setAudioMode,
    providerType,
    setProviderType,
    selectedProviderId,
    setSelectedProviderId,
    localWhisperStatus,
    availableProviders,
    showProviderSection,
    isLocalWhisper,
    isWhisperApi,
    fetchSettings,
    handleSave,
  } = useVoiceTranscription();

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centerState}>
          <Spin />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.voiceTranscriptionPage}>
      <PageHeader
        items={[
          { title: t("nav.settings") },
          { title: t("voiceTranscription.title") },
        ]}
      />
      <Alert
        type="info"
        showIcon
        message={t("voiceTranscription.transcriptionInfoTitle")}
        description={
          isLocalWhisper
            ? t("voiceTranscription.transcriptionInfoDescLocal")
            : t("voiceTranscription.transcriptionInfoDesc")
        }
      />
      <div className={styles.content}>
        <AudioModeCard
          audioMode={audioMode}
          onAudioModeChange={setAudioMode}
          localWhisperStatus={localWhisperStatus}
        />

        {showProviderSection && (
          <>
            <ProviderTypeCard
              providerType={providerType}
              onProviderTypeChange={setProviderType}
              isLocalWhisper={isLocalWhisper}
              localWhisperStatus={localWhisperStatus}
            />

            {isWhisperApi && (
              <ProviderSelectCard
                availableProviders={availableProviders}
                selectedProviderId={selectedProviderId}
                onProviderChange={setSelectedProviderId}
              />
            )}
          </>
        )}
      </div>

      <div className={styles.footerButtons}>
        <Button
          onClick={fetchSettings}
          disabled={saving}
          style={{ marginRight: 8 }}
        >
          {t("common.reset")}
        </Button>
        <Button type="primary" onClick={handleSave} loading={saving}>
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default VoiceTranscriptionPage;
