/**
 * Renders the backup list with inline Restore / Export / Delete actions.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { BackupMeta } from "@/api/types/backup";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import ScopeTags from "./ScopeTags";
import styles from "./BackupTable.module.less";

dayjs.extend(relativeTime);

const PAGE_SIZE = 10;

interface Props {
  backups: BackupMeta[];
  searchQuery: string;
  onRestore: (backup: BackupMeta) => void;
  onRefresh: () => void;
}

export default function BackupTable({
  backups,
  searchQuery,
  onRestore,
  onRefresh,
}: Props) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [exportTarget, setExportTarget] = useState<BackupMeta | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BackupMeta | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const filteredBackups = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const filtered = q
      ? backups.filter(
          (s) =>
            s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q),
        )
      : backups;
    return [...filtered].sort((a, b) => {
      const diff = dayjs(a.created_at).unix() - dayjs(b.created_at).unix();
      return sortDir === "desc" ? -diff : diff;
    });
  }, [backups, searchQuery, sortDir]);

  const totalPages = Math.ceil(filteredBackups.length / PAGE_SIZE);
  const pageData = filteredBackups.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE,
  );

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.deleteBackups([deleteTarget.id]);
      message.success(t("backup.deleteSuccess"));
      onRefresh();
    } catch {
      message.error(t("backup.deleteFailed"));
    } finally {
      setDeleteTarget(null);
    }
  };

  const handleExportConfirm = async () => {
    if (!exportTarget) return;
    try {
      await api.exportBackup(exportTarget.id, exportTarget.name);
    } catch {
      message.error(t("backup.exportFailed"));
    } finally {
      setExportTarget(null);
    }
  };

  if (backups.length === 0) {
    return (
      <Card className={styles.tableCard}>
        <CardContent className="flex items-center justify-center py-10 text-muted-foreground">
          {t("backup.noBackups")}
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card className={styles.tableCard}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[300px]">ID</TableHead>
              <TableHead>{t("backup.name")}</TableHead>
              <TableHead className="w-[320px]">
                {t("backup.scopeSummary")}
              </TableHead>
              <TableHead>{t("backup.descriptionLabel")}</TableHead>
              <TableHead
                className="w-[160px] cursor-pointer select-none"
                onClick={() =>
                  setSortDir((d) => (d === "desc" ? "asc" : "desc"))
                }
              >
                {t("backup.createdAt")} {sortDir === "desc" ? "↓" : "↑"}
              </TableHead>
              <TableHead className="w-[200px]">{t("common.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageData.map((record) => (
              <TableRow key={record.id}>
                <TableCell>
                  <span className={styles.idCell}>{record.id}</span>
                </TableCell>
                <TableCell className="max-w-[200px] truncate">
                  {record.name}
                </TableCell>
                <TableCell>
                  <ScopeTags
                    scope={record.scope}
                    agentCount={record.agent_count}
                  />
                </TableCell>
                <TableCell className="max-w-[150px] truncate">
                  {record.description}
                </TableCell>
                <TableCell>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="cursor-default">
                        {dayjs(record.created_at).fromNow()}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      {dayjs(record.created_at).format("YYYY-MM-DD HH:mm:ss")}
                    </TooltipContent>
                  </Tooltip>
                </TableCell>
                <TableCell>
                  <span className={styles.actions}>
                    <Button
                      variant="link"
                      size="sm"
                      onClick={() => onRestore(record)}
                    >
                      {t("backup.restore")}
                    </Button>
                    <Button
                      variant="link"
                      size="sm"
                      onClick={() => setExportTarget(record)}
                    >
                      {t("backup.export")}
                    </Button>
                    <Button
                      variant="link"
                      size="sm"
                      className="text-destructive"
                      onClick={() => setDeleteTarget(record)}
                    >
                      {t("backup.delete")}
                    </Button>
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-2 text-sm text-muted-foreground">
            <span>{t("backup.total", { count: filteredBackups.length })}</span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                &lt;
              </Button>
              <span className="px-2 py-1">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page === totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                &gt;
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Export confirmation */}
      <AlertDialog
        open={!!exportTarget}
        onOpenChange={(open) => !open && setExportTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("backup.exportWarningTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("backup.exportWarningContent")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleExportConfirm}
            >
              {t("backup.exportConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("backup.deleteConfirm")}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDelete}
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
