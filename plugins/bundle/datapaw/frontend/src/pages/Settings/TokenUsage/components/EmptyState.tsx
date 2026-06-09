import styles from "../index.module.less";

interface EmptyStateProps {
  message: string;
  className?: string;
}

export function EmptyState({ message, className }: EmptyStateProps) {
  return (
    <div className={`${styles.emptyState} ${className ?? ""}`}>
      <span className={styles.emptyIcon}>📊</span>
      <span>{message}</span>
    </div>
  );
}
