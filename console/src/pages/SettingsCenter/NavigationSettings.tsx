import { Button, Checkbox, Tag } from "antd";
import { RotateCcw } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { flattenMenu } from "@/layouts/registry/adapter";
import { filterMenuForAgentCapabilities } from "@/layouts/registry/capabilities";
import { partitionSidebarEntries } from "@/layouts/registry/sidebarEntries";
import { useMenuItems, useRoutes } from "@/plugins/registry/hooks";
import { useAgentStore } from "@/stores/agentStore";
import { useSidebarModeStore } from "@/stores/sidebarModeStore";
import styles from "./index.module.less";

export default function NavigationSettings() {
  const { t } = useTranslation();
  const routes = useRoutes();
  const rawAgentMenu = useMenuItems("primary.agentScoped");
  const rawSettingsMenu = useMenuItems("primary.settings");
  const { selectedAgent, agents } = useAgentStore();
  const currentAgent = agents.find((agent) => agent.id === selectedAgent);
  const {
    focusItemIds,
    hiddenPluginItemIds,
    setSidebarItemVisible,
    setSidebarItemsVisible,
    invertSidebarItems,
    resetFocusItemIds,
  } = useSidebarModeStore();

  const entryGroups = useMemo(() => {
    const capabilities = currentAgent
      ? {
          ...currentAgent.backend_capabilities,
          workspace_ui:
            currentAgent.backend === "qwenpaw"
              ? currentAgent.backend_capabilities?.workspace_ui ?? true
              : false,
        }
      : undefined;
    return partitionSidebarEntries(
      flattenMenu(
        filterMenuForAgentCapabilities(rawAgentMenu, capabilities),
        routes,
        18,
      ),
      flattenMenu(rawSettingsMenu, routes, 18),
    );
  }, [currentAgent, rawAgentMenu, rawSettingsMenu, routes]);

  const configurableGroups = [
    {
      key: "work",
      label: t("settingsCenter.sidebarGroups.work", "Work shortcuts"),
      entries: entryGroups.work,
    },
    {
      key: "global",
      label: t("settingsCenter.sidebarGroups.global", "Global settings"),
      entries: entryGroups.global,
    },
    {
      key: "plugins",
      label: t("settingsCenter.sidebarGroups.plugins", "Plugin shortcuts"),
      entries: entryGroups.plugins,
    },
  ].filter((group) => group.entries.length > 0);

  const isItemVisible = (itemId: string) =>
    itemId.startsWith("core.")
      ? focusItemIds.includes(itemId)
      : !hiddenPluginItemIds.includes(itemId);
  return (
    <div className={styles.preferencePage}>
      <div className={styles.pageTitle}>
        <h2>{t("settingsCenter.pages.navigation", "Sidebar")}</h2>
        <p>
          {t(
            "settingsCenter.navigationDescription",
            "Choose which shortcuts are shown in the sidebar.",
          )}
        </p>
      </div>

      <section className={styles.settingsCard}>
        <div className={styles.cardHeading}>
          <div>
            <h3>{t("settingsCenter.visibleItems", "Sidebar shortcuts")}</h3>
            <p>
              {t(
                "settingsCenter.visibleItemsHint",
                "Selected shortcuts are shown directly. Hidden items remain available here and keep their routes and data.",
              )}
            </p>
          </div>
          <Button icon={<RotateCcw size={15} />} onClick={resetFocusItemIds}>
            {t("common.reset")}
          </Button>
        </div>

        <div className={styles.fixedItem}>
          <Checkbox checked disabled>
            {t("nav.inbox")}
          </Checkbox>
          <Tag>{t("settingsCenter.alwaysVisible", "Always visible")}</Tag>
        </div>
        {configurableGroups.map((group) => {
          const groupItemIds = group.entries.map((entry) => entry.key);
          const allGroupItemsSelected = groupItemIds.every(isItemVisible);
          return (
            <section key={group.key} className={styles.itemSection}>
              <div className={styles.itemSectionHeading}>
                <h4>{group.label}</h4>
                <div className={styles.sectionActions}>
                  <Button
                    type="text"
                    size="small"
                    disabled={allGroupItemsSelected}
                    onClick={() => setSidebarItemsVisible(groupItemIds, true)}
                  >
                    {t("settingsCenter.selectAll", "Select all")}
                  </Button>
                  <Button
                    type="text"
                    size="small"
                    onClick={() => invertSidebarItems(groupItemIds)}
                  >
                    {t("settingsCenter.invertSelection", "Invert")}
                  </Button>
                </div>
              </div>
              <div className={styles.itemGrid}>
                {group.entries.map((entry) => (
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
            </section>
          );
        })}
      </section>
    </div>
  );
}
