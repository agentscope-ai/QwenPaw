import { Tabs, type TabsProps } from "@agentscope-ai/design";
import { LayoutGrid, List } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import styles from "./PluginViewToggle.module.less";

export type PluginViewMode = "card" | "list";

interface PluginViewToggleProps {
  value: PluginViewMode;
  onChange: (value: PluginViewMode) => void;
}

export function PluginViewToggle({ value, onChange }: PluginViewToggleProps) {
  const { t } = useTranslation();
  const items: TabsProps["items"] = [
    {
      key: "list",
      label: (
        <Tooltip title={t("skills.listView")}>
          <span className={styles.viewIcon} aria-label={t("skills.listView")}>
            <List size={15} />
          </span>
        </Tooltip>
      ),
    },
    {
      key: "card",
      label: (
        <Tooltip title={t("skills.gridView")}>
          <span className={styles.viewIcon} aria-label={t("skills.gridView")}>
            <LayoutGrid size={15} />
          </span>
        </Tooltip>
      ),
    },
  ];

  return (
    <div
      className={styles.viewToggleWrap}
      role="group"
      aria-label={`${t("skills.listView")} / ${t("skills.gridView")}`}
    >
      <Tabs
        className={styles.viewToggle}
        activeKey={value}
        items={items}
        onChange={(key) => onChange(key as PluginViewMode)}
        type="segmented"
      />
    </div>
  );
}
