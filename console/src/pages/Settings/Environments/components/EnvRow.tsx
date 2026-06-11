import { useState } from "react";
import { Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
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
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  return (
    <div className={`${styles.envRow} ${checked ? styles.envRowSelected : ""}`}>
      <Checkbox
        checked={checked}
        onCheckedChange={() => onToggle(idx)}
        className={styles.rowCheckbox}
      />

      <div className={styles.fieldsWrap}>
        <div
          className={`${styles.inputGroup} ${
            error ? styles.inputGroupError : ""
          }`}
        >
          <span className={styles.inputLabel}>Key</span>
          <Input
            value={row.key}
            placeholder="Variable Name"
            disabled={!row.isNew}
            onChange={(e) => onChange(idx, "key", e.target.value)}
            className={styles.inputField}
            autoFocus={row.isNew}
          />
        </div>

        <div className={styles.inputGroup}>
          <span className={styles.inputLabel}>Value</span>
          <div className="relative">
            <Input
              value={row.value}
              placeholder="Value"
              type={isPasswordVisible ? "text" : "password"}
              onChange={(e) => onChange(idx, "value", e.target.value)}
              className={`${styles.inputField} pr-8`}
            />
            <button
              className={`${styles.passwordToggle} absolute right-2 top-1/2 -translate-y-1/2`}
              onClick={() => setIsPasswordVisible(!isPasswordVisible)}
              type="button"
              title={
                isPasswordVisible
                  ? t("environments.hideValue")
                  : t("environments.showValue")
              }
            >
              {isPasswordVisible ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
      </div>

      <div className={styles.rowActions}>
        <button
          className={styles.rowIconBtn}
          onClick={() => onInsert(idx)}
          title={t("environments.insertRowBelow")}
        >
          <Plus size={14} />
        </button>
        <button
          className={`${styles.rowIconBtn} ${styles.rowIconBtnDanger}`}
          onClick={() => onRemove(idx)}
          title={t("environments.deleteRow")}
        >
          <Trash2 size={14} />
        </button>
      </div>

      {error && <div className={styles.rowError}>{error}</div>}
    </div>
  );
}
