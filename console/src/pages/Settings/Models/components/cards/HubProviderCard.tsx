import { useTranslation } from "react-i18next";
import { useState } from "react";
import { Modal } from "antd";
import { Network } from "lucide-react";
import type { ProviderInfo } from "../../../../../api/types";
import MemberModels from "../../../../Hub/governance/MemberModels";
import governanceStyles from "../../../../Hub/governance/governance.module.less";
import styles from "../../index.module.less";

export function HubProviderCard({
  provider,
  onSaved,
}: {
  provider: ProviderInfo;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className={styles.groupCardGlass}>
        <div className={styles.groupCardHeader}>
          <Network size={36} strokeWidth={1.5} />
          <span className={styles.groupCardName}>Hub</span>
          <span className={styles.customTag}>
            {t("hub.governance.provider.organization")}
          </span>
          {provider.models.length > 0 && (
            <div className={styles.groupCardLiveBadge}>
              <span className={styles.groupCardPulse} />
              {t("hub.runtimes.available")}
            </div>
          )}
        </div>
        <div className={styles.groupCardContent}>
          <div className={styles.groupCardField}>
            <span className={styles.groupCardFieldLabel}>
              {t("hub.governance.models.connection")}
            </span>
            <span className={styles.groupCardFieldValue}>
              {t("hub.governance.provider.managedHint")}
            </span>
          </div>
          <div className={styles.groupCardField}>
            <span className={styles.groupCardFieldLabel}>
              {t("hub.governance.models.availableModels")}
            </span>
            <span className={styles.groupCardFieldValue}>
              {provider.models.length
                ? provider.models.map((model) => model.name).join(" · ")
                : t("hub.governance.provider.waiting")}
            </span>
          </div>
          <div className={styles.groupCardField}>
            <span className={styles.groupCardFieldLabel}>
              {t("hub.governance.provider.usage")}
            </span>
            <span className={styles.groupCardFieldValue}>
              {t("hub.governance.provider.usageHint")}
            </span>
          </div>
        </div>
        <div className={styles.groupCardActions}>
          <button
            className={styles.groupCardActBtn}
            onClick={() => setOpen(true)}
          >
            {t("hub.governance.provider.modelsBudget")}
          </button>
          <button className={styles.groupCardActBtn} onClick={onSaved}>
            {t("common.refresh")}
          </button>
        </div>
      </div>
      <Modal
        title={t("hub.governance.provider.title")}
        open={open}
        centered
        width={760}
        footer={null}
        destroyOnClose
        className={governanceStyles.userModal}
        onCancel={() => {
          setOpen(false);
          onSaved();
        }}
      >
        <MemberModels />
      </Modal>
    </>
  );
}
