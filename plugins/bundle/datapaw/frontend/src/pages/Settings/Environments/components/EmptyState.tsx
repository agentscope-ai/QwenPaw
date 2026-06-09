import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface EmptyStateProps {
  className?: string;
}

export function EmptyState({ className }: EmptyStateProps) {
  const { t } = useTranslation();

  return (
    <div className={`${styles.emptyState} ${className || ""}`}>
      <span className={styles.emptyIcon}>📦</span>
      <span>{t("environments.noVariables")}</span>
    </div>
  );
}
