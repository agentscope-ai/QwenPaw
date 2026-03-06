import { useState } from "react";
import { Card, Button, Tag, Modal, message } from "@agentscope-ai/design";
import {
  EditOutlined,
  DeleteOutlined,
  AppstoreOutlined,
} from "@ant-design/icons";
import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { ProviderConfigModal } from "../modals/ProviderConfigModal";
import { ModelManageModal } from "../modals/ModelManageModal";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

interface RemoteProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
  isHover: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function RemoteProviderCard({
  provider,
  activeModels,
  onSaved,
  isHover,
  onMouseEnter,
  onMouseLeave,
}: RemoteProviderCardProps) {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);
  const [modelManageOpen, setModelManageOpen] = useState(false);

  const handleDeleteProvider = (e: React.MouseEvent) => {
    e.stopPropagation();
    Modal.confirm({
      title: t("models.deleteProvider"),
      content: t("models.deleteProviderConfirm", { name: provider.name }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.deleteCustomProvider(provider.id);
          message.success(t("models.providerDeleted", { name: provider.name }));
          onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.providerDeleteFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const totalCount = provider.models.length;
  const isConfigured =
    provider.id === "ollama"
      ? !!provider.current_base_url
      : provider.is_local
      ? true
      : provider.is_custom
      ? !!provider.current_base_url
      : !!provider.current_api_key;
  const hasModels = totalCount > 0;
  const isAvailable = isConfigured && hasModels;

  const providerTag = provider.is_custom ? (
    <Tag color="blue" style={{ marginLeft: 8, fontSize: 11 }}>
      {t("models.custom")}
    </Tag>
  ) : (
    <Tag color="green" style={{ marginLeft: 8, fontSize: 11 }}>
      {t("models.builtin")}
    </Tag>
  );

  const statusLabel = isAvailable
    ? t("models.providerAvailable")
    : isConfigured
    ? t("models.providerNoModels")
    : t("models.providerNotConfigured");
  const statusType = isAvailable
    ? "enabled"
    : isConfigured
    ? "partial"
    : "disabled";
  const statusDotColor = isAvailable
    ? "#52c41a"
    : isConfigured
    ? "#faad14"
    : "#d9d9d9";
  const statusDotShadow = isAvailable
    ? "0 0 0 2px rgba(82, 196, 26, 0.2)"
    : isConfigured
    ? "0 0 0 2px rgba(250, 173, 20, 0.2)"
    : "none";

  return (
    <Card
      hoverable
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`${styles.providerCard} ${
        isAvailable ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal}`}
    >
      <div style={{ marginBottom: 16 }}>
        <div className={styles.cardHeader}>
          <span className={styles.cardName}>
            {provider.name}
            {providerTag}
          </span>
          <div className={styles.statusContainer}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: statusDotColor,
                boxShadow: statusDotShadow,
              }}
            />
            <span
              className={`${styles.statusText} ${
                statusType === "enabled"
                  ? styles.enabled
                  : statusType === "partial"
                  ? styles.partial
                  : styles.disabled
              }`}
            >
              {statusLabel}
            </span>
          </div>
        </div>

        <div className={styles.cardInfo}>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.baseURL")}:</span>
            {provider.current_base_url ? (
              <span
                className={styles.infoValue}
                title={provider.current_base_url}
              >
                {provider.current_base_url}
              </span>
            ) : (
              <span className={styles.infoEmpty}>{t("models.notSet")}</span>
            )}
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.apiKey")}:</span>
            {provider.current_api_key ? (
              <span className={styles.infoValue}>
                {provider.current_api_key}
              </span>
            ) : (
              <span className={styles.infoEmpty}>{t("models.notSet")}</span>
            )}
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.model")}:</span>
            <span className={styles.infoValue}>
              {totalCount > 0
                ? t("models.modelsCount", { count: totalCount })
                : t("models.noModels")}
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
        <Button
          type="link"
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            setModalOpen(true);
          }}
          className={styles.configBtn}
          icon={<EditOutlined />}
        >
          {t("models.settings")}
        </Button>
        {provider.is_custom && (
          <Button
            type="link"
            size="small"
            danger
            onClick={handleDeleteProvider}
            icon={<DeleteOutlined />}
          >
            {t("models.deleteProvider")}
          </Button>
        )}
      </div>

      <ProviderConfigModal
        provider={provider}
        activeModels={activeModels}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={onSaved}
      />
      <ModelManageModal
        provider={provider}
        open={modelManageOpen}
        onClose={() => setModelManageOpen(false)}
        onSaved={onSaved}
      />
    </Card>
  );
}
