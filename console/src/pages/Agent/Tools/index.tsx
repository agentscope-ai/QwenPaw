import { useState, useMemo } from "react";
import { Card, Switch, Empty } from "@agentscope-ai/design";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import styles from "./index.module.less";

export default function ToolsPage() {
  const { t } = useTranslation();
  const {
    tools,
    loading,
    batchLoading,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
  } = useTools();
  const [hoverKey, setHoverKey] = useState<string | null>(null);

  const handleToggle = (tool: ToolInfo) => {
    toggleEnabled(tool);
  };

  const hasDisabledTools = useMemo(
    () => tools.some((tool) => !tool.enabled),
    [tools],
  );
  const hasEnabledTools = useMemo(
    () => tools.some((tool) => tool.enabled),
    [tools],
  );

  return (
    <div className={styles.toolsPage}>
      <div className={styles.pageHeader}>
        <div className={styles.breadcrumbHeader}>
          <span className={styles.breadcrumbParent}>Agent</span>
          <span className={styles.breadcrumbSeparator}>/</span>
          <span className={styles.breadcrumbCurrent}>{t("tools.title")}</span>
        </div>
        <div className={styles.headerAction}>
          <Switch
            checked={hasEnabledTools && !hasDisabledTools}
            onChange={() => (hasDisabledTools ? enableAll() : disableAll())}
            disabled={batchLoading || loading}
            checkedChildren={t("tools.enableAll")}
            unCheckedChildren={t("tools.disableAll")}
          />
        </div>
      </div>
      <div className={styles.toolsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <p>{t("common.loading")}</p>
          </div>
        ) : tools.length === 0 ? (
          <Empty description={t("tools.emptyState")} />
        ) : (
          <div className={styles.toolsGrid}>
            {tools.map((tool) => (
              <Card
                key={tool.name}
                className={`${styles.toolCard} ${
                  tool.enabled ? styles.enabledCard : ""
                } ${
                  hoverKey === tool.name ? styles.hoverCard : styles.normalCard
                }`}
                onMouseEnter={() => setHoverKey(tool.name)}
                onMouseLeave={() => setHoverKey(null)}
              >
                <div className={styles.cardHeader}>
                  <h3 className={styles.toolName}>{tool.name}</h3>
                  <div className={styles.statusContainer}>
                    <span className={styles.statusDot} />
                    <span className={styles.statusText}>
                      {tool.enabled
                        ? t("common.enabled")
                        : t("common.disabled")}
                    </span>
                  </div>
                </div>

                <p className={styles.toolDescription}>{tool.description}</p>

                <div className={styles.cardFooter}>
                  {tool.name === "execute_shell_command" && (
                    <div className={styles.inlineSettingItem}>
                      <span className={styles.settingLabel}>
                        {t("tools.asyncExecution")}
                      </span>
                      <Switch
                        checked={tool.async_execution}
                        onChange={() => toggleAsyncExecution(tool)}
                        disabled={!tool.enabled}
                      />
                    </div>
                  )}
                  <Switch
                    checked={tool.enabled}
                    onChange={() => handleToggle(tool)}
                  />
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
