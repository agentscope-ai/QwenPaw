import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { PlusCircle, Trash2, Folder, File } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import styles from "../index.module.less";

interface FileGuardSectionProps {
  onSave?: (handlers: {
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  }) => void;
}

export function FileGuardSection({ onSave }: FileGuardSectionProps = {}) {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(true);
  const [allowPreviewOutsideWorkspace, setAllowPreviewOutsideWorkspace] =
    useState(false);
  const [paths, setPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [removeConfirm, setRemoveConfirm] = useState<string | null>(null);
  const { message } = useAppMessage();

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getFileGuard();
      setEnabled(data?.enabled ?? true);
      setAllowPreviewOutsideWorkspace(
        data?.allow_preview_outside_workspace ?? false,
      );
      setPaths(data?.paths ?? []);
    } catch {
      message.error(t("security.fileGuard.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggle = useCallback(
    async (checked: boolean) => {
      setEnabled(checked);
      try {
        await api.updateFileGuard({ enabled: checked });
        message.success(t("security.fileGuard.saveSuccess"));
      } catch {
        setEnabled(!checked);
        message.error(t("security.fileGuard.saveFailed"));
      }
    },
    [t],
  );

  const handlePreviewToggle = useCallback(
    async (checked: boolean) => {
      setAllowPreviewOutsideWorkspace(checked);
      try {
        await api.updateFileGuard({
          allow_preview_outside_workspace: checked,
        });
        message.success(t("security.fileGuard.saveSuccess"));
      } catch {
        setAllowPreviewOutsideWorkspace(!checked);
        message.error(t("security.fileGuard.saveFailed"));
      }
    },
    [t],
  );

  const handleAdd = useCallback(() => {
    const trimmed = newPath.trim();
    if (!trimmed) return;
    if (paths.includes(trimmed)) {
      message.warning(t("security.fileGuard.duplicate"));
      return;
    }
    setPaths((prev) => [...prev, trimmed]);
    setNewPath("");
  }, [newPath, paths, t]);

  const handleRemove = useCallback((path: string) => {
    setPaths((prev) => prev.filter((p) => p !== path));
    setRemoveConfirm(null);
  }, []);

  const handleSave = useCallback(async () => {
    try {
      setSaving(true);
      await api.updateFileGuard({ paths });
      message.success(t("security.fileGuard.saveSuccess"));
    } catch {
      message.error(t("security.fileGuard.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [paths, t]);

  const handleReset = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    onSave?.({ save: handleSave, reset: handleReset, saving });
  }, [handleSave, handleReset, saving, onSave]);

  return (
    <>
      <div
        className={`${styles.formCard} border rounded-lg p-4 flex flex-col gap-4`}
      >
        <div className="flex items-center justify-between">
          <span className="font-medium">
            {t("security.fileGuard.enableLabel")}
          </span>
          <Switch checked={enabled} onCheckedChange={handleToggle} />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <span className="font-medium">
              {t("security.fileGuard.allowPreviewOutsideWorkspace")}
            </span>
            <div className="text-xs text-muted-foreground mt-0.5">
              {t("security.fileGuard.allowPreviewOutsideWorkspaceDesc")}
            </div>
          </div>
          <Switch
            checked={allowPreviewOutsideWorkspace}
            onCheckedChange={handlePreviewToggle}
          />
        </div>

        <div className="flex gap-2">
          <Input
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            placeholder={t("security.fileGuard.inputPlaceholder")}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAdd();
            }}
            disabled={!enabled}
            className="flex-1"
          />
          <Button onClick={handleAdd} disabled={!newPath.trim() || !enabled}>
            <PlusCircle size={16} className="mr-2" />
            {t("security.fileGuard.add")}
          </Button>
        </div>
      </div>

      <div className={`${styles.tableCard} border rounded-lg mt-2`}>
        <div className={loading ? "opacity-60 pointer-events-none" : ""}>
          {paths.length === 0 && !loading ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              {t("security.fileGuard.empty")}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("security.fileGuard.path")}</TableHead>
                  <TableHead style={{ width: 80 }}>
                    {t("security.fileGuard.actions")}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paths.map((path) => {
                  const isDir = path.endsWith("/") || path.endsWith("\\");
                  return (
                    <TableRow key={path}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {isDir ? (
                            <Folder size={16} className="text-yellow-500" />
                          ) : (
                            <File size={16} className="text-blue-500" />
                          )}
                          <code className="text-sm">{path}</code>
                          {isDir && (
                            <Badge
                              variant="outline"
                              className="text-xs border-orange-300 text-orange-600"
                            >
                              {t("security.fileGuard.directory")}
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                          onClick={() => setRemoveConfirm(path)}
                        >
                          <Trash2 size={14} />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      <AlertDialog
        open={!!removeConfirm}
        onOpenChange={(v) => {
          if (!v) setRemoveConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("security.fileGuard.removeConfirm")}
            </AlertDialogTitle>
            <AlertDialogDescription>{removeConfirm}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => removeConfirm && handleRemove(removeConfirm)}
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
