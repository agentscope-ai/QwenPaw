import { Card, Radio, Space, Alert } from "antd";
import { useTranslation } from "react-i18next";
import type { LocalWhisperStatus } from "../useVoiceTranscription";
import styles from "../index.module.less";

interface ProviderTypeCardProps {
  providerType: string;
  onProviderTypeChange: (value: string) => void;
  isLocalWhisper: boolean;
  localWhisperStatus: LocalWhisperStatus | null;
}

export function ProviderTypeCard({
  providerType,
  onProviderTypeChange,
  isLocalWhisper,
  localWhisperStatus,
}: ProviderTypeCardProps) {
  const { t } = useTranslation();

  return (
    <Card className={styles.card}>
      <h3 className={styles.cardTitle}>
        {t("voiceTranscription.providerTypeLabel")}
      </h3>
      <p className={styles.cardDescription}>
        {t("voiceTranscription.providerTypeDescription")}
      </p>
      <Radio.Group
        value={providerType}
        onChange={(e) => onProviderTypeChange(e.target.value)}
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
              description={t("voiceTranscription.localWhisperMissingDesc", {
                ffmpeg: localWhisperStatus.ffmpeg_installed
                  ? t("common.enabled")
                  : t("common.disabled"),
                whisper: localWhisperStatus.whisper_installed
                  ? t("common.enabled")
                  : t("common.disabled"),
              })}
            />
          )}
        </div>
      )}
    </Card>
  );
}
