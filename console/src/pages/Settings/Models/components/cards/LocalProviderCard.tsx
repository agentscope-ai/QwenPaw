import { ProviderCardStatus } from "./ProviderCardStatus";
import { ModelCardSurface } from "./ModelCardSurface";
import React from "react";
import type { ProviderInfo } from "../../../../../api/types";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";
import { ProviderIcon } from "../ProviderIconComponent";

interface LocalProviderCardProps {
  provider: ProviderInfo;
  onOpenModels: (provider: ProviderInfo) => void;
}

export const LocalProviderCard = React.memo(function LocalProviderCard({
  provider,
  onOpenModels,
}: LocalProviderCardProps) {
  const { t } = useTranslation();

  const totalCount = provider.models.length + provider.extra_models.length;
  const statusReady = totalCount > 0;

  return (
    <ModelCardSurface className={styles.groupCardGlass}>
      {/* Header - same layout as GroupCard */}
      <div className={styles.groupCardHeader}>
        <ProviderIcon providerId={provider.id} size={36} />
        <span className={styles.groupCardName}>{provider.name}</span>
      </div>
      <ProviderCardStatus
        configured={statusReady}
        label={
          statusReady
            ? t("models.cardStatus.ready")
            : t("models.localDownloadFirst")
        }
      >
        <span className={styles.localTag}>{t("models.local")}</span>
      </ProviderCardStatus>

      {/* Content */}
      <div className={styles.groupCardContent}>
        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>
            {t("models.localType")}
          </span>
          <div className={styles.groupCardMono}>
            {t("models.localEmbedded")}
          </div>
        </div>
        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>Models</span>
          <span className={styles.groupCardFieldValue}>
            {totalCount > 0
              ? t("models.modelsCount", { count: totalCount })
              : t("models.localDownloadFirst")}
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className={styles.groupCardActions}>
        <button
          className={`${styles.groupCardActBtn} ${styles.groupCardPrimaryAction}`}
          onClick={() => onOpenModels(provider)}
        >
          {t("models.models")}
        </button>
      </div>
    </ModelCardSurface>
  );
});
