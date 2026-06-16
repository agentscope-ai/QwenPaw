import React, { useState } from "react";
import { Button, Modal, Input } from "@agentscope-ai/design";
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
  ) : null;

  return (
    <div className={styles.groupCardGlass}>
      {/* Header - same layout as GroupCard */}
      <div className={styles.groupCardHeader}>
        <ProviderIcon providerId={provider.id} size={36} />
        <span className={styles.groupCardName}>{provider.name}</span>
        {providerTag}
        {provider.is_free_tier && <span className={styles.freeTag}>FREE</span>}
        {isAvailable && (
          <div className={styles.groupCardLiveBadge}>
            <span className={styles.groupCardPulse} />
            Live
          </div>
        )}
      </div>

      {/* Content - same layout as GroupCard */}
      <div className={styles.groupCardContent}>
        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>Endpoint</span>
          <div className={styles.groupCardMono}>{provider.base_url || "—"}</div>
        </div>

        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>API Key</span>
          {provider.api_key ? (
            <div className={styles.groupCardMono}>
              <span>{provider.api_key}</span>
              <span
                className={styles.groupCardChangeBtn}
                onClick={() => onOpenConfig(provider)}
              >
                {t("models.changeApiKey")}
              </span>
            </div>
          ) : provider.require_api_key === false ? (
            <div className={styles.groupCardMono}>
              {t("models.notRequired")}
            </div>
          ) : (
            <div className={styles.groupCardKeyInput}>
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

        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>Models</span>
          <span className={styles.groupCardFieldValue}>
            {totalCount > 0
              ? t("models.modelsCount", { count: totalCount })
              : t("models.noModels")}
          </span>
        </div>
      </div>

      {/* Actions - same layout as GroupCard */}
      <div className={styles.groupCardActions}>
        {needsOAuth && (
          <button
            className={styles.groupCardActBtn}
            onClick={() => setOauthModalOpen(true)}
          >
            {t("models.connect")}
          </button>
        )}
        <button
          className={styles.groupCardActBtn}
          onClick={() => onOpenModels(provider)}
        >
          {t("models.models")}
        </button>
        <button
          className={styles.groupCardActBtn}
          onClick={() => onOpenConfig(provider)}
        >
          {t("models.settings")}
        </button>
        {provider.is_custom ? (
          <button
            className={`${styles.groupCardActBtn} ${styles.groupCardActBtnDanger}`}
            onClick={handleDeleteProvider}
          >
            {t("common.delete")}
          </button>
        ) : (
          isConfigured &&
          provider.require_api_key !== false && (
            <button
              className={`${styles.groupCardActBtn} ${styles.groupCardActBtnDanger}`}
              onClick={(e) => {
                e.stopPropagation();
                Modal.confirm({
                  title: t("models.disableProvider"),
                  content: t("models.disableProviderConfirm", {
                    name: provider.name,
                  }),
                  okText: t("models.disableBtn"),
                  okButtonProps: { danger: true },
                  cancelText: t("models.cancel"),
                  onOk: async () => {
                    try {
                      await providerApi.configureProvider(provider.id, {
                        api_key: "",
                      });
                      message.success(
                        t("models.providerDisabled", {
                          name: provider.name,
                        }),
                      );
                      onSaved();
                    } catch (err) {
                      const msg =
                        err instanceof Error
                          ? err.message
                          : t("models.failedToSave");
                      message.error(msg);
                    }
                  },
                });
              }}
            >
              {t("models.disableBtn")}
            </button>
          )
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
    </div>
  );
});
