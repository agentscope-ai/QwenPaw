import { useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import api from "../../../api";
import { useEnvVars } from "./useEnvVars";
import { EmptyState, AddButton, Toolbar, EnvRow, type Row } from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

function shiftIndices(prev: Set<number>, removedIdx: number): Set<number> {
  const next = new Set<number>();
  prev.forEach((i) => {
    if (i < removedIdx) next.add(i);
    else if (i > removedIdx) next.add(i - 1);
  });
  return next;
}

type DeleteConfirm = {
  title: string;
  content: string;
  onOk: () => Promise<void>;
};

function EnvironmentsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { envVars, loading, error, fetchAll } = useEnvVars();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [keyErrors, setKeyErrors] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirm | null>(
    null,
  );

  const workingRows: Row[] = useMemo(
    () => rows ?? envVars.map((e) => ({ key: e.key, value: e.value })),
    [rows, envVars],
  );

  const dirty = rows !== null;
  const someSelected = selected.size > 0;
  const allSelected =
    workingRows.length > 0 && workingRows.every((_, i) => selected.has(i));

  const ensureLocal = useCallback((): Row[] => {
    if (rows) return [...rows];
    return envVars.map((e) => ({ key: e.key, value: e.value }));
  }, [rows, envVars]);

  const toggleSelect = useCallback((idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(workingRows.map((_, i) => i)));
    }
  }, [allSelected, workingRows]);

  const updateRow = useCallback(
    (idx: number, field: "key" | "value", val: string) => {
      const next = ensureLocal();
      next[idx] = { ...next[idx], [field]: val };
      setRows(next);
      if (field === "key") {
        setKeyErrors((prev) => {
          const copy = { ...prev };
          delete copy[idx];
          return copy;
        });
      }
    },
    [ensureLocal],
  );

  const addRow = useCallback(() => {
    const next = ensureLocal();
    next.push({ key: "", value: "", isNew: true });
    setRows(next);
  }, [ensureLocal]);

  const insertRowAfter = useCallback(
    (idx: number) => {
      const next = ensureLocal();
      next.splice(idx + 1, 0, { key: "", value: "", isNew: true });
      setRows(next);
      setSelected((prev) => {
        const rebuilt = new Set<number>();
        prev.forEach((i) => rebuilt.add(i <= idx ? i : i + 1));
        return rebuilt;
      });
    },
    [ensureLocal],
  );

  const removeRow = useCallback(
    (idx: number) => {
      const row = workingRows[idx];

      if (row.isNew) {
        const next = ensureLocal();
        next.splice(idx, 1);
        setRows(next.length === 0 && envVars.length === 0 ? null : next);
        setSelected((prev) => shiftIndices(prev, idx));
        return;
      }

      setDeleteConfirm({
        title: t("environments.deleteVariable"),
        content: t("environments.deleteConfirm", { name: row.key }),
        onOk: async () => {
          await api.deleteEnv(row.key);
          message.success(t("environments.deleteSuccess", { name: row.key }));
          setRows(null);
          setSelected(new Set());
          setKeyErrors({});
          fetchAll();
        },
      });
    },
    [workingRows, ensureLocal, envVars.length, fetchAll, t, message],
  );

  const removeSelected = useCallback(() => {
    if (selected.size === 0) return;
    const indices = Array.from(selected).sort((a, b) => a - b);
    const names = indices.map((i) => workingRows[i]?.key).filter(Boolean);
    const hasPersistedRows = indices.some((i) => !workingRows[i]?.isNew);

    if (!hasPersistedRows) {
      const next = ensureLocal().filter((_, i) => !selected.has(i));
      setRows(next.length === 0 && envVars.length === 0 ? null : next);
      setSelected(new Set());
      return;
    }

    const label =
      names.length <= 3
        ? names.map((n) => `"${n}"`).join(", ")
        : `${names.length} variables`;

    setDeleteConfirm({
      title: t("environments.deleteSelected"),
      content: t("environments.deleteSelectedConfirm", { label }),
      onOk: async () => {
        const persistedKeysToDelete = indices
          .map((i) => workingRows[i])
          .filter((row) => row && !row.isNew)
          .map((row) => row.key.trim())
          .filter(Boolean);

        if (persistedKeysToDelete.length > 0) {
          await Promise.all(
            persistedKeysToDelete.map((key) => api.deleteEnv(key)),
          );
        }

        message.success(t("environments.deleteSuccess", { name: label }));
        setRows(null);
        setSelected(new Set());
        setKeyErrors({});
        fetchAll();
      },
    });
  }, [
    selected,
    workingRows,
    ensureLocal,
    envVars.length,
    fetchAll,
    t,
    message,
  ]);

  const validate = useCallback((): boolean => {
    const errors: Record<number, string> = {};
    const seen = new Set<string>();
    for (let i = 0; i < workingRows.length; i++) {
      const k = workingRows[i].key.trim();
      if (!k) {
        errors[i] = t("environments.keyRequired");
      } else if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) {
        errors[i] = t("environments.invalidKeyFormat");
      } else if (seen.has(k)) {
        errors[i] = t("environments.duplicateKey");
      }
      seen.add(k);
    }
    setKeyErrors(errors);
    return Object.keys(errors).length === 0;
  }, [workingRows, t]);

  const handleSave = useCallback(async () => {
    if (!validate()) return;
    const dict: Record<string, string> = {};
    for (const r of workingRows) {
      dict[r.key.trim()] = r.value;
    }
    setSaving(true);
    try {
      await api.saveEnvs(dict);
      message.success(t("environments.saveSuccess"));
      setRows(null);
      setKeyErrors({});
      setSelected(new Set());
      fetchAll();
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("environments.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  }, [validate, workingRows, fetchAll, t, message]);

  const handleReset = useCallback(() => {
    setRows(null);
    setKeyErrors({});
    setSelected(new Set());
  }, []);

  return (
    <div className={styles.environmentsPage}>
      <PageHeader
        parent={t("environments.parent")}
        current={t("environments.environments")}
      />

      {loading ? (
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("environments.loading")}</span>
        </div>
      ) : error ? (
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={fetchAll}
            className="mt-3"
          >
            {t("environments.retry")}
          </Button>
        </div>
      ) : (
        <div className={styles.tableCard}>
          <Toolbar
            workingRowsLength={workingRows.length}
            allSelected={allSelected}
            someSelected={someSelected}
            selectedSize={selected.size}
            dirty={dirty}
            saving={saving}
            indeterminate={someSelected && !allSelected}
            onToggleSelectAll={toggleSelectAll}
            onRemoveSelected={removeSelected}
            onReset={handleReset}
            onSave={handleSave}
          />

          <div className={styles.rowList}>
            {workingRows.map((row, idx) => (
              <EnvRow
                key={idx}
                row={row}
                idx={idx}
                checked={selected.has(idx)}
                error={keyErrors[idx]}
                onToggle={toggleSelect}
                onChange={updateRow}
                onInsert={insertRowAfter}
                onRemove={removeRow}
              />
            ))}

            {workingRows.length === 0 && <EmptyState />}
          </div>

          <AddButton onClick={addRow} />
        </div>
      )}

      <AlertDialog
        open={!!deleteConfirm}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{deleteConfirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteConfirm?.content}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={async () => {
                if (!deleteConfirm) return;
                try {
                  await deleteConfirm.onOk();
                } catch (err) {
                  const errMsg =
                    err instanceof Error
                      ? err.message
                      : t("environments.deleteFailed");
                  message.error(errMsg);
                } finally {
                  setDeleteConfirm(null);
                }
              }}
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default EnvironmentsPage;
