import { PackageOpen } from "lucide-react";
import styles from "./EmptyState.module.less";

interface EmptyStateProps {
  text: string;
  children?: React.ReactNode;
}

export function EmptyState({ text, children }: EmptyStateProps) {
  return (
    <div className={styles.emptyState}>
      <span className={styles.icon}>
        <PackageOpen size={32} aria-hidden="true" />
      </span>
      <span className={styles.text}>{text}</span>
      {children}
    </div>
  );
}
