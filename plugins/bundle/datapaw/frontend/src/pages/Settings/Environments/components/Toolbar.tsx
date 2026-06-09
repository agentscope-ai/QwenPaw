import { Checkbox, Button } from "@agentscope-ai/design";
import { SparkDeleteLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface ToolbarProps {
  workingRowsLength: number;
  allSelected: boolean;
  someSelected: boolean;
  selectedSize: number;
  dirty: boolean;
  saving: boolean;
  indeterminate: boolean;
  onToggleSelectAll: () => void;
  onRemoveSelected: () => void;
  onReset: () => void;
  onSave: () => void;
  className?: string;
}

export function Toolbar({
  workingRowsLength,
  allSelected,
  someSelected,
  selectedSize,
  dirty,
  saving,
  indeterminate,
  onToggleSelectAll,
  onRemoveSelected,
  onReset,
  onSave,
  className,
}: ToolbarProps) {
  const { t } = useTranslation();

  return (
    <div className={`${styles.toolbar} ${className || ""}`}>
      <div className={styles.toolbarLeft}>
        {workingRowsLength > 0 && (
          <Checkbox
            checked={allSelected}
            indeterminate={indeterminate}
            onChange={onToggleSelectAll}
          />
        )}
        <span className={styles.toolbarCount}>
          {someSelected
            ? `${selectedSize} ${t("environments.of")} ${workingRowsLength} ${t(
                "environments.selected",
              )}`
            : `${workingRowsLength} ${
                workingRowsLength !== 1
                  ? t("environments.variables")
                  : t("environments.variable")
              }`}
        </span>
      </div>

      <div className={styles.toolbarRight}>
        {someSelected && (
          <Button
            danger
            size="small"
            icon={<SparkDeleteLine />}
            onClick={onRemoveSelected}
            disabled={saving}
          >
            {t("common.delete")} ({selectedSize})
          </Button>
        )}
        {dirty && (
          <>
            <Button size="small" onClick={onReset} disabled={saving}>
              {t("common.reset")}
            </Button>
            <Button
              type="primary"
              size="small"
              loading={saving}
              onClick={onSave}
            >
              {t("common.save")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
