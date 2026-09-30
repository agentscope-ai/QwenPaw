import { Card, Input } from "antd";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface TranscriptionModelCardProps {
  transcriptionModel: string;
  onTranscriptionModelChange: (value: string) => void;
}

export function TranscriptionModelCard({
  transcriptionModel,
  onTranscriptionModelChange,
}: TranscriptionModelCardProps) {
  const { t } = useTranslation();

  return (
    <Card className={styles.card}>
      <h3 className={styles.cardTitle}>{t("voiceTranscription.modelLabel")}</h3>
      <p className={styles.cardDescription}>
        {t("voiceTranscription.modelDescription")}
      </p>
      <Input
        value={transcriptionModel}
        onChange={(e) => onTranscriptionModelChange(e.target.value)}
        placeholder={t("voiceTranscription.modelPlaceholder")}
        style={{ width: "100%", maxWidth: 400 }}
        allowClear
      />
    </Card>
  );
}
