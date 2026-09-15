import { useState } from "react";
import { Modal } from "antd";
import { Network } from "lucide-react";
import type { ProviderInfo } from "../../../../../api/types";
import MemberModels from "../../../../Hub/governance/MemberModels";
import { useGovernanceText } from "../../../../Hub/governance/shared";
import governanceStyles from "../../../../Hub/governance/governance.module.less";
import styles from "../../index.module.less";

export function HubProviderCard({
  provider,
  onSaved,
}: {
  provider: ProviderInfo;
  onSaved: () => void;
}) {
  const text = useGovernanceText();
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className={styles.groupCardGlass}>
        <div className={styles.groupCardHeader}>
          <Network size={36} strokeWidth={1.5} />
          <span className={styles.groupCardName}>Hub</span>
          <span className={styles.customTag}>
            {text("组织提供", "Organization")}
          </span>
          {provider.models.length > 0 && (
            <div className={styles.groupCardLiveBadge}>
              <span className={styles.groupCardPulse} />
              Live
            </div>
          )}
        </div>
        <div className={styles.groupCardContent}>
          <div className={styles.groupCardField}>
            <span className={styles.groupCardFieldLabel}>
              {text("连接", "Connection")}
            </span>
            <span className={styles.groupCardFieldValue}>
              {text(
                "由组织管理，无需配置密钥",
                "Managed by your organization. No key setup needed.",
              )}
            </span>
          </div>
          <div className={styles.groupCardField}>
            <span className={styles.groupCardFieldLabel}>
              {text("可用模型", "Models")}
            </span>
            <span className={styles.groupCardFieldValue}>
              {provider.models.length
                ? provider.models.map((model) => model.name).join(" · ")
                : text(
                    "等待管理员发布模型并授权",
                    "Waiting for your administrator to publish models and grant access",
                  )}
            </span>
          </div>
          <div className={styles.groupCardField}>
            <span className={styles.groupCardFieldLabel}>
              {text("用量", "Usage")}
            </span>
            <span className={styles.groupCardFieldValue}>
              {text(
                "仅统计通过 Hub 调用的模型",
                "Only calls through Hub count toward its budget",
              )}
            </span>
          </div>
        </div>
        <div className={styles.groupCardActions}>
          <button
            className={styles.groupCardActBtn}
            onClick={() => setOpen(true)}
          >
            {text("模型与额度", "Models and budget")}
          </button>
          <button className={styles.groupCardActBtn} onClick={onSaved}>
            {text("刷新", "Refresh")}
          </button>
        </div>
      </div>
      <Modal
        title={text("Hub 模型与额度", "Hub models and budget")}
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
