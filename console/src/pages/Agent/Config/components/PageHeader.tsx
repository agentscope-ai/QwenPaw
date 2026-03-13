import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function PageHeader() {
  const { t } = useTranslation();
  return (
    <div className={styles.header}>
      <div>
        <h1 className={styles.title}>{t("agentConfig.title")}</h1>
        <p className={styles.description}>{t("agentConfig.description")}</p>
      </div>
    </div>
  );
}
