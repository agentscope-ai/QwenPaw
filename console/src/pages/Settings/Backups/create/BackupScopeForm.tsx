/**
 * Controlled form section for choosing what to include in a backup.
 * Handles the full/partial radio toggle and the four partial-mode checkboxes
 * (agents, global config, skill pool, secrets). Extracted from CreateBackupModal
 * so it can be unit-tested and potentially reused independently.
 */
import { useTranslation } from "react-i18next";
import type { AgentSummary } from "@/api/types/agents";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import AgentMultiSelect from "./AgentMultiSelect";
import styles from "./BackupScopeForm.module.less";

export interface ScopeFormValue {
  backupMode: "full" | "partial";
  selectedAgents: string[];
  globalConfig: boolean;
  includeSkillPool: boolean;
  includeSecrets: boolean;
}

interface Props {
  value: ScopeFormValue;
  onChange: (next: ScopeFormValue) => void;
  agents: AgentSummary[];
}

/**
 * Full/partial backup mode selector plus scope checkboxes.
 * Extracted from CreateBackupModal so it can be tested and reused independently.
 */
export default function BackupScopeForm({ value, onChange, agents }: Props) {
  const { t } = useTranslation();

  /** Shallow-merges a partial update into the current form value. */
  const set = (partial: Partial<ScopeFormValue>) =>
    onChange({ ...value, ...partial });

  return (
    <div className={styles.form}>
      <div className={styles.section}>
        <div className={styles.sectionLabel}>{t("backup.backupMode")}</div>
        <div className={`${styles.radioGroup} flex flex-col gap-3`}>
          {(["full", "partial"] as const).map((mode) => (
            <label key={mode} className="flex cursor-pointer items-start gap-2">
              <input
                type="radio"
                name="backupMode"
                value={mode}
                checked={value.backupMode === mode}
                onChange={() => set({ backupMode: mode })}
                className="mt-1 accent-primary"
              />
              <span>
                <strong>
                  {mode === "full"
                    ? t("backup.fullBackup")
                    : t("backup.partialBackup")}
                </strong>
                <div className={styles.radioDesc}>
                  {mode === "full"
                    ? t("backup.fullBackupDesc")
                    : t("backup.partialBackupDesc")}
                </div>
              </span>
            </label>
          ))}
        </div>
      </div>

      {value.backupMode === "partial" && (
        <div className={styles.partialOptions}>
          <div className="flex items-center gap-2">
            <Checkbox
              id="scope-agents"
              checked={value.selectedAgents.length > 0}
              onCheckedChange={(checked) => {
                set({
                  selectedAgents: checked ? agents.map((a) => a.id) : [],
                });
              }}
            />
            <Label htmlFor="scope-agents" className="cursor-pointer">
              {t("backup.scopeAgents")}
            </Label>
          </div>

          {value.selectedAgents.length > 0 && (
            <div className={styles.agentSelect}>
              <AgentMultiSelect
                agents={agents}
                value={value.selectedAgents}
                onChange={(ids) => set({ selectedAgents: ids })}
              />
            </div>
          )}

          <div className="flex items-center gap-2">
            <Checkbox
              id="scope-global-config"
              checked={value.globalConfig}
              onCheckedChange={(checked) => set({ globalConfig: !!checked })}
            />
            <Label htmlFor="scope-global-config" className="cursor-pointer">
              {t("backup.scopeGlobalConfig")}
            </Label>
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="scope-skill-pool"
              checked={value.includeSkillPool}
              onCheckedChange={(checked) =>
                set({ includeSkillPool: !!checked })
              }
            />
            <Label htmlFor="scope-skill-pool" className="cursor-pointer">
              {t("backup.scopeSkillPool")}
            </Label>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="scope-secrets"
                checked={value.includeSecrets}
                onCheckedChange={(checked) =>
                  set({ includeSecrets: !!checked })
                }
              />
              <Label htmlFor="scope-secrets" className="cursor-pointer">
                {t("backup.scopeSecrets")}
              </Label>
            </div>
            <div className={styles.secretsHint}>
              {t("backup.scopeSecretsHint")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
