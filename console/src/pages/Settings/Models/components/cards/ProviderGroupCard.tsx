import React, { useState } from "react";
import { Button, Input, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../../../api/types";
import type { ProviderGroup } from "../../utils";
import { getIsConfigured } from "../../utils";
import { providerApi } from "../../../../../api/modules/provider";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { ProviderIcon } from "../ProviderIconComponent";
import styles from "../../index.module.less";

interface ProviderGroupCardProps {
  group: ProviderGroup;
  onSaved: () => void;
  onOpenConfig: (provider: ProviderInfo) => void;
  onOpenModels: (provider: ProviderInfo) => void;
}

const VARIANT_LABELS: Record<string, string> = {
  dashscope: "DashScope",
  open_platform: "Open Platform",
  open_platform_cn: "China",
  open_platform_intl: "International",
  coding_plan: "Coding Plan",
  coding_plan_cn: "Coding (CN)",
  coding_plan_intl: "Coding (Intl)",
  token_plan: "Token Plan",
  token_plan_intl: "Token (Intl)",
  china: "China",
  international: "International",
};

export const ProviderGroupCard = React.memo(function ProviderGroupCard({
  group,
  onSaved,
  onOpenConfig,
  onOpenModels,
}: ProviderGroupCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [activeIdx, setActiveIdx] = useState(0);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [saving, setSaving] = useState(false);

  const activeProvider = group.providers[activeIdx] || group.providers[0];
  const totalModels =
    activeProvider.models.length + activeProvider.extra_models.length;
  const liveCount = group.providers.filter(getIsConfigured).length;
  const hasFreeTier = group.providers.some((p) => p.is_free_tier);

  const handleSaveKey = async () => {
    if (!apiKeyInput.trim()) return;
    setSaving(true);
    try {
      await providerApi.configureProvider(activeProvider.id, {
        api_key: apiKeyInput.trim(),
      });
      message.success(t("models.saved"));
      setApiKeyInput("");
      onSaved();
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("models.failedToSave");
      message.error(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.groupCardGlass}>
      {/* Header */}
      <div className={styles.groupCardHeader}>
        <ProviderIcon providerId={group.providers[0]?.id ?? ""} size={36} />
        <span className={styles.groupCardName}>{group.groupName}</span>
        {hasFreeTier && <span className={styles.freeTag}>FREE</span>}
        {liveCount > 0 && (
          <div className={styles.groupCardLiveBadge}>
            <span className={styles.groupCardPulse} />
            {liveCount} Live
          </div>
        )}
      </div>

      {/* Segmented Control */}
      <div className={styles.groupSegmented}>
        {group.providers.map((provider, idx) => {
          const configured = getIsConfigured(provider);
          const label =
            VARIANT_LABELS[provider.provider_variant || ""] || provider.name;
          return (
            <div
              key={provider.id}
              className={[
                styles.groupSegBtn,
                idx === activeIdx ? styles.groupSegBtnActive : "",
              ].join(" ")}
              onClick={() => setActiveIdx(idx)}
            >
              <span
                className={[
                  styles.groupSegDot,
                  configured ? styles.groupSegDotOn : styles.groupSegDotOff,
                ].join(" ")}
              />
              {label}
            </div>
          );
        })}
      </div>

      {/* Content */}
      <div className={styles.groupCardContent}>
        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>Endpoint</span>
          <div className={styles.groupCardMono}>
            {activeProvider.base_url || "—"}
          </div>
        </div>

        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>API Key</span>
          {activeProvider.api_key ? (
            <div className={styles.groupCardMono}>
              <span>{activeProvider.api_key}</span>
              <span
                className={styles.groupCardChangeBtn}
                onClick={() => onOpenConfig(activeProvider)}
              >
                {t("models.changeApiKey")}
              </span>
            </div>
          ) : activeProvider.require_api_key === false ? (
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
                  activeProvider.api_key_prefix
                    ? `${activeProvider.api_key_prefix}...`
                    : "sk-..."
                }
                style={{ flex: 1 }}
              />
              <Button
                type="primary"
                size="small"
                loading={saving}
                disabled={!apiKeyInput.trim()}
                onClick={handleSaveKey}
              >
                {t("models.saveApiKey")}
              </Button>
            </div>
          )}
        </div>

        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>Models</span>
          <span className={styles.groupCardFieldValue}>
            {totalModels > 0
              ? t("models.modelsCount", { count: totalModels })
              : t("models.noModels")}
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className={styles.groupCardActions}>
        <button
          className={styles.groupCardActBtn}
          onClick={() => onOpenModels(activeProvider)}
        >
          {t("models.models")}
        </button>
        <button
          className={styles.groupCardActBtn}
          onClick={() => onOpenConfig(activeProvider)}
        >
          {t("models.settings")}
        </button>
        {getIsConfigured(activeProvider) &&
          activeProvider.require_api_key !== false && (
            <button
              className={`${styles.groupCardActBtn} ${styles.groupCardActBtnDanger}`}
              onClick={() => {
                Modal.confirm({
                  title: t("models.disableProvider"),
                  content: t("models.disableProviderConfirm", {
                    name: activeProvider.name,
                  }),
                  okText: t("models.disableBtn"),
                  okButtonProps: { danger: true },
                  cancelText: t("models.cancel"),
                  onOk: async () => {
                    try {
                      await providerApi.configureProvider(activeProvider.id, {
                        api_key: "",
                      });
                      message.success(
                        t("models.providerDisabled", {
                          name: activeProvider.name,
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
          )}
      </div>
    </div>
  );
});
