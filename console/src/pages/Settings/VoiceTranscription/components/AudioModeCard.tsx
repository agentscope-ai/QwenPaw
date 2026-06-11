import { useTranslation } from "react-i18next";
import type { LocalWhisperStatus } from "../useVoiceTranscription";
import { Card, CardContent } from "@/components/ui/card";
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
      <CardContent className="pt-4">
        <h3 className={styles.cardTitle}>
          {t("voiceTranscription.audioModeLabel")}
        </h3>
        <p className={styles.cardDescription}>
          {t("voiceTranscription.audioModeDescription")}
        </p>
        <div className="flex flex-col gap-3">
          {(["auto", "native"] as const).map((value) => (
            <label
              key={value}
              className="flex cursor-pointer items-start gap-2"
            >
              <input
                type="radio"
                name="audioMode"
                value={value}
                checked={audioMode === value}
                onChange={() => onAudioModeChange(value)}
                className="mt-1 accent-primary"
              />
              <span>
                <span className={styles.optionLabel}>
                  {t(
                    `voiceTranscription.mode${
                      value.charAt(0).toUpperCase() + value.slice(1)
                    }`,
                  )}
                </span>
                <span className={styles.optionDescription}>
                  {t(
                    `voiceTranscription.mode${
                      value.charAt(0).toUpperCase() + value.slice(1)
                    }Desc`,
                  )}
                </span>
              </span>
            </label>
          ))}
        </div>

        {audioMode === "native" && localWhisperStatus && (
          <div className="mt-3">
            {localWhisperStatus.ffmpeg_installed ? (
              <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark-mode:border-green-800 dark-mode:bg-green-950 dark-mode:text-green-200">
                <span className="text-green-500">✓</span>
                {t("voiceTranscription.ffmpegReady")}
              </div>
            ) : (
              <div className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200">
                <div className="font-medium">
                  {t("voiceTranscription.ffmpegMissing")}
                </div>
                <div className="mt-1 text-yellow-700 dark-mode:text-yellow-300">
                  {t("voiceTranscription.ffmpegMissingDesc")}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
