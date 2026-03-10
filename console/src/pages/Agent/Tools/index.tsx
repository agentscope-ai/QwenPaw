import { useState } from "react";
import { Card, Switch, Empty } from "@agentscope-ai/design";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import styles from "./index.module.less";

export default function ToolsPage() {
  const { t } = useTranslation();
  const { tools, loading, toggleEnabled } = useTools();
  const [hoverKey, setHoverKey] = useState<string | null>(null);

  const handleToggle = (tool: ToolInfo) => {
    toggleEnabled(tool);
  };

  return (
    <div className={styles.toolsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("tools.title")}</h1>
          <p className={styles.description}>{t("tools.description")}</p>
        </div>
      </div>

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
                    {tool.enabled ? t("common.enabled") : t("common.disabled")}
                  </span>
                </div>
              </div>

              <p className={styles.toolDescription}>{tool.description}</p>

              <div className={styles.cardFooter}>
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
  );
}
