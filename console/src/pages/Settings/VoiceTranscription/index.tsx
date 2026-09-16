import { Button } from "@agentscope-ai/design";
import { Alert, Spin, Input, Select, Result } from "antd";
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
    canManage,
    canSave,
    canTest,
    testing,
    testResult,
    model,
    setModel,
    localModel,
    setLocalModel,
    localModels,
    handleTest,
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

  if (!canManage) return <Result status="403" title="403" />;

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
        {showProviderSection && isWhisperApi && (
          <label>
            {t("voiceTranscription.remoteModel")}
            <Input
              aria-label={t("voiceTranscription.remoteModel")}
              data-testid="voice-remote-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </label>
        )}
        {showProviderSection && isLocalWhisper && (
          <label>
            {t("voiceTranscription.localModel")}
            <Select
              aria-label={t("voiceTranscription.localModel")}
              data-testid="voice-local-model"
              value={localModel}
              options={localModels.map((value) => ({ value, label: value }))}
              onChange={setLocalModel}
              style={{ minWidth: 160 }}
            />
          </label>
        )}
        <label>
          {t("voiceTranscription.testSaved")}
          <input
            type="file"
            accept="audio/*"
            aria-label={t("voiceTranscription.testSaved")}
            data-testid="voice-test-upload"
            disabled={!canTest}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void handleTest(file);
            }}
          />
        </label>
        <p>{t("voiceTranscription.testSavedHint")}</p>
        {testing && <Spin />}
        {testResult && (
          <output data-testid="voice-test-result">{testResult}</output>
        )}
      </div>

      <div className={styles.footerButtons}>
        <Button
          onClick={fetchSettings}
          disabled={saving || testing}
          style={{ marginRight: 8 }}
        >
          {t("common.reset")}
        </Button>
        <Button
          type="primary"
          onClick={handleSave}
          loading={saving}
          disabled={!canSave}
          data-testid="voice-save"
        >
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default VoiceTranscriptionPage;
