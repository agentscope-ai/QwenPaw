import React, { useState } from "react";
import { Card, Button } from "@agentscope-ai/design";
import type { ProviderInfo } from "../../../../../api/types";
import { ModelManageModal } from "../modals/ModelManageModal";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";
import { providerIcon } from "../providerIcon";

interface LocalProviderCardProps {
  provider: ProviderInfo;
  onSaved: () => void;
}

export const LocalProviderCard = React.memo(function LocalProviderCard({
  provider,
  onSaved,
}: LocalProviderCardProps) {
  const { t } = useTranslation();
  const [isHover, setIsHover] = useState(false);
  const [modelManageOpen, setModelManageOpen] = useState(false);

  const totalCount = provider.models.length + provider.extra_models.length;
  const statusReady = totalCount > 0;
  const statusLabel = statusReady
    ? t("models.available")
    : t("models.unavailable");

  return (
    <Card
      hoverable
      onMouseEnter={() => setIsHover(true)}
      onMouseLeave={() => setIsHover(false)}
      className={`${styles.providerCard} ${
        statusReady ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal}`}
    >
      {/* Card Header with Icon and Status */}
      <div className={styles.cardHeaderRow}>
        <img
          src={providerIcon(provider.id)}
          alt={provider.name}
          className={styles.providerIcon}
        />
        <div className={styles.cardStatusHeader}>
          <span
            className={styles.statusDot}
            style={{
              backgroundColor: statusReady ? "#52c41a" : "#d9d9d9",
              boxShadow: statusReady
                ? "0 0 0 2px rgba(82, 196, 26, 0.2)"
                : "none",
            }}
          />
          <span
            className={`${styles.statusText} ${
              statusReady ? styles.enabled : styles.disabled
            }`}
          >
            {statusLabel}
          </span>
        </div>
      </div>

      {/* Title Row */}
      <div className={styles.cardTitleRow}>
        <span className={styles.cardName}>{provider.name}</span>
        <span className={styles.localTag}>{t("models.local")}</span>
      </div>

      {/* Info Section */}
      <div className={styles.cardInfo}>
        <div className={styles.infoRow}>
          <span className={styles.infoLabel}>{t("models.localType")}:</span>
          <span className={styles.infoValue}>{t("models.localEmbedded")}</span>
        </div>
        <div className={styles.infoRow}>
          <span className={styles.infoLabel}>{t("models.model")}:</span>
          <span className={styles.infoValue}>
            {totalCount > 0
              ? t("models.modelsCount", { count: totalCount })
              : t("models.localDownloadFirst")}
          </span>
        </div>
      </div>

      {/* Actions - only show on hover */}
      {isHover && (
        <div className={styles.cardActions}>
          <Button
            type="default"
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              setModelManageOpen(true);
            }}
            className={styles.actionBtn}
          >
            {t("models.models")}
          </Button>
        </div>
      )}

      <ModelManageModal
        provider={provider}
        open={modelManageOpen}
        onClose={() => setModelManageOpen(false)}
        onSaved={onSaved}
      />
    </Card>
  );
});
