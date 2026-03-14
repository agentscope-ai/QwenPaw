import { useEffect, useState } from "react";
import { Button, Card, message } from "@agentscope-ai/design";
import { Radio, Space, Spin } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import styles from "./index.module.less";

function VoiceTranscriptionPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [audioMode, setAudioMode] = useState("auto");

  const fetchAudioMode = async () => {
    setLoading(true);
    try {
      const res = await api.getAudioMode();
      setAudioMode(res.audio_mode ?? "auto");
    } catch (err) {
      console.error("Failed to load audio mode:", err);
      message.error(t("voiceTranscription.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAudioMode();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateAudioMode(audioMode);
      message.success(t("voiceTranscription.saveSuccess"));
    } catch (err) {
      console.error("Failed to save audio mode:", err);
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

      <div className={styles.footerActions}>
        <Button
          onClick={fetchAudioMode}
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
