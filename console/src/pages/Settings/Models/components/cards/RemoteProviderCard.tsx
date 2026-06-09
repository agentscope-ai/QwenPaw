import React, { useState } from "react";
import { Card, Button, Modal, Input } from "@agentscope-ai/design";
import type { ProviderInfo } from "../../../../../api/types";
import api from "../../../../../api";
import { providerApi } from "../../../../../api/modules/provider";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { getIsConfigured } from "../../utils";
import styles from "../../index.module.less";
import { ProviderIcon } from "../ProviderIconComponent";
import { OAuthConfirmModal } from "../../../../Chat/ModelSelector/OAuthConfirmModal";

interface RemoteProviderCardProps {
  provider: ProviderInfo;
  onSaved: () => void;
  onOpenConfig: (provider: ProviderInfo) => void;
  onOpenModels: (provider: ProviderInfo) => void;
}

export const RemoteProviderCard = React.memo(function RemoteProviderCard({
  provider,
  onSaved,
  onOpenConfig,
  onOpenModels,
}: RemoteProviderCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [oauthModalOpen, setOauthModalOpen] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiKeySaving, setApiKeySaving] = useState(false);

  const needsOAuth =
    provider.supports_oauth && !provider.api_key && !provider.oauth_connected;

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

  const totalCount = provider.models.length + provider.extra_models.length;
  const isConfigured = getIsConfigured(provider);
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
    <Card hoverable className={styles.providerCard}>
      {/* Card Header with Icon and Status */}
      <div className={styles.cardHeaderRow}>
        <ProviderIcon providerId={provider.id} size={32} />
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
          ) : provider.require_api_key === false ? (
            <span className={styles.infoEmpty}>{t("models.notRequired")}</span>
          ) : (
            <div className={styles.inlineKeyInput}>
              <Input.Password
                size="small"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                placeholder={
                  provider.api_key_prefix
                    ? `${provider.api_key_prefix}...`
                    : "sk-..."
                }
                style={{ flex: 1 }}
              />
              <Button
                type="primary"
                size="small"
                loading={apiKeySaving}
                disabled={!apiKeyInput.trim()}
                onClick={async (e) => {
                  e.stopPropagation();
                  setApiKeySaving(true);
                  try {
                    await providerApi.configureProvider(provider.id, {
                      api_key: apiKeyInput.trim(),
                    });
                    message.success(t("models.saved"));
                    setApiKeyInput("");
                    onSaved();
                  } catch (err) {
                    const msg =
                      err instanceof Error
                        ? err.message
                        : t("models.failedToSave");
                    message.error(msg);
                  } finally {
                    setApiKeySaving(false);
                  }
                }}
              >
                {t("models.saveApiKey")}
              </Button>
            </div>
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

      <div className={styles.cardActions}>
        {needsOAuth && (
          <Button
            type="primary"
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              setOauthModalOpen(true);
            }}
            className={styles.actionBtn}
          >
            {t("models.connect")}
          </Button>
        )}
        <Button
          type="default"
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            onOpenModels(provider);
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
            onOpenConfig(provider);
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

      <OAuthConfirmModal
        open={oauthModalOpen}
        providerId={provider.id}
        providerName={provider.name}
        onSuccess={() => {
          setOauthModalOpen(false);
          onSaved();
        }}
        onCancel={() => setOauthModalOpen(false)}
      />
    </Card>
  );
});
