import { ProviderCardStatus } from "./ProviderCardStatus";
import { ModelCardSurface } from "./ModelCardSurface";
import { ChevronRight } from "lucide-react";
import { ProviderCloseButton } from "./ProviderCloseButton";
import React, { useState } from "react";
import { Button, Modal, Input } from "@agentscope-ai/design";
import type { ProviderInfo } from "../../../../../api/types";
import api from "../../../../../api";
import { providerApi } from "../../../../../api/modules/provider";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { getIsConfigured } from "../../utils";
import styles from "../../index.module.less";
import HubProviderUsage from "./HubProviderUsage";
import { ProviderIcon } from "../ProviderIconComponent";
import { ProviderApiKeyLink } from "../ProviderApiKeyLink";
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

  const isManaged = provider.id === "hub-managed";
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

  const totalCount = new Set(
    [...provider.models, ...provider.extra_models].map((model) => model.id),
  ).size;
  const isConfigured = getIsConfigured(provider);

  const providerTag = isManaged ? (
    <span className={styles.customTag}>
      {t("hub.governance.provider.organization")}
    </span>
  ) : provider.is_custom ? (
    <span className={styles.customTag}>{t("models.custom")}</span>
  ) : null;

  return (
    <ModelCardSurface className={styles.groupCardGlass}>
      {!isManaged && (
        <ProviderCloseButton
          ids={[provider.id]}
          onSaved={onSaved}
          onConfigure={() => onOpenConfig(provider)}
        />
      )}
      {/* Header - same layout as GroupCard */}
      <div className={styles.groupCardHeader}>
        <ProviderIcon providerId={provider.id} size={36} />
        <span className={styles.groupCardName}>{provider.name}</span>
      </div>
      <ProviderCardStatus
        configured={isConfigured}
        disabled={provider.enabled === false}
        free={provider.is_free_tier}
      >
        {providerTag}
      </ProviderCardStatus>

      {/* Content - same layout as GroupCard */}
      <div className={styles.groupCardContent}>
        {!isManaged && (
          <>
            <div className={styles.groupCardField}>
              <span className={styles.groupCardFieldLabel}>Endpoint</span>
              <div className={styles.groupCardMono}>
                {provider.base_url || "—"}
              </div>
            </div>

            <div className={styles.groupCardField}>
              <span className={styles.groupCardFieldLabel}>
                API Key
                <ProviderApiKeyLink url={provider.meta?.api_key_url} />
              </span>
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
                      provider.api_key_prefixes?.length
                        ? `${provider.api_key_prefixes.join(", ")}...`
                        : provider.api_key_prefix
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
          </>
        )}
        <button
          type="button"
          className={styles.selectedModelsLink}
          onClick={() => onOpenModels(provider)}
        >
          <span>
            {t(
              provider.model_count == null
                ? "models.pool.enabledCount"
                : "models.pool.modelCount",
              {
                count: totalCount,
                total: provider.model_count ?? "—",
              },
            )}
          </span>
          <ChevronRight size={16} />
        </button>
        {isManaged && <HubProviderUsage />}
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
        {!isManaged && provider.is_custom && (
          <button
            className={`${styles.groupCardActBtn} ${styles.groupCardActBtnDanger}`}
            onClick={handleDeleteProvider}
          >
            {t("common.delete")}
          </button>
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
    </ModelCardSurface>
  );
});
