import React from "react";
import { PlusOutlined } from "@ant-design/icons";
import { Button, Tag } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type {
  MCPAccessEffect,
  MCPAccessPrincipalOption,
  MCPAccessRule,
  MCPToolAccessOverride,
} from "../../../../api/types";
import type { MCPAccessToolGroup } from "../accessPolicy";
import { toolRuleIdentityKey } from "../accessPolicy";
import styles from "../index.module.less";
import { MCPAccessPolicySegmented } from "./MCPAccessPolicySegmented";
import { MCPAccessRuleRows } from "./MCPAccessRuleRows";

interface MCPAccessToolPanelProps {
  groups: MCPAccessToolGroup[];
  principalOptions: MCPAccessPrincipalOption[];
  setToolDefaultEffect: (toolName: string, effect: MCPAccessEffect) => void;
  addRule: (toolName: string) => void;
  updateRule: (
    rule: MCPToolAccessOverride,
    patch: Partial<MCPAccessRule>,
  ) => void;
  setRuleEffect: (rule: MCPToolAccessOverride, effect: MCPAccessEffect) => void;
  deleteRule: (rule: MCPToolAccessOverride) => void;
  effectLabel: (effect: MCPAccessEffect) => string;
}

export const MCPAccessToolPanel: React.FC<MCPAccessToolPanelProps> = ({
  groups,
  principalOptions,
  setToolDefaultEffect,
  addRule,
  updateRule,
  setRuleEffect,
  deleteRule,
  effectLabel,
}) => {
  const { t } = useTranslation();

  return (
    <div className={styles.accessToolsPanel}>
      <div className={styles.accessSectionHeader}>
        <div className={styles.accessSectionTitle}>
          {t("mcp.access.toolSection")}
        </div>
      </div>
      <div className={styles.accessToolGroups}>
        {groups.map((group) => (
          <div key={group.toolName} className={styles.accessToolGroup}>
            <div className={styles.accessToolGroupHeader}>
              <div className={styles.accessToolInfo}>
                <div className={styles.accessToolTitle}>
                  <Tag color={group.stale ? "default" : "blue"}>
                    {group.toolName}
                  </Tag>
                  {group.stale && (
                    <Tag color="orange">{t("mcp.access.stale")}</Tag>
                  )}
                </div>
              </div>
              <div className={styles.accessToolDefault}>
                <span className={styles.accessDefaultLabel}>
                  {t("mcp.access.default")}
                </span>
                <MCPAccessPolicySegmented
                  value={group.defaultEffect}
                  onChange={(effect) =>
                    setToolDefaultEffect(group.toolName, effect)
                  }
                  effectLabel={effectLabel}
                />
              </div>
              <Button
                className={styles.accessToolAddButton}
                icon={<PlusOutlined />}
                onClick={() => addRule(group.toolName)}
              >
                {t("mcp.access.addRule")}
              </Button>
            </div>

            {(group.description ||
              (group.inputSchema &&
                Object.keys(group.inputSchema).length > 0)) && (
              <details className={styles.toolSchema}>
                <summary>{t("mcp.toolSchema")}</summary>
                {group.description && (
                  <div className={styles.toolSchemaDescription}>
                    {group.description}
                  </div>
                )}
                {group.inputSchema &&
                  Object.keys(group.inputSchema).length > 0 && (
                    <pre className={styles.toolSchemaContent}>
                      {JSON.stringify(group.inputSchema, null, 2)}
                    </pre>
                  )}
              </details>
            )}

            <MCPAccessRuleRows
              rules={group.rules}
              principalOptions={principalOptions}
              getKey={toolRuleIdentityKey}
              updateRule={updateRule}
              setRuleEffect={setRuleEffect}
              deleteRule={deleteRule}
              emptyText={t("mcp.access.noRules")}
              effectLabel={effectLabel}
            />
          </div>
        ))}
      </div>
    </div>
  );
};
