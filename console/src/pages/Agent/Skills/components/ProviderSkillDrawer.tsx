import { Button, Drawer } from "@agentscope-ai/design";
import { LockKeyhole } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { HarnessDiscoveredSkill } from "../../../../api/modules/harness";
import styles from "./ProviderSkillDrawer.module.less";

interface ProviderSkillDrawerProps {
  open: boolean;
  skill: HarnessDiscoveredSkill | null;
  onClose: () => void;
}

export function ProviderSkillDrawer({
  open,
  skill,
  onClose,
}: ProviderSkillDrawerProps) {
  const { t } = useTranslation();

  return (
    <Drawer
      width={480}
      placement="right"
      title={t("skills.providerSkillDetails")}
      open={open}
      onClose={onClose}
      destroyOnHidden
      footer={
        <div className={styles.footer}>
          <Button onClick={onClose}>{t("common.close")}</Button>
        </div>
      }
    >
      {skill && (
        <div className={styles.content}>
          <div className={styles.header}>
            <span className={styles.icon}>
              <LockKeyhole size={20} />
            </span>
            <div>
              <h2>{skill.name}</h2>
              <span className={styles.readOnlyBadge}>
                {t("skills.readOnly")}
              </span>
            </div>
          </div>

          <p className={styles.notice}>
            {t("skills.providerManagedDetailHint")}
          </p>

          <dl className={styles.details}>
            <div>
              <dt>{t("skills.provider")}</dt>
              <dd>{skill.provider_id}</dd>
            </div>
            <div>
              <dt>{t("skills.source")}</dt>
              <dd>{skill.source || "—"}</dd>
            </div>
            <div>
              <dt>{t("skills.scope")}</dt>
              <dd>{t("skills.providerOnly")}</dd>
            </div>
            <div>
              <dt>{t("skills.statusLabel")}</dt>
              <dd className={skill.enabled ? styles.enabled : styles.disabled}>
                {skill.enabled ? t("common.enabled") : t("common.disabled")}
              </dd>
            </div>
          </dl>

          <section className={styles.description}>
            <h3>{t("skills.descriptionLabel")}</h3>
            <p>{skill.description || t("skills.noDescription")}</p>
          </section>
        </div>
      )}
    </Drawer>
  );
}
