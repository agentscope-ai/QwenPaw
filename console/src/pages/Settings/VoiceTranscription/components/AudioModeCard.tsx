import InlineHelp from "@/components/InlineHelp";
import { PolicySelector } from "@/components/interaction/PolicySelector";
import { AudioLines, Mic } from "lucide-react";
import { Card, Alert } from "antd";
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
        <InlineHelp>{t("voiceTranscription.audioModeDescription")}</InlineHelp>
      </h3>
      <PolicySelector
        label={t("voiceTranscription.audioModeLabel")}
        value={audioMode}
        onChange={onAudioModeChange}
        options={[
          {
            value: "auto",
            label: t("voiceTranscription.modeAuto"),
            description: t("voiceTranscription.modeAutoDesc"),
            icon: <AudioLines size={18} />,
          },
          {
            value: "native",
            label: t("voiceTranscription.modeNative"),
            description: t("voiceTranscription.modeNativeDesc"),
            icon: <Mic size={18} />,
          },
        ]}
      />

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
