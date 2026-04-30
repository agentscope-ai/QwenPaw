import { Form, Switch, Button, Card, Select } from "@agentscope-ai/design";
import { PlusCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { MergedRule } from "../useToolGuard";
import type { ToolGuardConfig } from "../../../../api/modules/security";
import type { FormInstance } from "antd";
import { RuleTable, ShellEvasionSection } from "./index";
import styles from "../index.module.less";

interface ToolGuardTabProps {
  form: FormInstance;
  config: ToolGuardConfig | null;
  enabled: boolean;
  setEnabled: (val: boolean) => void;
  toolOptions: { label: string; value: string }[];
  mergedRules: MergedRule[];
  toggleRule: (ruleId: string, currentlyDisabled: boolean) => void;
  onPreviewRule: (rule: MergedRule) => void;
  onEditRule: (rule: MergedRule) => void;
  onDeleteRule: (ruleId: string) => void;
  openAddRule: () => void;
  shellEvasionChecks: Record<string, boolean>;
  toggleShellEvasionCheck: (checkName: string, checked: boolean) => void;
}

export function ToolGuardTab({
  form,
  config,
  enabled,
  setEnabled,
  toolOptions,
  mergedRules,
  toggleRule,
  onPreviewRule,
  onEditRule,
  onDeleteRule,
  openAddRule,
  shellEvasionChecks,
  toggleShellEvasionCheck,
}: ToolGuardTabProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.tabContent}>
      <div className={styles.sectionConfigureContainer}>
        <p className={styles.tabDescription}>
          {t("security.toolGuardDescription")}
        </p>

        <Card className={styles.formCard}>
          <Form
            form={form}
            layout="vertical"
            className={styles.form}
            initialValues={{
              enabled: config?.enabled ?? true,
              guarded_tools: config?.guarded_tools ?? [],
              denied_tools: config?.denied_tools ?? [],
            }}
          >
            <Form.Item
              label={t("security.enabled")}
              name="enabled"
              valuePropName="checked"
              tooltip={t("security.enabledTooltip")}
            >
              <Switch onChange={(val) => setEnabled(val)} />
            </Form.Item>
            <div className={styles.toolGuardRow}>
              <Form.Item
                label={t("security.guardedTools")}
                name="guarded_tools"
                tooltip={t("security.guardedToolsTooltip")}
                style={{ marginBottom: 0 }}
              >
                <Select
                  mode="tags"
                  options={toolOptions}
                  placeholder={t("security.guardedToolsPlaceholder")}
                  disabled={!enabled}
                  allowClear
                  style={{ width: "100%" }}
                />
              </Form.Item>

              <Form.Item
                label={t("security.deniedTools")}
                name="denied_tools"
                tooltip={t("security.deniedToolsTooltip")}
                style={{ marginBottom: 0 }}
              >
                <Select
                  mode="tags"
                  options={toolOptions}
                  placeholder={t("security.deniedToolsPlaceholder")}
                  disabled={!enabled}
                  allowClear
                  style={{ width: "100%" }}
                />
              </Form.Item>
            </div>
          </Form>
        </Card>
      </div>

      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>{t("security.rules.title")}</h2>
          <Button
            type="primary"
            icon={<PlusCircleOutlined />}
            onClick={openAddRule}
            disabled={!enabled}
            size="middle"
          >
            {t("security.rules.add")}
          </Button>
        </div>

        <Card className={styles.tableCard}>
          <RuleTable
            rules={mergedRules}
            enabled={enabled}
            onToggleRule={toggleRule}
            onPreviewRule={onPreviewRule}
            onEditRule={onEditRule}
            onDeleteRule={onDeleteRule}
          />
        </Card>
      </div>

      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            {t("security.shellEvasion.title")}
          </h2>
        </div>
        <div className={styles.sectionConfigureContainer}>
          <p className={styles.tabDescription}>
            {t("security.shellEvasion.description")}
          </p>
          <ShellEvasionSection
            checks={shellEvasionChecks}
            onToggle={toggleShellEvasionCheck}
            disabled={!enabled}
          />
        </div>
      </div>
    </div>
  );
}
