import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type SortingState,
} from "@tanstack/react-table";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import {
  createColumns,
  FilterBar,
  SessionDrawer,
  type Session,
} from "./components";
import { useSessions } from "./useSessions";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface ConfirmState {
  open: boolean;
  title: string;
  description: string;
  onConfirm: () => Promise<void>;
}

function SessionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    sessions,
    loading,
    updateSession,
    deleteSession,
    batchDeleteSessions,
  } = useSessions();
  const [filteredSessions, setFilteredSessions] = useState<Session[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [saving, setSaving] = useState(false);
  const [formValues, setFormValues] = useState({ name: "" });
  const [sorting, setSorting] = useState<SortingState>([
    { id: "updated_at", desc: true },
  ]);

  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set());

  // Filter states
  const [filterUserId, setFilterUserId] = useState<string>("");
  const [filterChannel, setFilterChannel] = useState<string>("");
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [confirmState, setConfirmState] = useState<ConfirmState>({
    open: false,
    title: "",
    description: "",
    onConfirm: async () => {},
  });

  const { message } = useAppMessage();

  useEffect(() => {
    api
      .listChannelTypes()
      .then(setAvailableChannels)
      .catch((err) => console.error("Failed to load channel types:", err));
  }, []);

  // Filter effect
  useEffect(() => {
    let filtered: Session[] = sessions;
    if (filterUserId) {
      filtered = filtered.filter(
        (s) => s.user_id?.toLowerCase().includes(filterUserId.toLowerCase()),
      );
    }
    if (filterChannel) {
      filtered = filtered.filter((s) => s.channel === filterChannel);
    }
    setFilteredSessions(filtered);
  }, [sessions, filterUserId, filterChannel]);

  const handleEdit = (session: Session) => {
    setEditingSession(session);
    setFormValues({ name: session.name ?? "" });
    setDrawerOpen(true);
  };

  const handleDelete = (sessionId: string) => {
    setConfirmState({
      open: true,
      title: t("sessions.confirmDelete"),
      description: t("sessions.deleteConfirm"),
      onConfirm: async () => {
        await deleteSession(sessionId);
      },
    });
  };

  const handleView = (session: Session) => {
    navigate(`/chat/${encodeURIComponent(session.id)}`);
  };

  const handleBatchDelete = () => {
    if (selectedRowIds.size === 0) {
      message.warning(t("sessions.batchDeleteConfirm", { count: 0 }));
      return;
    }
    setConfirmState({
      open: true,
      title: t("sessions.confirmDelete"),
      description: t("sessions.batchDeleteConfirm", {
        count: selectedRowIds.size,
      }),
      onConfirm: async () => {
        const success = await batchDeleteSessions(Array.from(selectedRowIds));
        if (success) {
          setSelectedRowIds(new Set());
        }
      },
    });
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSession(null);
  };

  const handleSubmit = async () => {
    if (editingSession) {
      setSaving(true);
      try {
        const success = await updateSession(editingSession.id, {
          name: formValues.name,
        });
        if (success) {
          setDrawerOpen(false);
        }
      } finally {
        setSaving(false);
      }
    }
  };

  const columns = createColumns({
    onEdit: handleEdit,
    onDelete: handleDelete,
    onView: handleView,
    t,
  });

  const table = useReactTable({
    data: filteredSessions,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.id,
  });

  return (
    <div className="flex flex-col h-full">
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("sessions.title") }]}
        extra={
          <div className="flex items-center gap-2">
            <FilterBar
              filterUserId={filterUserId}
              filterChannel={filterChannel}
              uniqueChannels={availableChannels}
              onUserIdChange={setFilterUserId}
              onChannelChange={setFilterChannel}
            />
            {selectedRowIds.size > 0 && (
              <Button variant="destructive" onClick={handleBatchDelete}>
                {t("sessions.batchDeleteButton")} ({selectedRowIds.size})
              </Button>
            )}
          </div>
        }
      />

      <Card className="flex-1 mx-4 mb-4">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((hg) => (
                    <TableRow key={hg.id}>
                      <TableHead className="w-12">
                        <input
                          type="checkbox"
                          className="cursor-pointer"
                          checked={
                            filteredSessions.length > 0 &&
                            filteredSessions.every((s) =>
                              selectedRowIds.has(s.id),
                            )
                          }
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedRowIds(
                                new Set(filteredSessions.map((s) => s.id)),
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
                      className={cn(
                        selectedRowIds.has(row.original.id)
                          ? "bg-muted/50"
                          : "",
                      )}
                    >
                      <TableCell>
                        <input
                          type="checkbox"
                          className="cursor-pointer"
                          checked={selectedRowIds.has(row.original.id)}
                          onChange={(e) => {
                            const next = new Set(selectedRowIds);
                            if (e.target.checked) {
                              next.add(row.original.id);
                            } else {
                              next.delete(row.original.id);
                            }
                            setSelectedRowIds(next);
                          }}
                        />
                      </TableCell>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="text-sm">
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
                        className="h-24 text-center text-muted-foreground"
                      >
                        {t("common.noData", "No data")}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <SessionDrawer
        open={drawerOpen}
        editingSession={editingSession}
        formValues={formValues}
        saving={saving}
        onClose={handleDrawerClose}
        onFormChange={(v) => setFormValues((prev) => ({ ...prev, ...v }))}
        onSubmit={handleSubmit}
      />

      <AlertDialog
        open={confirmState.open}
        onOpenChange={(o) =>
          !o && setConfirmState((s) => ({ ...s, open: false }))
        }
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmState.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmState.description}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cronJobs.cancelText")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                await confirmState.onConfirm();
                setConfirmState((s) => ({ ...s, open: false }));
              }}
            >
              {t("cronJobs.deleteText")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default SessionsPage;
