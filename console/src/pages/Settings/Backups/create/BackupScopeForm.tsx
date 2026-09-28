/**
 * Controlled form section for choosing what to include in a backup.
 * Handles the full/partial radio toggle and the four partial-mode checkboxes
 * (agents, global config, skill pool, secrets). Extracted from CreateBackupModal
 * so it can be unit-tested and potentially reused independently.
 */
import { Checkbox } from "antd";
import { Check, Folder, Settings2, Library, KeyRound } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";
import { PolicySelector } from "@/components/interaction/PolicySelector";
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

  const full = value.backupMode === "full";
  const reduced = useReducedMotion();
  const choices = [
    {
      key: "agents",
      label: t("backup.scopeAgents"),
      icon: Folder,
      checked: value.selectedAgents.length > 0,
      change: (checked: boolean) =>
        set({ selectedAgents: checked ? agents.map((a) => a.id) : [] }),
    },
    {
      key: "global",
      label: t("backup.scopeGlobalConfig"),
      icon: Settings2,
      checked: value.globalConfig,
      change: (checked: boolean) => set({ globalConfig: checked }),
    },
    {
      key: "skills",
      label: t("backup.scopeSkillPool"),
      icon: Library,
      checked: value.includeSkillPool,
      change: (checked: boolean) => set({ includeSkillPool: checked }),
    },
    {
      key: "secrets",
      label: t("backup.scopeSecrets"),
      icon: KeyRound,
      checked: value.includeSecrets,
      change: (checked: boolean) => set({ includeSecrets: checked }),
    },
  ];
  return (
    <div className={styles.form}>
      <PolicySelector
        label={t("backup.backupMode")}
        value={value.backupMode}
        onChange={(backupMode) => set({ backupMode })}
        options={[
          {
            value: "full",
            label: t("backup.fullBackup"),
            description: t("backup.fullBackupDesc"),
          },
          {
            value: "partial",
            label: t("backup.partialBackup"),
            description: t("backup.partialBackupDesc"),
          },
        ]}
      />
      <section className={styles.scope} aria-label={t("backup.scopeSummary")}>
        {choices.map((choice) => (
          <div
            key={choice.key}
            className={styles.scopeItem}
            data-selected={full || choice.checked || undefined}
          >
            <div className={styles.choiceRow}>
              <choice.icon size={17} aria-hidden="true" />
              {full ? (
                <span className={styles.choiceLabel}>{choice.label}</span>
              ) : (
                <Checkbox
                  checked={choice.checked}
                  indeterminate={
                    choice.key === "agents" &&
                    value.selectedAgents.length > 0 &&
                    value.selectedAgents.length < agents.length
                  }
                  onChange={(e) => choice.change(e.target.checked)}
                >
                  {choice.label}
                </Checkbox>
              )}
              {choice.key === "agents" && (
                <span className={styles.count}>
                  <NumberFlow
                    value={full ? agents.length : value.selectedAgents.length}
                    respectMotionPreference
                  />{" "}
                  / {agents.length}
                </span>
              )}
              {full && (
                <Check
                  size={16}
                  className={styles.included}
                  aria-hidden="true"
                />
              )}
            </div>
            {choice.key === "agents" && (
              <AnimatePresence initial={false}>
                {!full && (
                  <motion.div
                    key="agents"
                    className={styles.agentSelect}
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={
                      reduced
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 360, damping: 38 }
                    }
                  >
                    <div>
                      <AgentMultiSelect
                        agents={agents}
                        value={value.selectedAgents}
                        onChange={(selectedAgents) => set({ selectedAgents })}
                      />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            )}
            {choice.key === "secrets" && (
              <p className={styles.secretsHint}>
                {t("backup.scopeSecretsHint")}
              </p>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
