import styles from "../../index.module.less";

interface PageHeaderProps {
  parent?: string;
  current?: string;
  className?: string;
}

export function PageHeader({ parent, current, className }: PageHeaderProps) {
  return (
    <div className={`${styles.pageHeader} ${className ?? ""}`}>
      <div className={styles.breadcrumbHeader}>
        {parent && <span className={styles.breadcrumbParent}>{parent}</span>}
        {parent && current && (
          <span className={styles.breadcrumbSeparator}>/</span>
        )}
        {current && <span className={styles.breadcrumbCurrent}>{current}</span>}
      </div>
    </div>
  );
}
