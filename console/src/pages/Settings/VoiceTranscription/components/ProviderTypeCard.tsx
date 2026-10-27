import InlineHelp from "@/components/InlineHelp";
import { PolicySelector } from "@/components/interaction/PolicySelector";
import { MicOff, Cloud, Monitor } from "lucide-react";
import { Card, Alert } from "antd";
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
        <InlineHelp>
          {t("voiceTranscription.providerTypeDescription")}
        </InlineHelp>
      </h3>
      <PolicySelector
        label={t("voiceTranscription.providerTypeLabel")}
        value={providerType}
        onChange={onProviderTypeChange}
        options={[
          {
            value: "disabled",
            label: t("voiceTranscription.providerTypeDisabled"),
            description: t("voiceTranscription.providerTypeDisabledDesc"),
            icon: <MicOff size={18} />,
          },
          {
            value: "whisper_api",
            label: t("voiceTranscription.providerTypeWhisperApi"),
            description: t("voiceTranscription.providerTypeWhisperApiDesc"),
            icon: <Cloud size={18} />,
          },
          {
            value: "local_whisper",
            label: t("voiceTranscription.providerTypeLocalWhisper"),
            description: t("voiceTranscription.providerTypeLocalWhisperDesc"),
            icon: <Monitor size={18} />,
          },
        ]}
      />

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
