import { useEffect, useState } from "react";
import { Button, Card, message } from "@agentscope-ai/design";
import { Radio, Select, Space, Spin, Alert, Tag } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import styles from "./index.module.less";

interface TranscriptionProvider {
  id: string;
  name: string;
  available: boolean;
}

function VoiceTranscriptionPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [audioMode, setAudioMode] = useState("auto");
  const [providers, setProviders] = useState<TranscriptionProvider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [activeProviderId, setActiveProviderId] = useState("");

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const [modeRes, provRes] = await Promise.all([
        api.getAudioMode(),
        api.getTranscriptionProviders(),
      ]);
      setAudioMode(modeRes.audio_mode ?? "auto");
      setProviders(provRes.providers ?? []);
      setActiveProviderId(provRes.active_provider_id ?? "");
      // Find the configured provider (not auto-detected)
      // If active matches a provider but no explicit config, default to ""
      const configuredId =
        provRes.providers?.some(
          (p: TranscriptionProvider) =>
            p.id === provRes.active_provider_id && p.available,
        )
          ? provRes.active_provider_id
          : "";
      setSelectedProviderId(configuredId);
    } catch (err) {
      console.error("Failed to load settings:", err);
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
      await Promise.all([
        api.updateAudioMode(audioMode),
        api.updateTranscriptionProvider(selectedProviderId),
      ]);
      // Refresh to get updated active provider
      const provRes = await api.getTranscriptionProviders();
      setActiveProviderId(provRes.active_provider_id ?? "");
      message.success(t("voiceTranscription.saveSuccess"));
    } catch (err) {
      console.error("Failed to save settings:", err);
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

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>{t("voiceTranscription.title")}</h1>
          <p className={styles.description}>
            {t("voiceTranscription.description")}
          </p>
        </div>
      </div>

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
            <Radio value="transcribe">
              <span className={styles.optionLabel}>
                {t("voiceTranscription.modeTranscribe")}
              </span>
              <span className={styles.optionDescription}>
                {t("voiceTranscription.modeTranscribeDesc")}
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
      </Card>

      {showProviderSection && (
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
            <>
              <Select
                value={selectedProviderId}
                onChange={setSelectedProviderId}
                style={{ width: "100%", maxWidth: 400 }}
              >
                <Select.Option value="">
                  {t("voiceTranscription.providerAuto")}
                </Select.Option>
                {availableProviders.map((p) => (
                  <Select.Option key={p.id} value={p.id}>
                    {p.name}
                  </Select.Option>
                ))}
              </Select>
              {activeProviderId && (
                <div style={{ marginTop: 8 }}>
                  <span style={{ marginRight: 8, opacity: 0.65 }}>
                    {t("voiceTranscription.activeProvider")}
                  </span>
                  <Tag color="blue">
                    {providers.find((p) => p.id === activeProviderId)?.name ??
                      activeProviderId}
                  </Tag>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      <Alert
        type="info"
        showIcon
        message={t("voiceTranscription.transcriptionInfoTitle")}
        description={t("voiceTranscription.transcriptionInfoDesc")}
        style={{ marginBottom: 16 }}
      />

      <div className={styles.footerActions}>
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
