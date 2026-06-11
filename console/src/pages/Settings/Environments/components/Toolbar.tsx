import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
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
            data-state={indeterminate ? "indeterminate" : undefined}
            onCheckedChange={onToggleSelectAll}
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
            variant="destructive"
            size="sm"
            onClick={onRemoveSelected}
            disabled={saving}
          >
            <Trash2 className="mr-1 h-3 w-3" />
            {t("common.delete")} ({selectedSize})
          </Button>
        )}
        {dirty && (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={onReset}
              disabled={saving}
            >
              {t("common.reset")}
            </Button>
            <Button size="sm" disabled={saving} onClick={onSave}>
              {t("common.save")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
