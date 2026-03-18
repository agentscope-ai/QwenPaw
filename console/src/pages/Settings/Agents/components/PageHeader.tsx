import styles from "../index.module.less";

interface PageHeaderProps {
  title: string;
  description?: string;
  className?: string;
  action?: React.ReactNode;
}

export function PageHeader({
  title,
  description,
  className,
  action,
}: PageHeaderProps) {
  return (
    <section className={`${styles.section} ${className ?? ""}`}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h2 className={styles.sectionTitle}>{title}</h2>
        </div>
        {description && <p className={styles.sectionDesc}>{description}</p>}
      </div>
      {action && <div className={styles.sectionAction}>{action}</div>}
    </section>
  );
}
