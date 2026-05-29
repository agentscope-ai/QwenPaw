import styles from "./EmptyState.module.less";

interface EmptyStateProps {
  text: string;
  children?: React.ReactNode;
}

export function EmptyState({ text, children }: EmptyStateProps) {
  return (
    <div className={styles.emptyState}>
      <span className={styles.icon}>📦</span>
      <span className={styles.text}>{text}</span>
      {children}
    </div>
  );
}
