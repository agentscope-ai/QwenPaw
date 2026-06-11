import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
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
          <Loader2 className="animate-spin" />
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
      <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark-mode:border-blue-800 dark-mode:bg-blue-950 dark-mode:text-blue-200">
        <span>ℹ</span>
        <div>
          <div className="font-medium">
            {t("voiceTranscription.transcriptionInfoTitle")}
          </div>
          <div className="mt-1">
            {isLocalWhisper
              ? t("voiceTranscription.transcriptionInfoDescLocal")
              : t("voiceTranscription.transcriptionInfoDesc")}
          </div>
        </div>
      </div>
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
          variant="outline"
          onClick={fetchSettings}
          disabled={saving}
          className="mr-2"
        >
          {t("common.reset")}
        </Button>
        <Button onClick={handleSave} disabled={saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default VoiceTranscriptionPage;
