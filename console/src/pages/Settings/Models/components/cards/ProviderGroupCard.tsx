import { ProviderCredentialField } from "./ProviderCredentialField";
import { ProviderCardStatus } from "./ProviderCardStatus";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { ChevronRight } from "lucide-react";
import { ProviderCloseButton } from "./ProviderCloseButton";
import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../../../api/types";
import type { ProviderGroup } from "../../utils";
import { getIsConfigured } from "../../utils";
import { ProviderIcon } from "../ProviderIconComponent";
import styles from "../../index.module.less";

interface ProviderGroupCardProps {
  group: ProviderGroup;
  onSaved: () => void;
  onOpenConfig: (provider: ProviderInfo) => void;
  onOpenModels: (provider: ProviderInfo) => void;
}

const KNOWN_VARIANTS = new Set([
  "dashscope",
  "chat_completions",
  "responses",
  "open_platform",
  "open_platform_cn",
  "open_platform_intl",
  "coding_plan",
  "coding_plan_cn",
  "coding_plan_intl",
  "token_plan",
  "token_plan_intl",
  "china",
  "international",
]);

export const ProviderGroupCard = React.memo(function ProviderGroupCard({
  group,
  onSaved,
  onOpenConfig,
  onOpenModels,
}: ProviderGroupCardProps) {
  const { t } = useTranslation();
  const [activeIdx, setActiveIdx] = useState(0);

  const activeProvider = group.providers[activeIdx] || group.providers[0];
  const totalModels = new Set(
    [...activeProvider.models, ...activeProvider.extra_models].map(
      (model) => model.id,
    ),
  ).size;
  const liveCount = group.providers.filter(getIsConfigured).length;
  const hasFreeTier = activeProvider.is_free_tier;

  return (
    <InteractiveCard
      layoutId={`provider:${activeProvider.id}`}
      className={styles.groupCardGlass}
      tilt={2}
    >
      <ProviderCloseButton
        ids={group.providers.map((provider) => provider.id)}
        onSaved={onSaved}
        onConfigure={() => onOpenConfig(activeProvider)}
      />
      {/* Header */}
      <div className={styles.groupCardHeader}>
        <ProviderIcon
          providerId={group.providers[0]?.id ?? ""}
          size={36}
          decorative
        />
        <span className={styles.groupCardName}>{group.groupName}</span>
      </div>
      <ProviderCardStatus
        configured={liveCount > 0}
        count={liveCount}
        free={hasFreeTier}
      />

      {/* Segmented Control */}
      <div className={styles.groupSegmented}>
        {group.providers.map((provider, idx) => {
          const configured = getIsConfigured(provider);
          const variant = provider.provider_variant || "";
          const label = KNOWN_VARIANTS.has(variant)
            ? t(`models.providerVariants.${variant}`)
            : provider.name;
          return (
            <button
              type="button"
              aria-pressed={idx === activeIdx}
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
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className={styles.groupCardContent}>
        <div className={styles.groupCardField}>
          <span className={styles.groupCardFieldLabel}>
            {t("models.baseURL")}
          </span>
          <div className={styles.groupCardMono}>
            {activeProvider.base_url || "—"}
          </div>
        </div>

        <ProviderCredentialField
          key={activeProvider.id}
          provider={activeProvider}
          onSaved={onSaved}
        />

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
    </InteractiveCard>
  );
});
