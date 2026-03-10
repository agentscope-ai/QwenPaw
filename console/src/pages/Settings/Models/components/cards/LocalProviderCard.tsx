import { useState } from "react";
import { Card, Button, Tag } from "@agentscope-ai/design";
import { AppstoreOutlined } from "@ant-design/icons";
import type { ProviderInfo } from "../../../../../api/types";
import { ModelManageModal } from "../modals/ModelManageModal";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

interface LocalProviderCardProps {
  provider: ProviderInfo;
  onSaved: () => void;
  isHover: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function LocalProviderCard({
  provider,
  onSaved,
  isHover,
  onMouseEnter,
  onMouseLeave,
}: LocalProviderCardProps) {
  const { t } = useTranslation();
  const [modelManageOpen, setModelManageOpen] = useState(false);

  const totalCount = provider.models.length + provider.extra_models.length;
  const statusReady = totalCount > 0;
  const statusLabel = statusReady
    ? t("models.available")
    : t("models.unavailable");

  return (
    <Card
      hoverable
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`${styles.providerCard} ${
        statusReady ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal}`}
    >
      <div style={{ marginBottom: 16 }}>
        <div className={styles.cardHeader}>
          <span className={styles.cardName}>
            {provider.name}
            <Tag color="purple" style={{ marginLeft: 8, fontSize: 11 }}>
              {t("models.local")}
            </Tag>
          </span>
          <div className={styles.statusContainer}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
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

        <div className={styles.cardInfo}>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.localType")}:</span>
            <span className={styles.infoValue}>
              {t("models.localEmbedded")}
            </span>
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
      </div>

      <div className={styles.cardActions}>
        <Button
          type="link"
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            setModelManageOpen(true);
          }}
          className={styles.configBtn}
          icon={<AppstoreOutlined />}
        >
          {t("models.manageModels")}
        </Button>
      </div>

      <ModelManageModal
        provider={provider}
        open={modelManageOpen}
        onClose={() => setModelManageOpen(false)}
        onSaved={onSaved}
      />
    </Card>
  );
}
