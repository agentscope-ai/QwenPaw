import InlineHelp from "@/components/InlineHelp";
import { PolicySelector } from "@/components/interaction/PolicySelector";
import { MicOff, Cloud, Monitor } from "lucide-react";
import { Card } from "antd";
import { LocalWhisperCard } from "./LocalWhisperCard";
import { useTranslation } from "react-i18next";
import type { LocalWhisperStatus } from "../useVoiceTranscription";
import styles from "../index.module.less";

interface ProviderTypeCardProps {
  onInstall?: () => void;
  onEnable?: () => void;
  providerType: string;
  onProviderTypeChange: (value: string) => void;
  isLocalWhisper: boolean;
  localWhisperStatus: LocalWhisperStatus | null;
}

export function ProviderTypeCard({
  onInstall,
  onEnable,
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
        <LocalWhisperCard
          status={localWhisperStatus}
          onInstall={onInstall}
          onEnable={onEnable}
        />
      )}
    </Card>
  );
}
