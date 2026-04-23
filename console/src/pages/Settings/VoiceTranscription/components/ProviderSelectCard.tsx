import { Card, Select, Alert } from "antd";
import { useTranslation } from "react-i18next";
import type { TranscriptionProvider } from "../useVoiceTranscription";
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
      <h3 className={styles.cardTitle}>
        {t("voiceTranscription.providerLabel")}
      </h3>
      <p className={styles.cardDescription}>
        {t("voiceTranscription.providerDescription")}
      </p>

      {availableProviders.length === 0 ? (
        <Alert
          type="warning"
          showIcon
          message={t("voiceTranscription.noProvidersWarning")}
        />
      ) : (
        <Select
          value={selectedProviderId || undefined}
          onChange={onProviderChange}
          placeholder={t("voiceTranscription.providerPlaceholder")}
          style={{ width: "100%", maxWidth: 400 }}
        >
          {availableProviders.map((p) => (
            <Select.Option key={p.id} value={p.id}>
              {p.name}
            </Select.Option>
          ))}
        </Select>
      )}
    </Card>
  );
}
