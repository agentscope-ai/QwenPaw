import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

export function ProviderCardStatus({
  configured,
  disabled = false,
  free = false,
  count,
  label,
  children,
}: {
  configured: boolean;
  disabled?: boolean;
  free?: boolean;
  count?: number;
  label?: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.providerStatusRow}>
      <span
        className={styles.providerStatus}
        data-ready={configured && !disabled}
      >
        <span className={styles.providerStatusDot} aria-hidden="true" />
        {label ??
          (disabled
            ? t("models.cardStatus.disabled")
            : configured
            ? count != null
              ? t("models.cardStatus.configuredCount", { count })
              : t("models.cardStatus.configured")
            : t("models.cardStatus.unconfigured"))}
      </span>
      {free && (
        <span className={styles.freeTag}>{t("models.includesFreeModels")}</span>
      )}
      {children}
    </div>
  );
}
