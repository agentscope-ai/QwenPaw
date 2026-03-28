import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function PageHeader() {
  const { t } = useTranslation();
  return (
    <div className={styles.pageHeader}>
      <div className={styles.breadcrumbHeader}>
        <span className={styles.breadcrumbParent}>Agent</span>
        <span className={styles.breadcrumbSeparator}>/</span>
        <span className={styles.breadcrumbCurrent}>
          {t("agentConfig.title")}
        </span>
      </div>
    </div>
  );
}
