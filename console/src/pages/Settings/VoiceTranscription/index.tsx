import InlineHelp from "@/components/InlineHelp";
import { useAutoSave } from "@/hooks/useAutoSave";
import { Spin } from "antd";
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
    handleSave,
  } = useVoiceTranscription();

  const { schedule } = useAutoSave(() => handleSave(true));

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
        extra={
          <InlineHelp>
            {t(
              isLocalWhisper
                ? "voiceTranscription.transcriptionInfoDescLocal"
                : "voiceTranscription.transcriptionInfoDesc",
            )}
          </InlineHelp>
        }
        items={[
          { title: t("nav.settings") },
          { title: t("voiceTranscription.title") },
        ]}
      />
      <div className={styles.content}>
        <AudioModeCard
          audioMode={audioMode}
          onAudioModeChange={(value) => {
            setAudioMode(value);
            schedule();
          }}
          localWhisperStatus={localWhisperStatus}
        />

        {showProviderSection && (
          <>
            <ProviderTypeCard
              providerType={providerType}
              onProviderTypeChange={(value) => {
                setProviderType(value);
                schedule();
              }}
              isLocalWhisper={isLocalWhisper}
              localWhisperStatus={localWhisperStatus}
            />

            {isWhisperApi && (
              <ProviderSelectCard
                availableProviders={availableProviders}
                selectedProviderId={selectedProviderId}
                onProviderChange={(value) => {
                  setSelectedProviderId(value);
                  schedule();
                }}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default VoiceTranscriptionPage;
