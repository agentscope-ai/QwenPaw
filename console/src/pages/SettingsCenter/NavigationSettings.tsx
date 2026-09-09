import { Button, Checkbox, Tag } from "antd";
import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSidebarStore } from "@/stores/sidebarStore";
import SidebarEntrySection from "./SidebarEntrySection";
import { useSidebarEntryGroups } from "./useSidebarEntryGroups";
import styles from "./index.module.less";

export default function NavigationSettings() {
  const { t } = useTranslation();
  const { work, global, plugins } = useSidebarEntryGroups();
  const { resetFocusItemIds } = useSidebarStore();

  const configurableGroups = [
    {
      key: "work",
      label: t(
        "settingsCenter.sidebarGroups.agentConfiguration",
        "Agent configuration",
      ),
      entries: work,
    },
    {
      key: "global",
      label: t("settingsCenter.sidebarGroups.global", "Global settings"),
      entries: global,
    },
    {
      key: "plugins",
      label: t("settingsCenter.sidebarGroups.plugins", "Plugin features"),
      entries: plugins,
    },
  ].filter((group) => group.entries.length > 0);
  return (
    <div className={styles.preferencePage}>
      <div className={`${styles.pageTitle} ${styles.pageTitleRow}`}>
        <h2>{t("settingsCenter.pages.navigation", "Sidebar")}</h2>
        <Button icon={<RotateCcw size={15} />} onClick={resetFocusItemIds}>
          {t("common.reset")}
        </Button>
      </div>

      <section className={styles.settingsSection}>
        <h3 className={styles.sectionTitle}>
          {t("settingsCenter.fixedEntries", "Fixed entries")}
        </h3>
        <div className={styles.settingsCard}>
          <div className={styles.fixedItem}>
            <div className={styles.fixedEntryList}>
              <Checkbox checked disabled>
                {t("nav.inbox")}
              </Checkbox>
              <Checkbox checked disabled>
                {t("nav.marketplace")}
              </Checkbox>
            </div>
            <Tag>{t("settingsCenter.alwaysVisible", "Always visible")}</Tag>
          </div>
        </div>
      </section>

      {configurableGroups.map((group) => {
        return (
          <SidebarEntrySection
            key={group.key}
            entries={group.entries}
            label={group.label}
            selectAllLabel={t("settingsCenter.selectAll")}
            invertLabel={t("settingsCenter.invertSelection")}
          />
        );
      })}
    </div>
  );
}
