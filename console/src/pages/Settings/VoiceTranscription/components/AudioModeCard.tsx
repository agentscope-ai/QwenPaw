import { Card, Radio, Space, Alert } from "antd";
import { useTranslation } from "react-i18next";
import type { LocalWhisperStatus } from "../useVoiceTranscription";
import styles from "../index.module.less";

interface AudioModeCardProps {
  audioMode: string;
  onAudioModeChange: (value: string) => void;
  localWhisperStatus: LocalWhisperStatus | null;
}

export function AudioModeCard({
  audioMode,
  onAudioModeChange,
  localWhisperStatus,
}: AudioModeCardProps) {
  const { t } = useTranslation();

  return (
    <Card className={styles.card}>
      <h3 className={styles.cardTitle}>
        {t("voiceTranscription.audioModeLabel")}
      </h3>
      <p className={styles.cardDescription}>
        {t("voiceTranscription.audioModeDescription")}
      </p>
      <Radio.Group
        value={audioMode}
        onChange={(e) => onAudioModeChange(e.target.value)}
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
  );
}
