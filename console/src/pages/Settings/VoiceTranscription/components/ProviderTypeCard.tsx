import { PreferenceChoice } from "@/components/interaction/PreferenceChoice";
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
      </h3>
      <p className={styles.cardDescription}>
        {t("voiceTranscription.providerTypeDescription")}
      </p>
      <div className={styles.choiceGrid}>
        <PreferenceChoice
          label={t("voiceTranscription.providerTypeDisabled")}
          description={t("voiceTranscription.providerTypeDisabledDesc")}
          icon={<MicOff size={20} />}
          selected={providerType === "disabled"}
          onSelect={() => onProviderTypeChange("disabled")}
        />
        <PreferenceChoice
          label={t("voiceTranscription.providerTypeWhisperApi")}
          description={t("voiceTranscription.providerTypeWhisperApiDesc")}
          icon={<Cloud size={20} />}
          selected={providerType === "whisper_api"}
          onSelect={() => onProviderTypeChange("whisper_api")}
        />
        <PreferenceChoice
          label={t("voiceTranscription.providerTypeLocalWhisper")}
          description={t("voiceTranscription.providerTypeLocalWhisperDesc")}
          icon={<Monitor size={20} />}
          selected={providerType === "local_whisper"}
          onSelect={() => onProviderTypeChange("local_whisper")}
        />
      </div>

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
