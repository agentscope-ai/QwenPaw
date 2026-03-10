import { Card, Switch, Empty } from "@agentscope-ai/design";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import styles from "./index.module.less";

export default function ToolsPage() {
  const { t } = useTranslation();
  const { tools, loading, toggleEnabled } = useTools();

  const handleToggle = (tool: ToolInfo) => {
    toggleEnabled(tool);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
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
            <Card key={tool.name} className={styles.toolCard}>
              <div className={styles.cardHeader}>
                <h3 className={styles.toolName}>{tool.name}</h3>
                <Switch
                  checked={tool.enabled}
                  onChange={() => handleToggle(tool)}
                />
              </div>
              <p className={styles.toolDescription}>{tool.description}</p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
