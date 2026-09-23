import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";
import { OffloadPolicyCard } from "./OffloadPolicyCard";

export default function OffloadPolicyPage() {
  const { t } = useTranslation();

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.offloadPolicy", "Tool Offload")}
      />
      <OffloadPolicyCard />
    </div>
  );
}
