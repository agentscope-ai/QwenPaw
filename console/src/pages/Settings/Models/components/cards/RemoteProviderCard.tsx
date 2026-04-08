import React, { useState } from "react";
import { Card, Button, Modal } from "@agentscope-ai/design";
import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { ProviderConfigModal } from "../modals/ProviderConfigModal";
import { ModelManageModal } from "../modals/ModelManageModal";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import styles from "../../index.module.less";
import { providerIcon } from "../providerIcon";

interface RemoteProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
}

export const RemoteProviderCard = React.memo(function RemoteProviderCard({
  provider,
  activeModels,
  onSaved,
}: RemoteProviderCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [isHover, setIsHover] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modelManageOpen, setModelManageOpen] = useState(false);
  const [runDiscover, setRunDiscover] = useState(false);

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

  const handleRequestDiscover = () => {
    setRunDiscover(true);
    setModelManageOpen(true);
  };

  const handleModelManageClose = () => {
    setModelManageOpen(false);
    setRunDiscover(false);
  };

  const totalCount = provider.models.length + provider.extra_models.length;

  let isConfigured = false;

  if (provider.id === "qwenpaw-local") {
    isConfigured = true;
  } else if (provider.is_custom && provider.base_url) {
    isConfigured = true;
  } else if (provider.require_api_key === false) {
    isConfigured = true;
  } else if (provider.require_api_key && provider.api_key) {
    isConfigured = true;
  }

  const hasModels = totalCount > 0;
  const isAvailable = isConfigured && hasModels;

  const providerTag = provider.is_custom ? (
    <span className={styles.customTag}>{t("models.custom")}</span>
  ) : (
    <span className={styles.builtinTag}>{t("models.builtin")}</span>
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
    ? "rgba(20, 184, 166, 1)"
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
      onMouseEnter={() => setIsHover(true)}
      onMouseLeave={() => setIsHover(false)}
      className={`${styles.providerCard} ${
        isAvailable ? styles.enabledCard : ""
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

      {/* Title Row */}
      <div className={styles.cardTitleRow}>
        <span className={styles.cardName}>{provider.name}</span>
        {providerTag}
      </div>

      {/* Info Section */}
      <div className={styles.cardInfo}>
        <div className={styles.infoRow}>
          <span className={styles.infoLabel}>Base URL:</span>
          {provider.base_url ? (
            <span className={styles.infoValue} title={provider.base_url}>
              {provider.base_url}
            </span>
          ) : (
            <span className={styles.infoEmpty}>{t("models.notSet")}</span>
          )}
        </div>
        <div className={styles.infoRow}>
          <span className={styles.infoLabel}>API Key:</span>
          {provider.api_key ? (
            <span className={styles.infoValue}>{provider.api_key}</span>
          ) : (
            <span className={styles.infoEmpty}>{t("models.notSet")}</span>
          )}
        </div>
        <div className={styles.infoRow}>
          <span className={styles.infoLabel}>Model:</span>
          <span className={styles.infoValue}>
            {totalCount > 0
              ? t("models.modelsCount", { count: totalCount })
              : t("models.noModels")}
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
          <Button
            type="default"
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              setModalOpen(true);
            }}
            className={styles.actionBtn}
          >
            {t("models.settings")}
          </Button>
          {provider.is_custom && (
            <Button
              type="default"
              size="small"
              danger
              onClick={handleDeleteProvider}
              className={styles.actionBtn}
            >
              {t("common.delete")}
            </Button>
          )}
        </div>
      )}

      <ProviderConfigModal
        provider={provider}
        activeModels={activeModels}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={onSaved}
        onRequestDiscover={handleRequestDiscover}
      />
      <ModelManageModal
        provider={provider}
        open={modelManageOpen}
        onClose={handleModelManageClose}
        onSaved={onSaved}
        runDiscover={runDiscover}
      />
    </Card>
  );
});
