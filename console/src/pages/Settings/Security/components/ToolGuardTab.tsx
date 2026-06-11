import { useEffect, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { PlusCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MergedRule } from "../useToolGuard";
import type { ToolGuardConfig } from "../../../../api/modules/security";
import { RuleTable, ShellEvasionSection } from "./index";
import styles from "../index.module.less";

interface ToolSelectProps {
  label: string;
  tooltip?: string;
  value: string[];
  onChange: (val: string[]) => void;
  options: { label: string; value: string }[];
  disabled?: boolean;
  placeholder?: string;
  listId: string;
}

function ToolSelect({
  label,
  tooltip,
  value,
  onChange,
  options,
  disabled,
  placeholder,
  listId,
}: ToolSelectProps) {
  const [inp, setInp] = useState("");

  const add = (val: string) => {
    const trimmed = val.trim();
    if (trimmed && !value.includes(trimmed)) onChange([...value, trimmed]);
    setInp("");
  };
  const remove = (v: string) => onChange(value.filter((x) => x !== v));

  return (
    <div className="flex flex-col gap-1 flex-1">
      <div className="flex items-center gap-1">
        <Label>{label}</Label>
        {tooltip && (
          <span
            className="text-xs text-muted-foreground cursor-help"
            title={tooltip}
          >
            ?
          </span>
        )}
      </div>
      <div
        className={`flex flex-wrap gap-1 min-h-[36px] border rounded-md px-2 py-1 focus-within:ring-1 focus-within:ring-ring ${
          disabled ? "opacity-50 pointer-events-none bg-muted" : ""
        }`}
      >
        {value.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 bg-secondary text-secondary-foreground text-xs rounded px-2 py-0.5"
          >
            {v}
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground leading-none"
              onClick={() => remove(v)}
            >
              ×
            </button>
          </span>
        ))}
        <input
          className="flex-1 min-w-[100px] outline-none text-sm bg-transparent"
          placeholder={placeholder}
          value={inp}
          disabled={disabled}
          list={listId}
          onChange={(e) => setInp(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(inp);
            } else if (e.key === "Backspace" && !inp && value.length > 0) {
              remove(value[value.length - 1]);
            }
          }}
        />
        <datalist id={listId}>
          {options.map((o) => (
            <option key={o.value} value={o.value} />
          ))}
        </datalist>
      </div>
    </div>
  );
}

interface ToolGuardTabProps {
  config: ToolGuardConfig | null;
  enabled: boolean;
  setEnabled: (val: boolean) => void;
  formEnabled: boolean;
  setFormEnabled: (val: boolean) => void;
  formGuardedTools: string[];
  setFormGuardedTools: (val: string[]) => void;
  formDeniedTools: string[];
  setFormDeniedTools: (val: string[]) => void;
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
  config,
  enabled,
  setEnabled,
  formEnabled,
  setFormEnabled,
  formGuardedTools,
  setFormGuardedTools,
  formDeniedTools,
  setFormDeniedTools,
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

  // Sync config into form state on load
  useEffect(() => {
    if (config) {
      setFormEnabled(config.enabled ?? true);
      setFormGuardedTools(config.guarded_tools ?? []);
      setFormDeniedTools(config.denied_tools ?? []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  return (
    <div className={styles.tabContent}>
      <div className={styles.sectionConfigureContainer}>
        <p className={styles.tabDescription}>
          {t("security.toolGuardDescription")}
        </p>

        <div
          className={`${styles.formCard} border rounded-lg p-4 flex flex-col gap-4`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Label>{t("security.enabled")}</Label>
              <span
                className="text-xs text-muted-foreground cursor-help"
                title={t("security.enabledTooltip")}
              >
                ?
              </span>
            </div>
            <Switch
              checked={formEnabled}
              onCheckedChange={(val) => {
                setFormEnabled(val);
                setEnabled(val);
              }}
            />
          </div>

          <div className={styles.toolGuardRow}>
            <ToolSelect
              label={t("security.guardedTools")}
              tooltip={t("security.guardedToolsTooltip")}
              value={formGuardedTools}
              onChange={setFormGuardedTools}
              options={toolOptions}
              disabled={!formEnabled}
              placeholder={t("security.guardedToolsPlaceholder")}
              listId="guarded-tool-options"
            />
            <ToolSelect
              label={t("security.deniedTools")}
              tooltip={t("security.deniedToolsTooltip")}
              value={formDeniedTools}
              onChange={setFormDeniedTools}
              options={toolOptions}
              disabled={!formEnabled}
              placeholder={t("security.deniedToolsPlaceholder")}
              listId="denied-tool-options"
            />
          </div>
        </div>
      </div>

      <div className={styles.sectionContainer}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>{t("security.rules.title")}</h2>
          <Button onClick={openAddRule} disabled={!enabled} size="sm">
            <PlusCircle size={16} className="mr-2" />
            {t("security.rules.add")}
          </Button>
        </div>

        <div className={`${styles.tableCard} border rounded-lg p-2`}>
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
