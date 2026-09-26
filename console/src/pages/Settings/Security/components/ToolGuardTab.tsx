import InlineHelp from "@/components/InlineHelp";
import { SettingsField } from "@/components/interaction/SettingsField";
import {
  Form,
  Switch,
  Button,
  Card,
  Select,
  Alert,
} from "@agentscope-ai/design";
import { CirclePlus as PlusCircleOutlined } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MergedRule } from "../useToolGuard";
import type { ToolGuardConfig } from "../../../../api/modules/security";
import type { FormInstance } from "antd";
import { RuleTable, ShellEvasionSection } from "./index";
import styles from "../index.module.less";

interface ToolGuardTabProps {
  onValuesChange?: () => void;
  form: FormInstance;
  config: ToolGuardConfig | null;
  enabled: boolean;
  setEnabled: (val: boolean) => void;
  sandboxEnabled: boolean;
  setSandboxEnabled: (val: boolean) => void;
  sandboxReason: string | null;
  toolOptions: { label: string; value: string }[];
  mergedRules: MergedRule[];
  toggleRule: (ruleId: string, currentlyDisabled: boolean) => void;
  toggleAutoDeny: (ruleId: string, currentlyAutoDeny: boolean) => void;
  onPreviewRule: (rule: MergedRule) => void;
  onEditRule: (rule: MergedRule) => void;
  onDeleteRule: (ruleId: string) => void;
  openAddRule: () => void;
  shellEvasionChecks: Record<string, boolean>;
  toggleShellEvasionCheck: (checkName: string, checked: boolean) => void;
}

export function ToolGuardTab({
  form,
  onValuesChange,
  config,
  enabled,
  setEnabled,
  sandboxEnabled,
  setSandboxEnabled,
  sandboxReason,
  toolOptions,
  mergedRules,
  toggleRule,
  toggleAutoDeny,
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
        <Card className={styles.formCard}>
          <Form
            onValuesChange={onValuesChange}
            form={form}
            layout="vertical"
            className={styles.form}
            initialValues={{
              enabled: config?.enabled ?? true,
              guarded_tools: config?.guarded_tools ?? [],
              denied_tools: config?.denied_tools ?? [],
            }}
          >
            <SettingsField
              label={t("security.enabled")}
              name="enabled"
              valuePropName="checked"
              tooltip={t("security.enabledTooltip")}
            >
              <Switch onChange={(val) => setEnabled(val)} />
            </SettingsField>
            <SettingsField
              label={t("security.sandboxEnabled")}
              valuePropName="checked"
              tooltip={t("security.sandboxEnabledTooltip")}
            >
              <Switch
                checked={sandboxEnabled}
                onChange={(val) => setSandboxEnabled(val)}
              />
            </SettingsField>
            {sandboxEnabled && sandboxReason === null && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message={t("security.sandboxElevatedWarning")}
                description={t("security.sandboxElevatedDescription")}
              />
            )}
            {sandboxEnabled && sandboxReason === "unelevated" && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message={t("security.sandboxUnelevatedWarning")}
                description={t("security.sandboxUnelevatedDescription")}
              />
            )}
            <div className={styles.toolGuardRow}>
              <SettingsField
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
              </SettingsField>

              <SettingsField
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
              </SettingsField>
            </div>
          </Form>
        </Card>
      </div>

      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>{t("security.rules.title")}</h2>
          <Button
            type="primary"
            icon={<PlusCircleOutlined size="1em" />}
            onClick={openAddRule}
            disabled={!enabled}
            size="middle"
          >
            {t("security.rules.add")}
          </Button>
        </div>

        <div>
          <RuleTable
            rules={mergedRules}
            enabled={enabled}
            onToggleRule={toggleRule}
            onToggleAutoDeny={toggleAutoDeny}
            onPreviewRule={onPreviewRule}
            onEditRule={onEditRule}
            onDeleteRule={onDeleteRule}
          />
        </div>
      </div>

      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            {t("security.shellEvasion.title")}
            <InlineHelp subject={t("security.shellEvasion.title")}>
              {t("security.shellEvasion.description")}
            </InlineHelp>
          </h2>
        </div>
        <div className={styles.sectionConfigureContainer}>
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
