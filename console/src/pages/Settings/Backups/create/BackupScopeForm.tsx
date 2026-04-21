/**
 * Controlled form section for choosing what to include in a backup.
 * Handles the full/partial radio toggle and the four partial-mode checkboxes
 * (agents, global config, skill pool, secrets). Extracted from CreateBackupModal
 * so it can be unit-tested and potentially reused independently.
 */
import { Checkbox, Radio } from "antd";
import { useTranslation } from "react-i18next";
import type { AgentSummary } from "@/api/types/agents";
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
        <Radio.Group
          value={value.backupMode}
          onChange={(e) => set({ backupMode: e.target.value })}
          className={styles.radioGroup}
        >
          <Radio value="full">
            <strong>{t("backup.fullBackup")}</strong>
            <div className={styles.radioDesc}>{t("backup.fullBackupDesc")}</div>
          </Radio>
          <Radio value="partial">
            <strong>{t("backup.partialBackup")}</strong>
            <div className={styles.radioDesc}>
              {t("backup.partialBackupDesc")}
            </div>
          </Radio>
        </Radio.Group>
      </div>

      {value.backupMode === "partial" && (
        <div className={styles.partialOptions}>
          <Checkbox
            checked={value.selectedAgents.length > 0}
            indeterminate={
              value.selectedAgents.length > 0 &&
              value.selectedAgents.length < agents.length
            }
            onChange={(e) => {
              set({
                selectedAgents: e.target.checked ? agents.map((a) => a.id) : [],
              });
            }}
          >
            {t("backup.scopeAgents")}
          </Checkbox>

          {value.selectedAgents.length > 0 && (
            <div className={styles.agentSelect}>
              <AgentMultiSelect
                agents={agents}
                value={value.selectedAgents}
                onChange={(ids) => set({ selectedAgents: ids })}
              />
            </div>
          )}

          <Checkbox
            checked={value.globalConfig}
            onChange={(e) => set({ globalConfig: e.target.checked })}
          >
            {t("backup.scopeGlobalConfig")}
          </Checkbox>

          <Checkbox
            checked={value.includeSkillPool}
            onChange={(e) => set({ includeSkillPool: e.target.checked })}
          >
            {t("backup.scopeSkillPool")}
          </Checkbox>

          <div>
            <Checkbox
              checked={value.includeSecrets}
              onChange={(e) => set({ includeSecrets: e.target.checked })}
            >
              {t("backup.scopeSecrets")}
            </Checkbox>
            <div className={styles.secretsHint}>
              {t("backup.scopeSecretsHint")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
