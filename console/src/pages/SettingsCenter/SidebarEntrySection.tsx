import { Button, Checkbox } from "antd";
import type { ReactNode } from "react";

import type { FlatMenuEntry } from "@/layouts/registry/adapter";
import { useSidebarStore } from "@/stores/sidebarStore";
import styles from "./index.module.less";

interface SidebarEntrySectionProps {
  entries: FlatMenuEntry[];
  invertLabel: ReactNode;
  label: ReactNode;
  selectAllLabel: ReactNode;
}

export default function SidebarEntrySection({
  entries,
  invertLabel,
  label,
  selectAllLabel,
}: SidebarEntrySectionProps) {
  const {
    focusItemIds,
    hiddenPluginItemIds,
    setSidebarItemVisible,
    setSidebarItemsVisible,
    invertSidebarItems,
  } = useSidebarStore();
  const itemIds = entries.map((entry) => entry.key);
  const isItemVisible = (itemId: string) =>
    itemId.startsWith("core.")
      ? focusItemIds.includes(itemId)
      : !hiddenPluginItemIds.includes(itemId);
  const allItemsSelected = itemIds.every(isItemVisible);

  return (
    <section className={styles.settingsSection}>
      <div className={styles.sectionTitleRow}>
        <h3 className={styles.sectionTitle}>{label}</h3>
        <div className={styles.sectionActions}>
          <Button
            type="text"
            size="small"
            disabled={allItemsSelected}
            onClick={() => setSidebarItemsVisible(itemIds, true)}
          >
            {selectAllLabel}
          </Button>
          <Button
            type="text"
            size="small"
            onClick={() => invertSidebarItems(itemIds)}
          >
            {invertLabel}
          </Button>
        </div>
      </div>
      <div className={styles.settingsCard}>
        <div className={styles.itemGrid}>
          {entries.map((entry) => (
            <label key={entry.key} className={styles.itemOption}>
              <Checkbox
                checked={isItemVisible(entry.key)}
                onChange={(event) =>
                  setSidebarItemVisible(entry.key, event.target.checked)
                }
              />
              <span className={styles.itemIcon}>{entry.icon}</span>
              <span>{entry.label}</span>
            </label>
          ))}
        </div>
      </div>
    </section>
  );
}
