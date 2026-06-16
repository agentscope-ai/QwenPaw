import {
  FileBaselineProtectionFileList,
  FileBaselineProtectionSwitchRow,
} from "@extension/file_baseline";
import { IntegrityProtectionFrame } from "@extension/file_baseline/components/IntegrityProtectionFrame";
import { RuleIntegrityPassiveCard } from "@extension/rule_integrity";
import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

function IntegrityProtectionDeliverySection() {
  const { t } = useTranslation();

  return (
    <div className={styles.sectionFileGuardContainer}>
      <Card className={styles.formCard}>
        <FileBaselineProtectionSwitchRow />
        <p className={styles.tabDescription}>
          {t("security.integrityProtection.defaultOffNotice")}
        </p>
        <FileBaselineProtectionFileList />
      </Card>

      <RuleIntegrityPassiveCard />
    </div>
  );
}

export function IntegrityProtectionSection() {
  return (
    <IntegrityProtectionFrame>
      {() => <IntegrityProtectionDeliverySection />}
    </IntegrityProtectionFrame>
  );
}
