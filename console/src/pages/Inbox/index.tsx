import { useEffect, useMemo, useState } from "react";
import {
  Lightbulb,
  Copy,
  Wrench,
  PackageOpen,
  Bell,
  Loader2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
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
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { cn } from "@/lib/utils";
import { ApprovalCard as GlobalApprovalCard } from "../../components/ApprovalCard/ApprovalCard";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { commandsApi } from "../../api/modules/commands";
import { chatApi } from "../../api/modules/chat";
import sessionApi from "../Chat/sessionApi";
import { PushMessageCard } from "./components";
import { useInboxData } from "./hooks/useInboxData";
import { useTraceViewer } from "./hooks/useTraceViewer";
import { useAgentStore } from "../../stores/agentStore";
import {
  DEFAULT_AGENT_ID,
  getAgentDisplayName,
} from "../../utils/agentDisplayName";
import {
  getDetailModalTitle,
  formatToolInput,
  formatToolBlockContent,
} from "./utils/traceUtils";

type TabKey = "approvals" | "messages";
const INBOX_TAB_STORAGE_KEY = "qwenpaw.inbox.activeTab";
const PUSH_MESSAGES_PAGE_SIZE = 5;

const resolveInitialTab = (): TabKey => {
  if (typeof window === "undefined") return "messages";
  const stored = window.localStorage.getItem(INBOX_TAB_STORAGE_KEY);
  if (stored === "approvals" || stored === "messages") return stored;
  return "messages";
};

const renderMarkdownText = (text: string, className: string) => (
  <div className={className}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
  </div>
);

/** Simple pagination — replaces antd Pagination */
function SimplePagination({
  current,
  total,
  pageSize,
  onChange,
}: {
  current: number;
  total: number;
  pageSize: number;
  onChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-1 mt-4">
      <Button
        variant="outline"
        size="sm"
        disabled={current <= 1}
        onClick={() => onChange(current - 1)}
      >
        Prev
      </Button>
      {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
        <Button
          key={page}
          variant={page === current ? "default" : "outline"}
          size="sm"
          className={
            page === current
              ? "bg-primary text-primary-foreground hover:bg-primary/90 border-0"
              : ""
          }
          onClick={() => onChange(page)}
        >
          {page}
        </Button>
      ))}
      <Button
        variant="outline"
        size="sm"
        disabled={current >= totalPages}
        onClick={() => onChange(current + 1)}
      >
        Next
      </Button>
    </div>
  );
}

export default function InboxPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabKey>(resolveInitialTab);
  const [markAllReading, setMarkAllReading] = useState(false);
  const [selectedAgentFilter, setSelectedAgentFilter] = useState<
    string | undefined
  >(undefined);
  const [messagesPage, setMessagesPage] = useState(1);
  const [selectedMessageIds, setSelectedMessageIds] = useState<string[]>([]);
  const [batchMode, setBatchMode] = useState(false);
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const agents = useAgentStore((state) => state.agents);
  const { approvals: pendingApprovals, setApprovals } = useApprovalContext();
  const {
    summary,
    pushMessages,
    markMessageAsRead,
    markAllMessagesAsRead,
    deleteMessage,
    deleteMessages,
  } = useInboxData();
  const agentDisplayNameById = useMemo(
    () =>
      new Map(agents.map((agent) => [agent.id, getAgentDisplayName(agent, t)])),
    [agents, t],
  );
  const filteredPushMessages = useMemo(() => {
    if (!selectedAgentFilter) return pushMessages;
    return pushMessages.filter(
      (msg) =>
        (msg.metadata?.agentId || DEFAULT_AGENT_ID) === selectedAgentFilter,
    );
  }, [pushMessages, selectedAgentFilter]);

  const pushMessageAgentOptions = useMemo(() => {
    const ids = new Set<string>(
      filteredPushMessages.map(
        (msg) => msg.metadata?.agentId || DEFAULT_AGENT_ID,
      ),
    );
    pushMessages.forEach((msg) => {
      ids.add(msg.metadata?.agentId || DEFAULT_AGENT_ID);
    });
    return Array.from(ids)
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b))
      .map((id) => ({
        value: id,
        label:
          agentDisplayNameById.get(id) ||
          (id === DEFAULT_AGENT_ID ? t("agent.defaultDisplayName") : id),
      }));
  }, [agentDisplayNameById, filteredPushMessages, pushMessages, t]);

  const urgentApprovalCount = useMemo(
    () =>
      pendingApprovals.filter((item) =>
        ["high", "critical"].includes(item.severity?.toLowerCase?.() || ""),
      ).length,
    [pendingApprovals],
  );

  const pagedPushMessages = useMemo(() => {
    const start = (messagesPage - 1) * PUSH_MESSAGES_PAGE_SIZE;
    return filteredPushMessages.slice(start, start + PUSH_MESSAGES_PAGE_SIZE);
  }, [filteredPushMessages, messagesPage]);

  const currentPageMessageIds = useMemo(
    () => pagedPushMessages.map((item) => item.id),
    [pagedPushMessages],
  );

  const allCurrentPageSelected = useMemo(
    () =>
      currentPageMessageIds.length > 0 &&
      currentPageMessageIds.every((id) => selectedMessageIds.includes(id)),
    [currentPageMessageIds, selectedMessageIds],
  );

  const totalMessagePages = Math.max(
    1,
    Math.ceil(filteredPushMessages.length / PUSH_MESSAGES_PAGE_SIZE),
  );

  const handleApproveRequest = async (
    requestId: string,
    rootSessionId: string,
  ) => {
    await commandsApi.sendApprovalCommand("approve", requestId, rootSessionId);
    setApprovals((prev) =>
      prev.filter((item) => item.request_id !== requestId),
    );
    toast.success(t("approval.approved"));
  };

  const handleRejectRequest = async (
    requestId: string,
    rootSessionId: string,
  ) => {
    await commandsApi.sendApprovalCommand("deny", requestId, rootSessionId);
    setApprovals((prev) =>
      prev.filter((item) => item.request_id !== requestId),
    );
    toast.success(t("approval.denied"));
  };

  const handleCancelTask = async (rootSessionId: string) => {
    const resolvedChatId =
      sessionApi.getRealIdForSession(rootSessionId) ?? rootSessionId;
    await chatApi.stopChat(resolvedChatId);
    setApprovals((prev) =>
      prev.filter((item) => item.root_session_id !== rootSessionId),
    );
  };

  const {
    detailOpen,
    selectedMessage,
    traceLoading,
    traceEvents,
    expandedTraceMap,
    traceContainerRef,
    openMessageDetail,
    closeDetail,
    toggleTracePanel,
    copyTraceBlock,
    handleTraceScroll,
  } = useTraceViewer(markMessageAsRead);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(INBOX_TAB_STORAGE_KEY, activeTab);
    }
  }, [activeTab]);

  useEffect(() => {
    if (messagesPage > totalMessagePages) setMessagesPage(totalMessagePages);
  }, [messagesPage, totalMessagePages]);

  useEffect(() => {
    const validIdSet = new Set(pushMessages.map((item) => item.id));
    setSelectedMessageIds((prev) => prev.filter((id) => validIdSet.has(id)));
  }, [pushMessages]);

  useEffect(() => {
    setMessagesPage(1);
  }, [selectedAgentFilter]);

  const handleViewMessage = (messageId: string) => {
    const found = pushMessages.find((item) => item.id === messageId);
    if (!found) {
      toast.warning(t("inbox.messageNotFound"));
      return;
    }
    openMessageDetail(found);
  };

  const handleMarkAllRead = async () => {
    if (summary.pushMessages.unread <= 0) {
      toast.info(t("inbox.markAllReadNoUnread"));
      return;
    }
    setMarkAllReading(true);
    try {
      const updated = await markAllMessagesAsRead();
      toast.success(t("inbox.markAllReadSuccess", { count: updated }));
    } catch {
      toast.error(t("common.operationFailed"));
    } finally {
      setMarkAllReading(false);
    }
  };

  const handleToggleMessageSelection = (
    messageId: string,
    checked: boolean,
  ) => {
    setSelectedMessageIds((prev) => {
      if (checked) {
        if (prev.includes(messageId)) return prev;
        return [...prev, messageId];
      }
      return prev.filter((id) => id !== messageId);
    });
  };

  const handleToggleSelectCurrentPage = (checked: boolean) => {
    setSelectedMessageIds((prev) => {
      const pageSet = new Set(currentPageMessageIds);
      if (checked) {
        const merged = new Set(prev);
        currentPageMessageIds.forEach((id) => merged.add(id));
        return Array.from(merged);
      }
      return prev.filter((id) => !pageSet.has(id));
    });
  };

  const handleBatchDeleteMessages = async () => {
    if (!selectedMessageIds.length) return;
    const deletedCount = await deleteMessages(selectedMessageIds);
    setSelectedMessageIds([]);
    if (deletedCount > 0) {
      toast.success(t("inbox.batchDeleteSuccess", { count: deletedCount }));
    }
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <PageHeader items={[{ title: t("inbox.title") }]} extra={null} />

      <div className="flex-1 overflow-y-auto min-h-0 px-8 pb-7">
        <Tabs
          value={activeTab}
          onValueChange={(key) => setActiveTab(key as TabKey)}
        >
          <TabsList className="mb-4">
            <TabsTrigger
              value="messages"
              className="inline-flex items-center gap-2 text-[15px]"
            >
              <Bell size={15} />
              {t("inbox.tabPushMessages")}
              {summary.pushMessages.unread > 0 && (
                <Badge className="ml-1 bg-primary text-primary-foreground border-0 text-[10px] px-1.5 py-0 h-4">
                  {summary.pushMessages.unread}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger
              value="approvals"
              className="inline-flex items-center gap-2 text-[15px]"
            >
              <PackageOpen size={15} />
              {t("inbox.tabApprovals")}
              {urgentApprovalCount > 0 && (
                <Badge className="ml-1 bg-primary text-primary-foreground border-0 text-[10px] px-1.5 py-0 h-4">
                  {urgentApprovalCount}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          {/* Messages Tab */}
          <TabsContent value="messages" className="pb-2">
            <div className="flex justify-between items-center gap-3 mb-3">
              <div className="flex items-center gap-2.5">
                <Select
                  value={selectedAgentFilter ?? "__all__"}
                  onValueChange={(value) =>
                    setSelectedAgentFilter(
                      value === "__all__" ? undefined : value,
                    )
                  }
                >
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder={t("inbox.filterByAgent")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">
                      {t("inbox.filterByAgent")}
                    </SelectItem>
                    {pushMessageAgentOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center gap-2.5">
                {batchMode ? (
                  <>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={allCurrentPageSelected}
                        onCheckedChange={(checked) =>
                          handleToggleSelectCurrentPage(Boolean(checked))
                        }
                        disabled={currentPageMessageIds.length <= 0}
                        id="select-all"
                      />
                      <label
                        htmlFor="select-all"
                        className="text-sm cursor-pointer"
                      >
                        {t("inbox.selectAllCurrentPage")}
                      </label>
                    </div>
                    <span className="text-sm text-muted-foreground text-[12px]">
                      {t("inbox.selectedItems", {
                        count: selectedMessageIds.length,
                      })}
                    </span>
                    <AlertDialog
                      open={batchDeleteOpen}
                      onOpenChange={setBatchDeleteOpen}
                    >
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={selectedMessageIds.length <= 0}
                        >
                          {t("inbox.batchDeleteButton")}
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>
                            {t("inbox.batchDeleteConfirm", {
                              count: selectedMessageIds.length,
                            })}
                          </AlertDialogTitle>
                          <AlertDialogDescription>
                            {t(
                              "common.actionCannotBeUndone",
                              "This action cannot be undone.",
                            )}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>
                            {t("common.cancel")}
                          </AlertDialogCancel>
                          <AlertDialogAction
                            className="bg-destructive text-white hover:bg-destructive/90"
                            onClick={() => void handleBatchDeleteMessages()}
                          >
                            {t("common.confirm")}
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setBatchMode(false);
                        setSelectedMessageIds([]);
                      }}
                    >
                      {t("inbox.exitBatch")}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setBatchMode(true)}
                    >
                      {t("inbox.batchOperation")}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void handleMarkAllRead()}
                      disabled={
                        markAllReading || summary.pushMessages.unread <= 0
                      }
                    >
                      {markAllReading && (
                        <Loader2 size={14} className="animate-spin" />
                      )}
                      {t("inbox.markAllRead")}
                    </Button>
                  </>
                )}
              </div>
            </div>

            {filteredPushMessages.length > 0 ? (
              <div className="flex flex-col gap-2.5">
                {pagedPushMessages.map((item) => (
                  <PushMessageCard
                    key={item.id}
                    message={item}
                    onMarkAsRead={markMessageAsRead}
                    onDelete={deleteMessage}
                    onView={handleViewMessage}
                    selected={selectedMessageIds.includes(item.id)}
                    onSelectChange={
                      batchMode ? handleToggleMessageSelection : undefined
                    }
                  />
                ))}
                <SimplePagination
                  current={messagesPage}
                  total={filteredPushMessages.length}
                  pageSize={PUSH_MESSAGES_PAGE_SIZE}
                  onChange={setMessagesPage}
                />
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
                <PackageOpen size={36} className="opacity-40" />
                <p className="text-sm">{t("inbox.emptyPush")}</p>
              </div>
            )}
          </TabsContent>

          {/* Approvals Tab */}
          <TabsContent value="approvals" className="pb-2">
            {pendingApprovals.length > 0 ? (
              <div className="flex flex-col gap-2.5">
                {pendingApprovals.map((approval) => (
                  <GlobalApprovalCard
                    key={approval.request_id}
                    requestId={approval.request_id}
                    agentId={approval.agent_id}
                    ownerAgentId={approval.owner_agent_id}
                    showInboxAgentContext
                    toolName={approval.tool_name}
                    severity={approval.severity}
                    findingsCount={approval.findings_count}
                    findingsSummary={approval.findings_summary}
                    toolParams={approval.tool_params}
                    createdAt={approval.created_at}
                    timeoutSeconds={approval.timeout_seconds}
                    sessionId={approval.session_id}
                    rootSessionId={approval.root_session_id}
                    onApprove={() =>
                      handleApproveRequest(
                        approval.request_id,
                        approval.root_session_id,
                      )
                    }
                    onDeny={() =>
                      handleRejectRequest(
                        approval.request_id,
                        approval.root_session_id,
                      )
                    }
                    onCancel={() => {
                      void handleCancelTask(approval.root_session_id);
                    }}
                    onAcknowledge={(requestId) => {
                      return commandsApi
                        .sendApprovalCommand(
                          "deny",
                          requestId,
                          approval.root_session_id,
                        )
                        .catch(() => undefined)
                        .then(() => {
                          setApprovals((prev) =>
                            prev.filter(
                              (item) => item.request_id !== requestId,
                            ),
                          );
                        });
                    }}
                  />
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
                <PackageOpen size={36} className="opacity-40" />
                <p className="text-sm">{t("inbox.emptyApprovals")}</p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>

      {/* Message detail dialog */}
      <Dialog
        open={detailOpen}
        onOpenChange={(open) => {
          if (!open) closeDetail();
        }}
      >
        <DialogContent className="max-w-[820px] w-full max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{getDetailModalTitle(selectedMessage, t)}</DialogTitle>
          </DialogHeader>

          {selectedMessage ? (
            <div className="flex flex-col gap-3.5">
              {/* Descriptions replacement — simple grid */}
              <div className="grid grid-cols-2 gap-0 border border-border rounded-md overflow-hidden text-sm mb-4">
                {[
                  {
                    label: t("inbox.detailStatus"),
                    value: (
                      <Badge
                        variant={
                          selectedMessage.metadata?.status === "error"
                            ? "destructive"
                            : "secondary"
                        }
                        className={cn(
                          "text-[11px] border-0",
                          selectedMessage.metadata?.status !== "error" &&
                            "bg-green-100 text-green-800 dark-mode:bg-green-900/30 dark-mode:text-green-400",
                        )}
                      >
                        {selectedMessage.metadata?.status || "success"}
                      </Badge>
                    ),
                  },
                  {
                    label: t("inbox.detailAgent"),
                    value: (() => {
                      const agentId =
                        selectedMessage.metadata?.agentId || DEFAULT_AGENT_ID;
                      return (
                        agentDisplayNameById.get(agentId) ||
                        (agentId === DEFAULT_AGENT_ID
                          ? t("agent.defaultDisplayName")
                          : agentId)
                      );
                    })(),
                  },
                  {
                    label: t("inbox.detailReceivedAt"),
                    value: selectedMessage.createdAt.toLocaleString(),
                  },
                  {
                    label: t("inbox.detailTaskId"),
                    value: selectedMessage.id || "-",
                  },
                ].map(({ label, value }) => (
                  <div
                    key={label}
                    className="flex border-b border-border last:border-b-0 [&:nth-child(odd)]:border-r"
                  >
                    <div className="bg-muted/50 px-3 py-2 text-xs font-medium text-muted-foreground w-32 shrink-0">
                      {label}
                    </div>
                    <div className="px-3 py-2 text-xs text-foreground flex items-center">
                      {value}
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex flex-col gap-2">
                <div className="text-[12px] font-semibold text-foreground/55 dark-mode:text-white/55 mb-3">
                  {t("inbox.detailExecutionTrace")}
                </div>

                {traceLoading ? (
                  <div className="flex justify-center py-8 px-3 rounded-lg border border-dashed border-black/15 dark-mode:border-white/18 text-foreground/55 dark-mode:text-white/55 mx-auto w-full">
                    <Loader2
                      size={20}
                      className="animate-spin text-muted-foreground"
                    />
                  </div>
                ) : traceEvents.length > 0 ? (
                  <div
                    ref={traceContainerRef as React.RefObject<HTMLDivElement>}
                    className="max-h-[420px] overflow-auto"
                    onScroll={(event) => {
                      handleTraceScroll(event.currentTarget.scrollTop);
                    }}
                  >
                    <div className="flex flex-col">
                      {traceEvents.map((item, index) => {
                        const {
                          eventRecord,
                          eventType,
                          traceText,
                          collapsible,
                          collapseTitle,
                        } = item;
                        const kind = eventType;
                        const foldIcon = kind
                          .toLowerCase()
                          .includes("thinking") ? (
                          <Lightbulb size={13} />
                        ) : kind.toLowerCase().includes("tool") ? (
                          <Wrench size={13} />
                        ) : null;
                        const collapseKey = `trace-${item.at}-${index}`;
                        const isPanelActive = !!expandedTraceMap[collapseKey];

                        return (
                          <div
                            key={`${item.at}-${index}`}
                            className="flex flex-col gap-1.5 py-1.5"
                          >
                            {eventRecord.role === "user" && traceText ? (
                              <div className="flex justify-end pr-2.5">
                                <div className="max-w-[min(82%,680px)] bg-black/[0.06] dark-mode:bg-white/[0.08] text-foreground dark-mode:text-white/90 rounded-[14px] px-3 py-2.5 text-sm leading-relaxed border border-black/[0.06] dark-mode:border-white/15 whitespace-pre-wrap break-words">
                                  {traceText}
                                </div>
                              </div>
                            ) : kind === "push_preview" && traceText ? (
                              renderMarkdownText(
                                traceText,
                                "text-sm leading-[1.65] text-foreground/88 dark-mode:text-white/85 whitespace-normal overflow-anywhere ml-1.5 mr-2.5",
                              )
                            ) : collapsible ? (
                              <Accordion
                                type="single"
                                collapsible
                                value={isPanelActive ? collapseKey : ""}
                                onValueChange={(value) => {
                                  toggleTracePanel(
                                    collapseKey,
                                    value === collapseKey,
                                  );
                                }}
                                className={cn(
                                  "border-none rounded-lg bg-transparent transition-colors hover:bg-black/[0.02] dark-mode:hover:bg-white/[0.04]",
                                  isPanelActive && "bg-muted",
                                )}
                              >
                                <AccordionItem
                                  value={collapseKey}
                                  className="border-0"
                                >
                                  <AccordionTrigger className="py-0 hover:no-underline flex items-center gap-2 w-full">
                                    <div className="flex items-center gap-1.5">
                                      {foldIcon && (
                                        <span className="inline-flex items-center justify-center text-foreground/50 dark-mode:text-white/55">
                                          {foldIcon}
                                        </span>
                                      )}
                                      <span className="font-medium text-[13px] text-foreground/85 dark-mode:text-white/85">
                                        {collapseTitle}
                                      </span>
                                    </div>
                                  </AccordionTrigger>
                                  <AccordionContent>
                                    {item.renderKind === "tool_pair" ? (
                                      <div className="flex flex-col gap-2.5">
                                        {item.toolInput ? (
                                          <div className="flex flex-col border border-border rounded-lg overflow-hidden bg-card">
                                            <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 bg-muted border-b border-border">
                                              <div className="text-[12px] font-semibold text-foreground/65 dark-mode:text-white/70">
                                                Input
                                              </div>
                                              <button
                                                type="button"
                                                className="border-none bg-transparent text-foreground/50 dark-mode:text-white/55 cursor-pointer p-0.5 hover:text-foreground/80 dark-mode:hover:text-white/85"
                                                onClick={() =>
                                                  void copyTraceBlock(
                                                    formatToolBlockContent(
                                                      formatToolInput(
                                                        item.toolInput || "",
                                                      ),
                                                    ),
                                                  )
                                                }
                                                title={t("common.copy")}
                                              >
                                                <Copy size={13} />
                                              </button>
                                            </div>
                                            <pre className="m-0 rounded-none border-none bg-card px-3 py-2.5 text-[12px] leading-relaxed whitespace-pre overflow-x-auto overflow-y-auto max-h-[220px] font-mono text-foreground/82">
                                              {formatToolBlockContent(
                                                formatToolInput(item.toolInput),
                                              )}
                                            </pre>
                                          </div>
                                        ) : null}
                                        {item.toolOutput ? (
                                          <div className="flex flex-col border border-border rounded-lg overflow-hidden bg-card">
                                            <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 bg-muted border-b border-border">
                                              <div className="text-[12px] font-semibold text-foreground/65 dark-mode:text-white/70">
                                                Output
                                              </div>
                                              <button
                                                type="button"
                                                className="border-none bg-transparent text-foreground/50 dark-mode:text-white/55 cursor-pointer p-0.5 hover:text-foreground/80 dark-mode:hover:text-white/85"
                                                onClick={() =>
                                                  void copyTraceBlock(
                                                    formatToolBlockContent(
                                                      item.toolOutput || "",
                                                    ),
                                                  )
                                                }
                                                title={t("common.copy")}
                                              >
                                                <Copy size={13} />
                                              </button>
                                            </div>
                                            <pre className="m-0 rounded-none border-none bg-card px-3 py-2.5 text-[12px] leading-relaxed whitespace-pre overflow-x-auto overflow-y-auto max-h-[220px] font-mono text-foreground/82">
                                              {formatToolBlockContent(
                                                item.toolOutput,
                                              )}
                                            </pre>
                                          </div>
                                        ) : null}
                                      </div>
                                    ) : traceText ? (
                                      renderMarkdownText(
                                        traceText,
                                        "text-[13px] leading-[1.75] text-foreground/82 dark-mode:text-white/82",
                                      )
                                    ) : (
                                      <pre className="m-0 rounded-lg border border-border px-3 py-2.5 text-[12px] leading-relaxed overflow-x-auto whitespace-pre break-normal text-foreground/82">
                                        {JSON.stringify(eventRecord, null, 2)}
                                      </pre>
                                    )}
                                  </AccordionContent>
                                </AccordionItem>
                              </Accordion>
                            ) : traceText ? (
                              renderMarkdownText(
                                traceText,
                                "text-[13px] leading-[1.75] text-foreground/82 dark-mode:text-white/82 ml-1.5 mr-2.5",
                              )
                            ) : (
                              <pre className="m-0 rounded-lg border border-border px-3 py-2.5 text-[12px] leading-relaxed overflow-x-auto whitespace-pre break-normal text-foreground/82 ml-1.5 mr-2.5">
                                {JSON.stringify(eventRecord, null, 2)}
                              </pre>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground py-4 px-3 rounded-lg border border-dashed border-black/15 dark-mode:border-white/18 dark-mode:text-white/55">
                    {t("inbox.detailTraceEmpty")}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
