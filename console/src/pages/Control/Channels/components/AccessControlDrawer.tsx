import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  accessControlApi,
  type ACLData,
  type ACLUserEntry,
} from "../../../../api/modules/accessControl";
import { getChannelLabel, type ChannelKey } from "./constants";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { Loader2, Trash2, Plus, Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface AccessControlDrawerProps {
  open: boolean;
  onClose: () => void;
}

function toEntries(
  map: Record<string, { remark: string; username: string }> | undefined,
): ACLUserEntry[] {
  if (!map) return [];
  return Object.entries(map).map(([userId, info]) => ({
    userId,
    remark: info?.remark ?? "",
    username: info?.username ?? "",
  }));
}

// Inline editable text cell
function EditableCell({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
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
        placeholder={placeholder}
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
      title="Click to edit"
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {value || <span className="text-muted-foreground/40">-</span>}
    </span>
  );
}

// Copy button for user IDs
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

export function AccessControlDrawer({
  open,
  onClose,
}: AccessControlDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [allACLs, setAllACLs] = useState<Record<string, ACLData>>({});
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [newUserId, setNewUserId] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newRemark, setNewRemark] = useState("");
  const [activeTab, setActiveTab] = useState<"whitelist" | "blacklist">(
    "whitelist",
  );
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set());
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<{ userId: string } | null>(
    null,
  );
  const [confirmBatch, setConfirmBatch] = useState(false);

  const fetchACLs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await accessControlApi.getAclAll();
      setAllACLs(data);
      const keys = Object.keys(data);
      if (keys.length === 0) {
        setSelectedChannel(null);
      } else if (!selectedChannel || !keys.includes(selectedChannel)) {
        setSelectedChannel(keys[0]);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [selectedChannel]);

  useEffect(() => {
    if (open) fetchACLs();
  }, [open, fetchACLs]);

  const channelKeys = Object.keys(allACLs);
  const currentACL = selectedChannel ? allACLs[selectedChannel] : null;

  const handleAdd = async () => {
    if (!selectedChannel || !newUserId.trim()) return;
    const addApi =
      activeTab === "whitelist"
        ? accessControlApi.addAclWhitelist
        : accessControlApi.addAclBlacklist;
    try {
      await addApi([
        {
          channel: selectedChannel,
          user_id: newUserId.trim(),
          remark: newRemark.trim(),
          username: newUsername.trim(),
        },
      ]);
      message.success(t("channels.userAdded"));
      setNewUserId("");
      setNewUsername("");
      setNewRemark("");
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleRemove = async (userId: string) => {
    if (!selectedChannel) return;
    const removeApi =
      activeTab === "whitelist"
        ? accessControlApi.removeAclWhitelist
        : accessControlApi.removeAclBlacklist;
    try {
      await removeApi([{ channel: selectedChannel, user_id: userId }]);
      message.success(t("channels.userRemoved"));
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleRemarkSave = async (userId: string, remark: string) => {
    if (!selectedChannel) return;
    try {
      await accessControlApi.updateAclRemark(selectedChannel, userId, remark);
      setAllACLs((prev) => {
        const channelData = prev[selectedChannel];
        if (!channelData) return prev;
        const list = channelData[activeTab];
        const existing = list[userId] ?? { remark: "", username: "" };
        return {
          ...prev,
          [selectedChannel]: {
            ...channelData,
            [activeTab]: { ...list, [userId]: { ...existing, remark } },
          },
        };
      });
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleUsernameSave = async (userId: string, username: string) => {
    if (!selectedChannel) return;
    try {
      await accessControlApi.updateUsername(selectedChannel, userId, username);
      setAllACLs((prev) => {
        const channelData = prev[selectedChannel];
        if (!channelData) return prev;
        const list = channelData[activeTab];
        const existing = list[userId] ?? { remark: "", username: "" };
        return {
          ...prev,
          [selectedChannel]: {
            ...channelData,
            [activeTab]: { ...list, [userId]: { ...existing, username } },
          },
        };
      });
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleBatchRemove = async () => {
    if (!selectedChannel || selectedRowIds.size === 0) return;
    setBatchLoading(true);
    const removeApi =
      activeTab === "whitelist"
        ? accessControlApi.removeAclWhitelist
        : accessControlApi.removeAclBlacklist;
    try {
      await removeApi(
        Array.from(selectedRowIds).map((userId) => ({
          channel: selectedChannel,
          user_id: userId,
        })),
      );
      message.success(
        t("channels.batchSuccess", { count: selectedRowIds.size }),
      );
      setSelectedRowIds(new Set());
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setBatchLoading(false);
    }
  };

  const listData: ACLUserEntry[] = currentACL
    ? toEntries(currentACL[activeTab])
    : [];

  const columns: ColumnDef<ACLUserEntry>[] = [
    {
      id: "username",
      header: t("channels.username"),
      size: 120,
      cell: ({ row }) => (
        <EditableCell
          value={row.original.username || ""}
          onChange={(v) => handleUsernameSave(row.original.userId, v)}
        />
      ),
    },
    {
      id: "userId",
      header: t("channels.userId"),
      size: 180,
      cell: ({ row }) => (
        <div className="flex items-center gap-1 max-w-[180px]">
          <span className="truncate text-sm" title={row.original.userId}>
            {row.original.userId}
          </span>
          <CopyButton text={row.original.userId} />
        </div>
      ),
    },
    {
      id: "remark",
      header: t("channels.remark"),
      size: 160,
      cell: ({ row }) => (
        <EditableCell
          value={row.original.remark || ""}
          onChange={(v) => handleRemarkSave(row.original.userId, v)}
        />
      ),
    },
    {
      id: "actions",
      header: t("channels.actions"),
      size: 80,
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0 text-destructive hover:text-destructive"
          onClick={() => setConfirmRemove({ userId: row.original.userId })}
        >
          <Trash2 size={12} />
        </Button>
      ),
    },
  ];

  const table = useReactTable({
    data: listData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (row) => row.userId,
    initialState: { pagination: { pageSize: 10 } },
  });

  return (
    <>
      <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
        <SheetContent side="right" className="w-[700px] flex flex-col p-0">
          <SheetHeader className="px-6 py-4 border-b">
            <SheetTitle>{t("channels.manageAccessControl")}</SheetTitle>
          </SheetHeader>

          <div className="flex-1 overflow-y-auto px-6 py-4">
            {/* Tabs */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex border rounded-md overflow-hidden">
                {(["whitelist", "blacklist"] as const).map((tab) => (
                  <button
                    key={tab}
                    className={cn(
                      "px-4 py-1.5 text-sm transition-colors",
                      activeTab === tab
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted",
                    )}
                    onClick={() => {
                      setActiveTab(tab);
                      setSelectedRowIds(new Set());
                    }}
                  >
                    {t(`channels.${tab}`)}
                  </button>
                ))}
              </div>
              <Button
                size="sm"
                disabled={!selectedChannel}
                onClick={() => setAddModalOpen(true)}
              >
                <Plus size={14} className="mr-1" />
                {t("channels.addUser")}
              </Button>
            </div>

            {/* Channel select + batch */}
            <div className="flex items-center justify-between mb-3 gap-2">
              <Select
                value={selectedChannel ?? ""}
                onValueChange={(v) => {
                  setSelectedChannel(v);
                  setSelectedRowIds(new Set());
                }}
                disabled={channelKeys.length === 0}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder={t("channels.filterByChannel")} />
                </SelectTrigger>
                <SelectContent>
                  {channelKeys.map((key) => (
                    <SelectItem key={key} value={key}>
                      {getChannelLabel(key as ChannelKey, t)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="flex items-center gap-2">
                {selectedRowIds.size > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {t("channels.selectedCount", {
                      count: selectedRowIds.size,
                    })}
                  </span>
                )}
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={selectedRowIds.size === 0}
                  onClick={() => setConfirmBatch(true)}
                >
                  {batchLoading && (
                    <Loader2 size={12} className="animate-spin mr-1" />
                  )}
                  <Trash2 size={12} className="mr-1" />
                  {t("channels.batchRemove")}
                </Button>
              </div>
            </div>

            {/* Table */}
            {loading ? (
              <div className="flex justify-center items-center h-24">
                <Loader2 className="animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="border rounded-md overflow-hidden">
                <Table>
                  <TableHeader>
                    {table.getHeaderGroups().map((hg) => (
                      <TableRow key={hg.id}>
                        <TableHead className="w-10">
                          <input
                            type="checkbox"
                            className="cursor-pointer"
                            checked={
                              listData.length > 0 &&
                              listData.every((r) =>
                                selectedRowIds.has(r.userId),
                              )
                            }
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedRowIds(
                                  new Set(listData.map((r) => r.userId)),
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
                    {table.getRowModel().rows.map((row) => (
                      <TableRow
                        key={row.id}
                        className={
                          selectedRowIds.has(row.original.userId)
                            ? "bg-muted/50"
                            : ""
                        }
                      >
                        <TableCell>
                          <input
                            type="checkbox"
                            className="cursor-pointer"
                            checked={selectedRowIds.has(row.original.userId)}
                            onChange={(e) => {
                              const next = new Set(selectedRowIds);
                              if (e.target.checked)
                                next.add(row.original.userId);
                              else next.delete(row.original.userId);
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
                    ))}
                    {table.getRowModel().rows.length === 0 && (
                      <TableRow>
                        <TableCell
                          colSpan={columns.length + 1}
                          className="h-16 text-center text-muted-foreground text-sm"
                        >
                          {activeTab === "whitelist"
                            ? t("channels.noWhitelistUsers")
                            : t("channels.noBlacklistUsers")}
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

      {/* Add user dialog */}
      <Dialog
        open={addModalOpen}
        onOpenChange={(o) => !o && setAddModalOpen(false)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("channels.addUser")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>{t("channels.userId")}</Label>
              <Input
                placeholder={t("channels.addUserPlaceholder")}
                value={newUserId}
                onChange={(e) => setNewUserId(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t("channels.username")}</Label>
              <Input
                placeholder={t("channels.usernamePlaceholder")}
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t("channels.remark")}</Label>
              <Input
                placeholder={t("channels.remarkPlaceholder")}
                value={newRemark}
                onChange={(e) => setNewRemark(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setAddModalOpen(false);
                setNewUserId("");
                setNewUsername("");
                setNewRemark("");
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              disabled={!newUserId.trim()}
              onClick={async () => {
                await handleAdd();
                setAddModalOpen(false);
              }}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirm single remove */}
      <AlertDialog
        open={!!confirmRemove}
        onOpenChange={(o) => !o && setConfirmRemove(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("channels.batchRemove")}</AlertDialogTitle>
            <AlertDialogDescription>
              {`Remove ${confirmRemove?.userId}?`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (confirmRemove) await handleRemove(confirmRemove.userId);
                setConfirmRemove(null);
              }}
            >
              {t("channels.batchRemove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm batch remove */}
      <AlertDialog
        open={confirmBatch}
        onOpenChange={(o) => !o && setConfirmBatch(false)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("channels.batchRemove")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("channels.batchRemoveConfirm", { count: selectedRowIds.size })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                await handleBatchRemove();
                setConfirmBatch(false);
              }}
            >
              {t("channels.batchRemove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
