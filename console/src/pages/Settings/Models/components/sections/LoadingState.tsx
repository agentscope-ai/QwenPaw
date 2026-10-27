import {
  LoadingState as SharedLoadingState,
  type LoadingStateProps,
} from "@/components/LoadingState";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

export function LoadingState({
  message,
  error,
  onRetry,
  className,
}: LoadingStateProps) {
  const { t } = useTranslation();

  return (
    <SharedLoadingState
      className={`${styles.loading} ${className || ""}`}
      textClassName={styles.loadingText}
      message={message}
      error={error}
      errorColor="var(--app-error-text)"
      onRetry={onRetry}
      retryLabel={t("models.retry")}
    />
  );
}
