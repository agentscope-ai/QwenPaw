import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface PageHeaderProps {
  className?: string;
}

export function PageHeader({ className }: PageHeaderProps) {
  const { t } = useTranslation();

  return (
    <div className={`${styles.header} ${className || ""}`}>
      <h1 className={styles.title}>{t("security.title")}</h1>
      <p className={styles.description}>{t("security.description")}</p>
    </div>
  );
}
