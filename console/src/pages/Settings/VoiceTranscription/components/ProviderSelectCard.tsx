import { useTranslation } from "react-i18next";
import type { TranscriptionProvider } from "../useVoiceTranscription";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import styles from "../index.module.less";

interface ProviderSelectCardProps {
  availableProviders: TranscriptionProvider[];
  selectedProviderId: string;
  onProviderChange: (id: string) => void;
}

export function ProviderSelectCard({
  availableProviders,
  selectedProviderId,
  onProviderChange,
}: ProviderSelectCardProps) {
  const { t } = useTranslation();

  return (
    <Card className={styles.card}>
      <CardContent className="pt-4">
        <h3 className={styles.cardTitle}>
          {t("voiceTranscription.providerLabel")}
        </h3>
        <p className={styles.cardDescription}>
          {t("voiceTranscription.providerDescription")}
        </p>

        {availableProviders.length === 0 ? (
          <div className="flex items-center gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200">
            <span>⚠</span>
            {t("voiceTranscription.noProvidersWarning")}
          </div>
        ) : (
          <Select
            value={selectedProviderId || undefined}
            onValueChange={onProviderChange}
          >
            <SelectTrigger className="w-full max-w-[400px]">
              <SelectValue
                placeholder={t("voiceTranscription.providerPlaceholder")}
              />
            </SelectTrigger>
            <SelectContent>
              {availableProviders.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </CardContent>
    </Card>
  );
}
