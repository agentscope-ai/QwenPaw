import { Switch } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

/**
 * The 7 shell evasion check types defined in
 * `shell_evasion_guardian.py` → `_CHECKS`.
 */
const SHELL_EVASION_CHECK_KEYS = [
  "command_substitution",
  "obfuscated_flags",
  "backslash_escaped_whitespace",
  "backslash_escaped_operators",
  "newlines",
  "comment_quote_desync",
  "quoted_newline",
] as const;

interface ShellEvasionSectionProps {
  checks: Record<string, boolean>;
  onToggle: (checkName: string, checked: boolean) => void;
  disabled?: boolean;
}

export function ShellEvasionSection({
  checks,
  onToggle,
  disabled = false,
}: ShellEvasionSectionProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.shellEvasionSection}>
      <div className={styles.shellEvasionGrid}>
        {SHELL_EVASION_CHECK_KEYS.map((checkKey) => {
          const isEnabled = checks[checkKey] === true;
          const nameKey = `security.shellEvasion.checks.${checkKey}.name`;
          const descKey = `security.shellEvasion.checks.${checkKey}.description`;
          const displayName =
            t(nameKey, { defaultValue: "" }) ||
            checkKey
              .replace(/_/g, " ")
              .replace(/\b\w/g, (c) => c.toUpperCase());
          const displayDesc = t(descKey, { defaultValue: "" });

          return (
            <div key={checkKey} className={styles.shellEvasionItem}>
              <div className={styles.shellEvasionItemInfo}>
                <span className={styles.shellEvasionItemName}>
                  {displayName}
                </span>
                {displayDesc && (
                  <span className={styles.shellEvasionItemDesc}>
                    {displayDesc}
                  </span>
                )}
              </div>
              <Switch
                size="small"
                checked={isEnabled}
                onChange={(val) => onToggle(checkKey, val)}
                disabled={disabled}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
