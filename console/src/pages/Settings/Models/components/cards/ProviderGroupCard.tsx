import { ChevronRight } from "lucide-react";
import { ProviderCloseButton } from "./ProviderCloseButton";
import React, { useState } from "react";
import { Button, Input } from "@agentscope-ai/design";
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
  const totalModels = new Set(
    [...activeProvider.models, ...activeProvider.extra_models].map(
      (model) => model.id,
    ),
  ).size;
  const liveCount = group.providers.filter(getIsConfigured).length;
  const hasFreeTier = activeProvider.is_free_tier;

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
      <ProviderCloseButton
        ids={group.providers.map((provider) => provider.id)}
        onSaved={onSaved}
        onConfigure={() => onOpenConfig(activeProvider)}
      />
      {/* Header */}
      <div className={styles.groupCardHeader}>
        <ProviderIcon providerId={group.providers[0]?.id ?? ""} size={36} />
        <span className={styles.groupCardName}>{group.groupName}</span>
        {hasFreeTier && (
          <span className={styles.freeTag}>
            {t("models.includesFreeModels")}
          </span>
        )}
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
                  activeProvider.api_key_prefixes?.length
                    ? `${activeProvider.api_key_prefixes.join(", ")}...`
                    : activeProvider.api_key_prefix
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

        <button
          type="button"
          className={styles.selectedModelsLink}
          onClick={() => onOpenModels(activeProvider)}
        >
          <span>
            {t(
              activeProvider.model_count == null
                ? "models.pool.enabledCount"
                : "models.pool.modelCount",
              {
                count: totalModels,
                total: activeProvider.model_count ?? "—",
              },
            )}
          </span>
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
});
