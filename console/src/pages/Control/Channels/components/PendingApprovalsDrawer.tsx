import { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  accessControlApi,
  type PendingEntry,
} from "../../../../api/modules/accessControl";
import { getChannelLabel, type ChannelKey } from "./constants";
import { ChannelIcon } from "./ChannelIcon";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useReactTable,
  getCoreRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, Check, X, Trash2, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

type PendingAction = "approve" | "deny" | "dismiss";

const ACTION_API_MAP: Record<
  PendingAction,
  typeof accessControlApi.approveAclPending
> = {
  approve: accessControlApi.approveAclPending,
  deny: accessControlApi.denyAclPending,
  dismiss: accessControlApi.dismissAclPending,
};

const ACTION_SUCCESS_KEY: Record<PendingAction, string> = {
  approve: "channels.approveSuccess",
  deny: "channels.denySuccess",
  dismiss: "channels.dismissSuccess",
};

interface PendingApprovalsDrawerProps {
  open: boolean;
  onClose: () => void;
}

// Inline editable cell
function EditableCell({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const commit = () => {
    if (draft !== value) onChange(draft);
    setEditing(false);
  };
  if (editing) {
    return (
      <input
        autoFocus
        className="w-full border-b border-primary bg-transparent text-sm outline-none py-0.5"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
      />
    );
  }
  return (
    <span
      className="cursor-pointer hover:text-primary text-sm"
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {value || <span className="text-muted-foreground/40">-</span>}
    </span>
  );
}

// Copy button
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };
  return (
    <button
      onClick={copy}
      className="text-muted-foreground hover:text-foreground"
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
    </button>
  );
}

export function PendingApprovalsDrawer({
  open,
  onClose,
}: PendingApprovalsDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [pending, setPending] = useState<PendingEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set());
  const [confirmBatch, setConfirmBatch] = useState<PendingAction | null>(null);
  const [channelFilter, setChannelFilter] = useState<string>("all");

  const fetchPending = useCallback(async () => {
    setLoading(true);
    try {
      const data = await accessControlApi.getAclAllPending();
      setPending(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchPending();
      setSelectedRowIds(new Set());
    }
  }, [open, fetchPending]);

  const availableChannels = useMemo(() => {
    return Array.from(new Set(pending.map((e) => e.channel)));
  }, [pending]);

  const filteredPending = useMemo(() => {
    if (channelFilter === "all") return pending;
    return pending.filter((e) => e.channel === channelFilter);
  }, [pending, channelFilter]);

  const selectedEntries = useMemo(
    () =>
      Array.from(selectedRowIds).map((key) => {
        const [channel, ...rest] = key.split(":");
        return { channel, user_id: rest.join(":") };
      }),
    [selectedRowIds],
  );

  const handleRemarkSave = async (entry: PendingEntry, remark: string) => {
    try {
      await accessControlApi.updatePendingRemark(
        entry.channel,
        entry.user_id,
        remark,
      );
      setPending((prev) =>
        prev.map((p) =>
          p.channel === entry.channel && p.user_id === entry.user_id
            ? { ...p, remark }
            : p,
        ),
      );
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleUsernameSave = async (entry: PendingEntry, username: string) => {
    try {
      await accessControlApi.updateUsername(
        entry.channel,
        entry.user_id,
        username,
      );
      setPending((prev) =>
        prev.map((p) =>
          p.channel === entry.channel && p.user_id === entry.user_id
            ? { ...p, username }
            : p,
        ),
      );
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleAction = async (entry: PendingEntry, action: PendingAction) => {
    const key = `${entry.channel}:${entry.user_id}`;
    setActionLoading(key);
    try {
      await ACTION_API_MAP[action]([
        { channel: entry.channel, user_id: entry.user_id },
      ]);
      message.success(t(ACTION_SUCCESS_KEY[action]));
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleBatchAction = async (action: PendingAction) => {
    setBatchLoading(true);
    try {
      await ACTION_API_MAP[action](selectedEntries);
      message.success(
        t("channels.batchSuccess", { count: selectedEntries.length }),
      );
      setSelectedRowIds(new Set());
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setBatchLoading(false);
    }
  };

  const columns: ColumnDef<PendingEntry>[] = [
    {
      id: "channel",
      header: t("channels.channel"),
      size: 100,
      cell: ({ row }) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-1.5">
              <ChannelIcon
                channelKey={row.original.channel as ChannelKey}
                size={16}
              />
              <span className="text-sm">
                {getChannelLabel(row.original.channel as ChannelKey, t)}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            {getChannelLabel(row.original.channel as ChannelKey, t)}
          </TooltipContent>
        </Tooltip>
      ),
    },
    {
      id: "username",
      header: t("channels.username"),
      size: 120,
      cell: ({ row }) => (
        <EditableCell
          value={row.original.username || ""}
          onChange={(v) => handleUsernameSave(row.original, v)}
        />
      ),
    },
    {
      id: "user_id",
      header: t("channels.userId"),
      size: 140,
      cell: ({ row }) => (
        <div className="flex items-center gap-1 max-w-[140px]">
          <span className="truncate text-sm" title={row.original.user_id}>
            {row.original.user_id}
          </span>
          <CopyButton text={row.original.user_id} />
        </div>
      ),
    },
    {
      id: "first_message",
      header: t("channels.firstMessage"),
      size: 150,
      cell: ({ row }) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="truncate max-w-[140px] block text-sm">
              {row.original.first_message || "-"}
            </span>
          </TooltipTrigger>
          <TooltipContent>{row.original.first_message}</TooltipContent>
        </Tooltip>
      ),
    },
    {
      id: "remark",
      header: t("channels.remark"),
      size: 130,
      cell: ({ row }) => (
        <EditableCell
          value={row.original.remark || ""}
          onChange={(v) => handleRemarkSave(row.original, v)}
        />
      ),
    },
    {
      id: "timestamp",
      header: t("channels.time"),
      size: 150,
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.timestamp
            ? new Date(row.original.timestamp * 1000).toLocaleString()
            : "-"}
        </span>
      ),
    },
    {
      id: "actions",
      header: t("channels.actions"),
      size: 200,
      cell: ({ row }) => {
        const key = `${row.original.channel}:${row.original.user_id}`;
        const isLoading = actionLoading === key;
        return (
          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-green-600 hover:text-green-600 text-xs"
              disabled={isLoading}
              onClick={() => handleAction(row.original, "approve")}
            >
              {isLoading ? (
                <Loader2 size={10} className="animate-spin" />
              ) : (
                <Check size={12} className="mr-1" />
              )}
              {t("channels.approve")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-destructive hover:text-destructive text-xs"
              disabled={isLoading}
              onClick={() => handleAction(row.original, "deny")}
            >
              <X size={12} className="mr-1" />
              {t("channels.deny")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-muted-foreground text-xs"
              disabled={isLoading}
              onClick={() => handleAction(row.original, "dismiss")}
            >
              {t("channels.dismiss")}
            </Button>
          </div>
        );
      },
    },
  ];

  const table = useReactTable({
    data: filteredPending,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (row) => `${row.channel}:${row.user_id}`,
    initialState: { pagination: { pageSize: 10 } },
  });

  const hasSelection = selectedRowIds.size > 0;

  return (
    <>
      <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
        <SheetContent side="right" className="w-[960px] flex flex-col p-0">
          <SheetHeader className="px-6 py-4 border-b">
            <SheetTitle>{t("channels.pendingApprovals")}</SheetTitle>
          </SheetHeader>

          <div className="flex-1 overflow-y-auto px-6 py-4">
            {/* Filter + batch actions */}
            <div className="flex items-center justify-between mb-4 gap-2">
              <Select
                value={channelFilter}
                onValueChange={(v) => {
                  setChannelFilter(v);
                  setSelectedRowIds(new Set());
                }}
              >
                <SelectTrigger className="w-[200px]">
                  <SelectValue placeholder={t("channels.filterByChannel")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    {t("channels.filterByChannel")}
                  </SelectItem>
                  {availableChannels.map((ch) => (
                    <SelectItem key={ch} value={ch}>
                      {getChannelLabel(ch as ChannelKey, t)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="flex items-center gap-2">
                {hasSelection && (
                  <span className="text-xs text-muted-foreground">
                    {t("channels.selectedCount", {
                      count: selectedRowIds.size,
                    })}
                  </span>
                )}
                <Button
                  size="sm"
                  disabled={!hasSelection}
                  onClick={() => setConfirmBatch("approve")}
                >
                  {batchLoading ? (
                    <Loader2 size={12} className="animate-spin mr-1" />
                  ) : (
                    <Check size={12} className="mr-1" />
                  )}
                  {t("channels.batchApprove")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasSelection}
                  onClick={() => setConfirmBatch("deny")}
                >
                  <X size={12} className="mr-1" />
                  {t("channels.batchDeny")}
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={!hasSelection}
                  onClick={() => setConfirmBatch("dismiss")}
                >
                  <Trash2 size={12} className="mr-1" />
                  {t("channels.batchDismiss")}
                </Button>
              </div>
            </div>

            {/* Table */}
            {loading ? (
              <div className="flex justify-center items-center h-24">
                <Loader2 className="animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="border rounded-md overflow-x-auto">
                <Table>
                  <TableHeader>
                    {table.getHeaderGroups().map((hg) => (
                      <TableRow key={hg.id}>
                        <TableHead className="w-10">
                          <input
                            type="checkbox"
                            className="cursor-pointer"
                            checked={
                              filteredPending.length > 0 &&
                              filteredPending.every((r) =>
                                selectedRowIds.has(`${r.channel}:${r.user_id}`),
                              )
                            }
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedRowIds(
                                  new Set(
                                    filteredPending.map(
                                      (r) => `${r.channel}:${r.user_id}`,
                                    ),
                                  ),
                                );
                              } else {
                                setSelectedRowIds(new Set());
                              }
                            }}
                          />
                        </TableHead>
                        {hg.headers.map((header) => (
                          <TableHead
                            key={header.id}
                            style={{ width: header.getSize() }}
                          >
                            {flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                          </TableHead>
                        ))}
                      </TableRow>
                    ))}
                  </TableHeader>
                  <TableBody>
                    {table.getRowModel().rows.map((row) => {
                      const rowKey = `${row.original.channel}:${row.original.user_id}`;
                      return (
                        <TableRow
                          key={row.id}
                          className={cn(
                            selectedRowIds.has(rowKey) ? "bg-muted/50" : "",
                          )}
                        >
                          <TableCell>
                            <input
                              type="checkbox"
                              className="cursor-pointer"
                              checked={selectedRowIds.has(rowKey)}
                              onChange={(e) => {
                                const next = new Set(selectedRowIds);
                                if (e.target.checked) next.add(rowKey);
                                else next.delete(rowKey);
                                setSelectedRowIds(next);
                              }}
                            />
                          </TableCell>
                          {row.getVisibleCells().map((cell) => (
                            <TableCell key={cell.id}>
                              {flexRender(
                                cell.column.columnDef.cell,
                                cell.getContext(),
                              )}
                            </TableCell>
                          ))}
                        </TableRow>
                      );
                    })}
                    {table.getRowModel().rows.length === 0 && (
                      <TableRow>
                        <TableCell
                          colSpan={columns.length + 1}
                          className="h-16 text-center text-muted-foreground text-sm"
                        >
                          {t("channels.noPendingApprovals")}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>

      {/* Batch action confirm */}
      <AlertDialog
        open={!!confirmBatch}
        onOpenChange={(o) => !o && setConfirmBatch(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmBatch === "approve"
                ? t("channels.batchApprove")
                : confirmBatch === "deny"
                ? t("channels.batchDeny")
                : t("channels.batchDismiss")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmBatch === "approve"
                ? t("channels.batchApproveConfirm", {
                    count: selectedRowIds.size,
                  })
                : confirmBatch === "deny"
                ? t("channels.batchDenyConfirm", { count: selectedRowIds.size })
                : t("channels.batchDismissConfirm", {
                    count: selectedRowIds.size,
                  })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (confirmBatch) await handleBatchAction(confirmBatch);
                setConfirmBatch(null);
              }}
            >
              {t("common.confirm", "Confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
