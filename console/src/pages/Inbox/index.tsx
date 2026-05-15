import { useEffect, useMemo, useState } from "react";
import {
  Tabs,
  Empty,
  Button,
  Badge,
  Collapse,
  Pagination,
  Checkbox,
  Popconfirm,
  message,
  Modal,
  Descriptions,
  Tag,
  Spin,
  Select,
} from "antd";
import {
  BulbOutlined,
  CopyOutlined,
  DownOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { PackageOpen, Bell } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
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
import styles from "./index.module.less";

type TabKey = "approvals" | "messages";
const INBOX_TAB_STORAGE_KEY = "qwenpaw.inbox.activeTab";
const PUSH_MESSAGES_PAGE_SIZE = 5;

const resolveInitialTab = (): TabKey => {
  if (typeof window === "undefined") {
    return "messages";
  }
  const stored = window.localStorage.getItem(INBOX_TAB_STORAGE_KEY);
  if (stored === "approvals" || stored === "messages") {
    return stored;
  }
  return "messages";
};

const renderMarkdownText = (text: string, className: string) => (
  <div className={className}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
  </div>
);

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
    if (!selectedAgentFilter) {
      return pushMessages;
    }
    return pushMessages.filter(
      (message) =>
        (message.metadata?.agentId || DEFAULT_AGENT_ID) === selectedAgentFilter,
    );
  }, [pushMessages, selectedAgentFilter]);
  const pushMessageAgentOptions = useMemo(() => {
    const ids = new Set<string>(
      filteredPushMessages.map(
        (message) => message.metadata?.agentId || DEFAULT_AGENT_ID,
      ),
    );
    pushMessages.forEach((message) => {
      ids.add(message.metadata?.agentId || DEFAULT_AGENT_ID);
    });
    const options = Array.from(ids)
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b))
      .map((id) => ({
        value: id,
        label:
          agentDisplayNameById.get(id) ||
          (id === DEFAULT_AGENT_ID ? t("agent.defaultDisplayName") : id),
      }));
    return options;
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
    message.success(t("approval.approved"));
  };

  const handleRejectRequest = async (
    requestId: string,
    rootSessionId: string,
  ) => {
    await commandsApi.sendApprovalCommand("deny", requestId, rootSessionId);
    setApprovals((prev) =>
      prev.filter((item) => item.request_id !== requestId),
    );
    message.success(t("approval.denied"));
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
    if (messagesPage > totalMessagePages) {
      setMessagesPage(totalMessagePages);
    }
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
      message.warning(t("inbox.messageNotFound"));
      return;
    }
    openMessageDetail(found);
  };

  const handleMarkAllRead = async () => {
    if (summary.pushMessages.unread <= 0) {
      message.info(t("inbox.markAllReadNoUnread"));
      return;
    }
    setMarkAllReading(true);
    try {
      const updated = await markAllMessagesAsRead();
      message.success(t("inbox.markAllReadSuccess", { count: updated }));
    } catch {
      message.error(t("common.operationFailed"));
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
      message.success(t("inbox.batchDeleteSuccess", { count: deletedCount }));
    }
  };

  const tabItems = [
    {
      key: "messages",
      label: (
        <span className={styles.tabLabel}>
          <Bell size={16} />
          {t("inbox.tabPushMessages")}
          {summary.pushMessages.unread > 0 && (
            <Badge count={summary.pushMessages.unread} color="#ff7f16" />
          )}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          <div className={styles.messagesToolbar}>
            <div className={styles.messagesSelectionTools}>
              <Select
                size="middle"
                value={selectedAgentFilter}
                onChange={(value) => setSelectedAgentFilter(value)}
                allowClear
                options={pushMessageAgentOptions}
                style={{ width: 180 }}
                placeholder={t("inbox.filterByAgent")}
              />
            </div>
            <div className={styles.messagesSelectionTools}>
              {batchMode ? (
                <>
                  <Checkbox
                    checked={allCurrentPageSelected}
                    onChange={(event) =>
                      handleToggleSelectCurrentPage(event.target.checked)
                    }
                    disabled={currentPageMessageIds.length <= 0}
                  >
                    {t("inbox.selectAllCurrentPage")}
                  </Checkbox>
                  <span className={styles.selectedCountText}>
                    {t("inbox.selectedItems", {
                      count: selectedMessageIds.length,
                    })}
                  </span>
                  <Popconfirm
                    title={t("inbox.batchDeleteConfirm", {
                      count: selectedMessageIds.length,
                    })}
                    onConfirm={() => void handleBatchDeleteMessages()}
                    okText={t("common.confirm")}
                    cancelText={t("common.cancel")}
                    disabled={selectedMessageIds.length <= 0}
                  >
                    <Button danger disabled={selectedMessageIds.length <= 0}>
                      {t("inbox.batchDeleteButton")}
                    </Button>
                  </Popconfirm>
                  <Button
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
                  <Button onClick={() => setBatchMode(true)}>
                    {t("inbox.batchOperation")}
                  </Button>
                  <Button
                    onClick={() => void handleMarkAllRead()}
                    loading={markAllReading}
                    disabled={summary.pushMessages.unread <= 0}
                  >
                    {t("inbox.markAllRead")}
                  </Button>
                </>
              )}
            </div>
          </div>
          {filteredPushMessages.length > 0 ? (
            <div className={styles.cardList}>
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
              <div className={styles.paginationWrap}>
                <Pagination
                  current={messagesPage}
                  total={filteredPushMessages.length}
                  pageSize={PUSH_MESSAGES_PAGE_SIZE}
                  onChange={setMessagesPage}
                  showSizeChanger={false}
                />
              </div>
            </div>
          ) : (
            <Empty description={t("inbox.emptyPush")} />
          )}
        </div>
      ),
    },
    {
      key: "approvals",
      label: (
        <span className={styles.tabLabel}>
          <PackageOpen size={16} />
          {t("inbox.tabApprovals")}
          {urgentApprovalCount > 0 && (
            <Badge count={urgentApprovalCount} color="#ff7f16" />
          )}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          {pendingApprovals.length > 0 ? (
            <div className={styles.cardList}>
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
                          prev.filter((item) => item.request_id !== requestId),
                        );
                      });
                  }}
                />
              ))}
            </div>
          ) : (
            <Empty description={t("inbox.emptyApprovals")} />
          )}
        </div>
      ),
    },
  ];

  return (
    <div className={styles.inboxPage}>
      <PageHeader items={[{ title: t("inbox.title") }]} extra={null} />

      <div className={styles.pageContent}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as TabKey)}
          items={tabItems}
          className={styles.inboxTabs}
        />
      </div>
      <Modal
        open={detailOpen}
        onCancel={closeDetail}
        footer={null}
        width={820}
        title={getDetailModalTitle(selectedMessage, t)}
      >
        {selectedMessage ? (
          <div className={styles.messageDetail}>
            <Descriptions
              size="small"
              column={2}
              bordered
              className={styles.messageDetailMeta}
            >
              <Descriptions.Item label={t("inbox.detailStatus")}>
                <Tag
                  color={
                    selectedMessage.metadata?.status === "error"
                      ? "error"
                      : "success"
                  }
                >
                  {selectedMessage.metadata?.status || "success"}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t("inbox.detailAgent")}>
                {(() => {
                  const agentId =
                    selectedMessage.metadata?.agentId || DEFAULT_AGENT_ID;
                  return (
                    agentDisplayNameById.get(agentId) ||
                    (agentId === DEFAULT_AGENT_ID
                      ? t("agent.defaultDisplayName")
                      : agentId)
                  );
                })()}
              </Descriptions.Item>
              <Descriptions.Item label={t("inbox.detailReceivedAt")}>
                {selectedMessage.createdAt.toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label={t("inbox.detailTaskId")}>
                {selectedMessage.id || "-"}
              </Descriptions.Item>
            </Descriptions>

            <div className={styles.messageDetailBlock}>
              <div className={styles.messageDetailLabel}>
                {t("inbox.detailExecutionTrace")}
              </div>
              {traceLoading ? (
                <div className={styles.traceLoading}>
                  <Spin size="small" />
                </div>
              ) : traceEvents.length > 0 ? (
                <div
                  ref={traceContainerRef as React.RefObject<HTMLDivElement>}
                  className={styles.traceContainer}
                  onScroll={(event) => {
                    handleTraceScroll(event.currentTarget.scrollTop);
                  }}
                >
                  <div className={styles.traceTimeline}>
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
                        <BulbOutlined />
                      ) : kind.toLowerCase().includes("tool") ? (
                        <ToolOutlined />
                      ) : null;
                      const collapseKey = `trace-${item.at}-${index}`;
                      const isPanelActive = !!expandedTraceMap[collapseKey];
                      return (
                        <div
                          key={`${item.at}-${index}`}
                          className={styles.traceEntry}
                        >
                          {eventRecord.role === "user" && traceText ? (
                            <div className={styles.traceUserRow}>
                              <div className={styles.traceUserMessage}>
                                {traceText}
                              </div>
                            </div>
                          ) : kind === "push_preview" && traceText ? (
                            renderMarkdownText(
                              traceText,
                              `${styles.traceAssistantMessage} ${styles.traceStandaloneAligned}`,
                            )
                          ) : collapsible ? (
                            <Collapse
                              bordered={false}
                              ghost
                              activeKey={isPanelActive ? [collapseKey] : []}
                              onChange={(keys) => {
                                const nextActive = Array.isArray(keys)
                                  ? keys.length > 0
                                  : Boolean(keys);
                                toggleTracePanel(collapseKey, nextActive);
                              }}
                              className={`${styles.traceCollapse} ${
                                isPanelActive ? styles.traceCollapseActive : ""
                              }`}
                              expandIcon={() => null}
                              items={[
                                {
                                  key: collapseKey,
                                  label: (
                                    <div className={styles.traceFoldHeader}>
                                      {foldIcon ? (
                                        <span className={styles.traceFoldIcon}>
                                          {foldIcon}
                                        </span>
                                      ) : null}
                                      <span className={styles.traceFoldTitle}>
                                        {collapseTitle}
                                      </span>
                                      <span
                                        className={`${
                                          styles.traceInlineChevron
                                        } ${
                                          isPanelActive
                                            ? styles.traceInlineChevronActive
                                            : ""
                                        }`}
                                      >
                                        <DownOutlined />
                                      </span>
                                    </div>
                                  ),
                                  children:
                                    item.renderKind === "tool_pair" ? (
                                      <div className={styles.toolDetailWrap}>
                                        {item.toolInput ? (
                                          <div className={styles.toolSection}>
                                            <div
                                              className={styles.traceCodeHeader}
                                            >
                                              <div
                                                className={
                                                  styles.traceCodeTitle
                                                }
                                              >
                                                Input
                                              </div>
                                              <button
                                                type="button"
                                                className={
                                                  styles.traceCodeCopyBtn
                                                }
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
                                                <CopyOutlined />
                                              </button>
                                            </div>
                                            <pre
                                              className={styles.toolCodeBlock}
                                            >
                                              {formatToolBlockContent(
                                                formatToolInput(item.toolInput),
                                              )}
                                            </pre>
                                          </div>
                                        ) : null}
                                        {item.toolOutput ? (
                                          <div className={styles.toolSection}>
                                            <div
                                              className={styles.traceCodeHeader}
                                            >
                                              <div
                                                className={
                                                  styles.traceCodeTitle
                                                }
                                              >
                                                Output
                                              </div>
                                              <button
                                                type="button"
                                                className={
                                                  styles.traceCodeCopyBtn
                                                }
                                                onClick={() =>
                                                  void copyTraceBlock(
                                                    formatToolBlockContent(
                                                      item.toolOutput || "",
                                                    ),
                                                  )
                                                }
                                                title={t("common.copy")}
                                              >
                                                <CopyOutlined />
                                              </button>
                                            </div>
                                            <pre
                                              className={styles.toolCodeBlock}
                                            >
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
                                        styles.traceMarkdownBlock,
                                      )
                                    ) : (
                                      <pre className={styles.traceJsonBlock}>
                                        {JSON.stringify(eventRecord, null, 2)}
                                      </pre>
                                    ),
                                },
                              ]}
                            />
                          ) : traceText ? (
                            renderMarkdownText(
                              traceText,
                              `${styles.traceMarkdownBlock} ${styles.traceStandaloneAligned}`,
                            )
                          ) : (
                            <pre
                              className={`${styles.traceJsonBlock} ${styles.traceStandaloneAligned}`}
                            >
                              {JSON.stringify(eventRecord, null, 2)}
                            </pre>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className={styles.traceEmpty}>
                  {t("inbox.detailTraceEmpty")}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
