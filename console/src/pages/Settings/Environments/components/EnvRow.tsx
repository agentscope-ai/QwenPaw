import { Checkbox, Input } from "@agentscope-ai/design";
import { Trash2 as SparkDeleteLine, Plus as SparkPlusLine } from "lucide-react";
import {
  Eye as EyeOutlined,
  EyeOff as EyeInvisibleOutlined,
} from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export interface Row {
  key: string;
  value: string;
  isNew?: boolean;
}

interface EnvRowProps {
  row: Row;
  idx: number;
  checked: boolean;
  error?: string;
  onToggle: (idx: number) => void;
  onChange: (idx: number, field: "key" | "value", val: string) => void;
  onInsert: (idx: number) => void;
  onRemove: (idx: number) => void;
}

export function EnvRow({
  row,
  idx,
  checked,
  error,
  onToggle,
  onChange,
  onInsert,
  onRemove,
}: EnvRowProps) {
  const { t } = useTranslation();
  const fieldId = useId();
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  return (
    <div className={`${styles.envRow} ${checked ? styles.envRowSelected : ""}`}>
      <Checkbox
        aria-label={`${t("environments.variable")}: ${row.key || idx + 1}`}
        checked={checked}
        onChange={() => onToggle(idx)}
        className={styles.rowCheckbox}
      />

      <div className={styles.fieldsWrap}>
        <div
          className={`${styles.inputGroup} ${
            error ? styles.inputGroupError : ""
          }`}
        >
          <label htmlFor={`${fieldId}-key`} className={styles.inputLabel}>
            {t("environments.key")}
          </label>
          <Input
            id={`${fieldId}-key`}
            aria-invalid={!!error}
            aria-describedby={error ? `${fieldId}-error` : undefined}
            value={row.key}
            placeholder={t("environments.variableNamePlaceholder")}
            disabled={!row.isNew}
            onChange={(e) => onChange(idx, "key", e.target.value)}
            className={styles.inputField}
            autoFocus={row.isNew}
          />
        </div>

        <div className={styles.inputGroup}>
          <label htmlFor={`${fieldId}-value`} className={styles.inputLabel}>
            {t("environments.value")}
          </label>
          <Input
            id={`${fieldId}-value`}
            value={row.value}
            placeholder={t("environments.valuePlaceholder")}
            type={isPasswordVisible ? "text" : "password"}
            onChange={(e) => onChange(idx, "value", e.target.value)}
            className={styles.inputField}
            suffix={
              <button
                className={styles.passwordToggle}
                onClick={() => setIsPasswordVisible(!isPasswordVisible)}
                type="button"
                title={
                  isPasswordVisible
                    ? t("environments.hideValue")
                    : t("environments.showValue")
                }
              >
                {isPasswordVisible ? (
                  <EyeOutlined size="1em" />
                ) : (
                  <EyeInvisibleOutlined size="1em" />
                )}
              </button>
            }
          />
        </div>
      </div>

      <div className={styles.rowActions}>
        <button
          className={styles.rowIconBtn}
          onClick={() => onInsert(idx)}
          title={t("environments.insertRowBelow")}
        >
          <SparkPlusLine size="1em" />
        </button>
        <button
          className={`${styles.rowIconBtn} ${styles.rowIconBtnDanger}`}
          onClick={() => onRemove(idx)}
          title={t("environments.deleteRow")}
        >
          <SparkDeleteLine size="1em" />
        </button>
      </div>

      {error && (
        <div id={`${fieldId}-error`} role="alert" className={styles.rowError}>
          {error}
        </div>
      )}
    </div>
  );
}
