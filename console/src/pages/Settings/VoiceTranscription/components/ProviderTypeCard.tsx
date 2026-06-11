import { useTranslation } from "react-i18next";
import type { LocalWhisperStatus } from "../useVoiceTranscription";
import { Card, CardContent } from "@/components/ui/card";
import styles from "../index.module.less";

interface ProviderTypeCardProps {
  providerType: string;
  onProviderTypeChange: (value: string) => void;
  isLocalWhisper: boolean;
  localWhisperStatus: LocalWhisperStatus | null;
}

const PROVIDER_TYPES = ["disabled", "whisper_api", "local_whisper"] as const;

function toI18nKey(value: string): string {
  return value
    .split("_")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join("");
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
      <CardContent className="pt-4">
        <h3 className={styles.cardTitle}>
          {t("voiceTranscription.providerTypeLabel")}
        </h3>
        <p className={styles.cardDescription}>
          {t("voiceTranscription.providerTypeDescription")}
        </p>
        <div className="flex flex-col gap-3">
          {PROVIDER_TYPES.map((value) => (
            <label
              key={value}
              className="flex cursor-pointer items-start gap-2"
            >
              <input
                type="radio"
                name="providerType"
                value={value}
                checked={providerType === value}
                onChange={() => onProviderTypeChange(value)}
                className="mt-1 accent-primary"
              />
              <span>
                <span className={styles.optionLabel}>
                  {t(`voiceTranscription.providerType${toI18nKey(value)}`)}
                </span>
                <span className={styles.optionDescription}>
                  {t(`voiceTranscription.providerType${toI18nKey(value)}Desc`)}
                </span>
              </span>
            </label>
          ))}
        </div>

        {isLocalWhisper && localWhisperStatus && (
          <div className="mt-3">
            {localWhisperStatus.available ? (
              <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark-mode:border-green-800 dark-mode:bg-green-950 dark-mode:text-green-200">
                <span className="text-green-500">✓</span>
                {t("voiceTranscription.localWhisperReady")}
              </div>
            ) : (
              <div className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200">
                <div className="font-medium">
                  {t("voiceTranscription.localWhisperMissing")}
                </div>
                <div className="mt-1 text-yellow-700 dark-mode:text-yellow-300">
                  {t("voiceTranscription.localWhisperMissingDesc", {
                    ffmpeg: localWhisperStatus.ffmpeg_installed
                      ? t("common.enabled")
                      : t("common.disabled"),
                    whisper: localWhisperStatus.whisper_installed
                      ? t("common.enabled")
                      : t("common.disabled"),
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
