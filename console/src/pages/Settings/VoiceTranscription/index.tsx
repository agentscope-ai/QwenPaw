import { useEffect, useState } from "react";
import { Button, Card, message } from "@agentscope-ai/design";
import { Radio, Select, Space, Spin, Alert } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

interface TranscriptionProvider {
  id: string;
  name: string;
  available: boolean;
}

interface LocalWhisperStatus {
  available: boolean;
  ffmpeg_installed: boolean;
  whisper_installed: boolean;
}

function VoiceTranscriptionPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [audioMode, setAudioMode] = useState("auto");
  const [providerType, setProviderType] = useState("disabled");
  const [providers, setProviders] = useState<TranscriptionProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [localWhisperStatus, setLocalWhisperStatus] =
    useState<LocalWhisperStatus | null>(null);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const [modeRes, provTypeRes, provRes, lwStatus] = await Promise.all([
        api.getAudioMode(),
        api.getTranscriptionProviderType(),
        api.getTranscriptionProviders(),
        api.getLocalWhisperStatus(),
      ]);
      setAudioMode(modeRes.audio_mode ?? "auto");
      setProviderType(provTypeRes.transcription_provider_type ?? "disabled");
      setProviders(provRes.providers ?? []);
      setSelectedProviderId(provRes.configured_provider_id ?? "");
      setLocalWhisperStatus(lwStatus);
    } catch (err) {
      console.error("Failed to load voice transcription settings:", err);
      message.error(t("voiceTranscription.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const promises: Promise<unknown>[] = [
        api.updateAudioMode(audioMode),
        api.updateTranscriptionProviderType(providerType),
      ];
      if (providerType === "whisper_api") {
        promises.push(api.updateTranscriptionProvider(selectedProviderId));
      }
      await Promise.all(promises);
      message.success(t("voiceTranscription.saveSuccess"));
    } catch (err) {
      console.error("Failed to save voice transcription settings:", err);
      message.error(t("voiceTranscription.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centerState}>
          <Spin />
        </div>
      </div>
    );
  }

  const availableProviders = providers.filter((p) => p.available);
  const showProviderSection = audioMode !== "native";
  const isLocalWhisper = providerType === "local_whisper";
  const isWhisperApi = providerType === "whisper_api";

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
        <Card className={styles.card}>
          <h3 className={styles.cardTitle}>
            {t("voiceTranscription.audioModeLabel")}
          </h3>
          <p className={styles.cardDescription}>
            {t("voiceTranscription.audioModeDescription")}
          </p>
          <Radio.Group
            value={audioMode}
            onChange={(e) => setAudioMode(e.target.value)}
          >
            <Space direction="vertical" size="middle">
              <Radio value="auto">
                <span className={styles.optionLabel}>
                  {t("voiceTranscription.modeAuto")}
                </span>
                <span className={styles.optionDescription}>
                  {t("voiceTranscription.modeAutoDesc")}
                </span>
              </Radio>
              <Radio value="native">
                <span className={styles.optionLabel}>
                  {t("voiceTranscription.modeNative")}
                </span>
                <span className={styles.optionDescription}>
                  {t("voiceTranscription.modeNativeDesc")}
                </span>
              </Radio>
            </Space>
          </Radio.Group>

          {audioMode === "native" && localWhisperStatus && (
            <div style={{ marginTop: 12 }}>
              {localWhisperStatus.ffmpeg_installed ? (
                <Alert
                  type="success"
                  showIcon
                  message={t("voiceTranscription.ffmpegReady")}
                />
              ) : (
                <Alert
                  type="warning"
                  showIcon
                  message={t("voiceTranscription.ffmpegMissing")}
                  description={t("voiceTranscription.ffmpegMissingDesc")}
                />
              )}
            </div>
          )}
        </Card>

        {showProviderSection && (
          <>
            <Card className={styles.card}>
              <h3 className={styles.cardTitle}>
                {t("voiceTranscription.providerTypeLabel")}
              </h3>
              <p className={styles.cardDescription}>
                {t("voiceTranscription.providerTypeDescription")}
              </p>
              <Radio.Group
                value={providerType}
                onChange={(e) => setProviderType(e.target.value)}
              >
                <Space direction="vertical" size="middle">
                  <Radio value="disabled">
                    <span className={styles.optionLabel}>
                      {t("voiceTranscription.providerTypeDisabled")}
                    </span>
                    <span className={styles.optionDescription}>
                      {t("voiceTranscription.providerTypeDisabledDesc")}
                    </span>
                  </Radio>
                  <Radio value="whisper_api">
                    <span className={styles.optionLabel}>
                      {t("voiceTranscription.providerTypeWhisperApi")}
                    </span>
                    <span className={styles.optionDescription}>
                      {t("voiceTranscription.providerTypeWhisperApiDesc")}
                    </span>
                  </Radio>
                  <Radio value="local_whisper">
                    <span className={styles.optionLabel}>
                      {t("voiceTranscription.providerTypeLocalWhisper")}
                    </span>
                    <span className={styles.optionDescription}>
                      {t("voiceTranscription.providerTypeLocalWhisperDesc")}
                    </span>
                  </Radio>
                </Space>
              </Radio.Group>

              {isLocalWhisper && localWhisperStatus && (
                <div style={{ marginTop: 12 }}>
                  {localWhisperStatus.available ? (
                    <Alert
                      type="success"
                      showIcon
                      message={t("voiceTranscription.localWhisperReady")}
                    />
                  ) : (
                    <Alert
                      type="warning"
                      showIcon
                      message={t("voiceTranscription.localWhisperMissing")}
                      description={t(
                        "voiceTranscription.localWhisperMissingDesc",
                        {
                          ffmpeg: localWhisperStatus.ffmpeg_installed
                            ? t("common.enabled")
                            : t("common.disabled"),
                          whisper: localWhisperStatus.whisper_installed
                            ? t("common.enabled")
                            : t("common.disabled"),
                        },
                      )}
                    />
                  )}
                </div>
              )}
            </Card>

            {isWhisperApi && (
              <Card className={styles.card}>
                <h3 className={styles.cardTitle}>
                  {t("voiceTranscription.providerLabel")}
                </h3>
                <p className={styles.cardDescription}>
                  {t("voiceTranscription.providerDescription")}
                </p>

                {availableProviders.length === 0 ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={t("voiceTranscription.noProvidersWarning")}
                  />
                ) : (
                  <Select
                    value={selectedProviderId || undefined}
                    onChange={setSelectedProviderId}
                    placeholder={t("voiceTranscription.providerPlaceholder")}
                    style={{ width: "100%", maxWidth: 400 }}
                  >
                    {availableProviders.map((p) => (
                      <Select.Option key={p.id} value={p.id}>
                        {p.name}
                      </Select.Option>
                    ))}
                  </Select>
                )}
              </Card>
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
