import { useEffect, useMemo, useState } from "react";
import {
  Tabs,
  Empty,
  Button,
  Badge,
  Collapse,
  message,
  Modal,
  Descriptions,
  Tag,
  Spin,
} from "antd";
import {
  BulbOutlined,
  CopyOutlined,
  DownOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { PackageOpen, Bell, Sparkles, Plus } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import api from "../../api";
import {
  ApprovalCard,
  CreateHarvestModal,
  HarvestCard,
  MagazineStackViewer,
  PushMessageCard,
} from "./components";
import { useInboxData } from "./hooks/useInboxData";
import type { HarvestInstance, PushMessage } from "./types";
import styles from "./index.module.less";

type TabKey = "approvals" | "messages" | "harvests";
const INBOX_TAB_STORAGE_KEY = "qwenpaw.inbox.activeTab";

const resolveInitialTab = (): TabKey => {
  if (typeof window === "undefined") {
    return "messages";
  }
  const stored = window.localStorage.getItem(INBOX_TAB_STORAGE_KEY);
  if (
    stored === "approvals" ||
    stored === "messages" ||
    stored === "harvests"
  ) {
    return stored;
  }
  return "messages";
};

const buildContentFallbackTrace = (messageItem: PushMessage) => ({
  events: messageItem.content
    ? [
        {
          at: messageItem.createdAt.getTime() / 1000,
          event: {
            kind: "push_preview",
            text: messageItem.content,
          },
        },
      ]
    : [],
});

const isCollapsibleTraceEvent = (
  kind: string,
  event: Record<string, unknown>,
): boolean => {
  const lowerKind = kind.toLowerCase();
  if (lowerKind.includes("thinking") || lowerKind.includes("tool")) {
    return true;
  }
  // Keep tool-like payloads folded by default even when kind is generic.
  if (
    typeof event.tool === "string" ||
    typeof event.tool_name === "string" ||
    typeof event.function_name === "string"
  ) {
    return true;
  }
  return false;
};

const extractTraceText = (event: Record<string, unknown>): string => {
  if (typeof event.text === "string" && event.text.trim()) {
    return event.text.trim();
  }
  if (typeof event.message === "string" && event.message.trim()) {
    return event.message.trim();
  }
  if (typeof event.content === "string" && event.content.trim()) {
    return event.content.trim();
  }
  return "";
};

const normalizeTraceKind = (event: Record<string, unknown>): string =>
  typeof event.kind === "string" ? (event.kind as string) : "event";

type TraceDisplayItem = {
  at: number;
  eventType: string;
  eventRecord: Record<string, unknown>;
  traceText: string;
  collapsible: boolean;
  collapseTitle: string;
  toolInput?: string;
  toolOutput?: string;
  renderKind: "tool_pair" | "normal";
};

const shouldHideTraceEvent = (
  eventType: string,
  eventRecord: Record<string, unknown>,
): boolean => {
  const lowerType = eventType.toLowerCase();
  if (lowerType === "response_completed") return true;
  if (
    !extractTraceText(eventRecord) &&
    !isCollapsibleTraceEvent(eventType, eventRecord)
  ) {
    return true;
  }
  return false;
};

const getTraceFoldTitle = (
  eventType: string,
  eventRecord: Record<string, unknown>,
): string => {
  const lowerType = eventType.toLowerCase();
  if (lowerType.includes("thinking")) return "Thinking";
  if (lowerType.includes("tool")) {
    if (
      typeof eventRecord.tool_name === "string" &&
      eventRecord.tool_name.trim()
    ) {
      return eventRecord.tool_name;
    }
    if (typeof eventRecord.tool === "string" && eventRecord.tool.trim()) {
      return eventRecord.tool;
    }
    return "Tool";
  }
  return "Details";
};

const getTraceFoldIcon = (eventType: string) => {
  const lowerType = eventType.toLowerCase();
  if (lowerType.includes("thinking")) {
    return <BulbOutlined />;
  }
  if (lowerType.includes("tool")) {
    return <ToolOutlined />;
  }
  return null;
};

const formatTraceTime = (seconds: number): string => {
  if (!Number.isFinite(seconds)) return "-";
  return new Date(seconds * 1000).toLocaleTimeString([], {
    hour12: false,
  });
};

const getToolFieldText = (
  eventRecord: Record<string, unknown>,
  field: "tool_input" | "tool_output",
): string => {
  const val = eventRecord[field];
  if (typeof val === "string" && val.trim()) return val;
  return "";
};

const formatToolInput = (text: string): string => {
  if (!text.trim()) return "{}";
  return text;
};

const formatToolBlockContent = (text: string): string => {
  const normalized = text.trim();
  if (!normalized) return "";
  try {
    const parsed = JSON.parse(normalized);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return text;
  }
};

const renderMarkdownText = (text: string, className: string) => (
  <div className={className}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
  </div>
);

export default function InboxPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabKey>(resolveInitialTab);
  const [magazineViewerOpen, setMagazineViewerOpen] = useState(false);
  const [currentHarvest, setCurrentHarvest] = useState<HarvestInstance | null>(
    null,
  );
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedMessage, setSelectedMessage] = useState<PushMessage | null>(
    null,
  );
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceData, setTraceData] = useState<{
    events: Array<{ at: number; event: Record<string, unknown> }>;
  } | null>(null);
  const [expandedTraceMap, setExpandedTraceMap] = useState<
    Record<string, boolean>
  >({});
  const {
    summary,
    approvals,
    pushMessages,
    harvests,
    markMessageAsRead,
    deleteMessage,
    approveRequest,
    rejectRequest,
    triggerHarvest,
  } = useInboxData();
  const traceEvents = useMemo<TraceDisplayItem[]>(() => {
    if (!traceData) return [];
    const normalized = traceData.events
      .map((item) => {
        const eventRecord = item.event || {};
        const eventType = normalizeTraceKind(eventRecord);
        return { ...item, eventRecord, eventType };
      })
      .filter(
        (item) => !shouldHideTraceEvent(item.eventType, item.eventRecord),
      );
    const grouped: TraceDisplayItem[] = [];
    for (let i = 0; i < normalized.length; i += 1) {
      const current = normalized[i];
      const traceText = extractTraceText(current.eventRecord);
      const collapsible = isCollapsibleTraceEvent(
        current.eventType,
        current.eventRecord,
      );
      const collapseTitle = getTraceFoldTitle(
        current.eventType,
        current.eventRecord,
      );

      if (current.eventType === "tool_call") {
        const next = normalized[i + 1];
        const currentToolName = String(current.eventRecord.tool_name || "");
        const nextToolName = String(next?.eventRecord?.tool_name || "");
        const canPair =
          !!next &&
          next.eventType === "tool_output" &&
          (!!currentToolName || !!nextToolName)
            ? currentToolName === nextToolName
            : true;
        const toolInput = getToolFieldText(current.eventRecord, "tool_input");
        if (canPair && next) {
          const nextTraceText = extractTraceText(next.eventRecord);
          const toolOutput =
            getToolFieldText(next.eventRecord, "tool_output") || nextTraceText;
          grouped.push({
            at: current.at,
            eventType: "tool_call",
            eventRecord: current.eventRecord,
            traceText,
            collapsible: true,
            collapseTitle:
              collapseTitle ||
              getTraceFoldTitle(next.eventType, next.eventRecord),
            toolInput,
            toolOutput,
            renderKind: "tool_pair",
          });
          i += 1;
          continue;
        }
        grouped.push({
          at: current.at,
          eventType: current.eventType,
          eventRecord: current.eventRecord,
          traceText,
          collapsible: true,
          collapseTitle,
          toolInput,
          renderKind: "tool_pair",
        });
        continue;
      }

      if (current.eventType === "tool_output") {
        const toolOutput =
          getToolFieldText(current.eventRecord, "tool_output") || traceText;
        grouped.push({
          at: current.at,
          eventType: current.eventType,
          eventRecord: current.eventRecord,
          traceText,
          collapsible: true,
          collapseTitle,
          toolOutput,
          renderKind: "tool_pair",
        });
        continue;
      }

      grouped.push({
        at: current.at,
        eventType: current.eventType,
        eventRecord: current.eventRecord,
        traceText,
        collapsible,
        collapseTitle,
        renderKind: "normal",
      });
    }
    return grouped;
  }, [traceData]);

  const copyTraceBlock = async (text: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      message.success(t("common.copied"));
    } catch {
      message.error(t("common.copyFailed"));
    }
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(INBOX_TAB_STORAGE_KEY, activeTab);
    }
  }, [activeTab]);

  useEffect(() => {
    setExpandedTraceMap({});
  }, [traceData, detailOpen]);

  const handleViewMessage = (messageId: string) => {
    const found = pushMessages.find((item) => item.id === messageId);
    if (!found) {
      message.warning(t("inbox.messageNotFound"));
      return;
    }
    if (!found.read) {
      markMessageAsRead(found.id);
    }
    setSelectedMessage(found.read ? found : { ...found, read: true });
    setDetailOpen(true);
    const runId =
      typeof found.metadata?.payload?.run_id === "string"
        ? (found.metadata.payload.run_id as string)
        : undefined;
    if (!runId) {
      setTraceData(buildContentFallbackTrace(found));
      return;
    }
    setTraceLoading(true);
    void api
      .getInboxTrace(runId)
      .then((trace) => {
        setTraceData({
          events: trace.events || [],
        });
      })
      .catch(() => {
        setTraceData(buildContentFallbackTrace(found));
      })
      .finally(() => setTraceLoading(false));
  };

  const handleViewHarvest = (harvestId: string) => {
    const harvest = harvests.find((item) => item.id === harvestId);
    if (!harvest) return;
    setCurrentHarvest(harvest);
    setMagazineViewerOpen(true);
  };

  const handleHarvestSettings = (harvestId: string) => {
    console.info("Open harvest settings:", harvestId);
    message.info(t("inbox.harvestSettingsComingSoon"));
  };

  const tabItems = [
    {
      key: "approvals",
      label: (
        <span className={styles.tabLabel}>
          <PackageOpen size={16} />
          {t("inbox.tabApprovals")}
          {summary.approvals.urgent > 0 && (
            <Badge count={summary.approvals.urgent} />
          )}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          {approvals.length > 0 ? (
            <div className={styles.cardList}>
              {approvals.map((approval) => (
                <ApprovalCard
                  key={approval.id}
                  approval={approval}
                  onApprove={approveRequest}
                  onReject={rejectRequest}
                />
              ))}
            </div>
          ) : (
            <Empty description={t("inbox.emptyApprovals")} />
          )}
        </div>
      ),
    },
    {
      key: "messages",
      label: (
        <span className={styles.tabLabel}>
          <Bell size={16} />
          {t("inbox.tabPushMessages")}
          {summary.pushMessages.unread > 0 && (
            <Badge count={summary.pushMessages.unread} />
          )}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          {pushMessages.length > 0 ? (
            <div className={styles.cardList}>
              {pushMessages.map((item) => (
                <PushMessageCard
                  key={item.id}
                  message={item}
                  onMarkAsRead={markMessageAsRead}
                  onDelete={deleteMessage}
                  onView={handleViewMessage}
                />
              ))}
            </div>
          ) : (
            <Empty description={t("inbox.emptyPush")} />
          )}
        </div>
      ),
    },
    {
      key: "harvests",
      label: (
        <span className={styles.tabLabel}>
          <Sparkles size={16} />
          {t("inbox.tabHarvests")}
          {summary.harvests.active > 0 && (
            <Badge count={summary.harvests.active} status="processing" />
          )}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          {harvests.length > 0 ? (
            <div className={styles.harvestGrid}>
              {harvests.map((harvest) => (
                <HarvestCard
                  key={harvest.id}
                  harvest={harvest}
                  onTrigger={triggerHarvest}
                  onViewAll={handleViewHarvest}
                  onSettings={handleHarvestSettings}
                />
              ))}
            </div>
          ) : (
            <Empty description={t("inbox.emptyHarvests")}>
              <Button
                type="primary"
                icon={<Plus size={16} />}
                onClick={() => setCreateModalOpen(true)}
              >
                {t("inbox.createFirstHarvest")}
              </Button>
            </Empty>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className={styles.inboxPage}>
      <PageHeader
        items={[{ title: t("inbox.title") }]}
        extra={
          activeTab === "harvests" ? (
            <Button
              type="primary"
              icon={<Plus size={16} />}
              onClick={() => setCreateModalOpen(true)}
            >
              {t("inbox.createHarvest")}
            </Button>
          ) : null
        }
      />

      <div className={styles.pageContent}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as TabKey)}
          items={tabItems}
          className={styles.inboxTabs}
        />
      </div>

      {currentHarvest ? (
        <MagazineStackViewer
          open={magazineViewerOpen}
          harvest={currentHarvest}
          onClose={() => setMagazineViewerOpen(false)}
        />
      ) : null}

      <CreateHarvestModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onSubmit={() => {
          message.success(t("inbox.createSuccess"));
          setCreateModalOpen(false);
        }}
      />

      <Modal
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={820}
        title={selectedMessage?.title || t("inbox.messageDetailTitle")}
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
                {selectedMessage.metadata?.agentId || "-"}
              </Descriptions.Item>
              <Descriptions.Item label={t("inbox.detailSource")}>
                {selectedMessage.metadata?.sourceType || "-"}
              </Descriptions.Item>
              <Descriptions.Item label={t("inbox.detailRunId")} span={2}>
                {(selectedMessage.metadata?.payload?.run_id as string) || "-"}
              </Descriptions.Item>
            </Descriptions>

            <div className={styles.messageDetailBlock}>
              <div className={styles.messageDetailLabel}>
                {t("inbox.detailContent")}
              </div>
              <pre className={styles.messageDetailContent}>
                {selectedMessage.content || "-"}
              </pre>
            </div>

            <div className={styles.messageDetailBlock}>
              <div className={styles.messageDetailLabel}>
                {t("inbox.detailExecutionTrace")}
              </div>
              {traceLoading ? (
                <div className={styles.traceLoading}>
                  <Spin size="small" />
                </div>
              ) : traceEvents.length > 0 ? (
                <div className={styles.traceContainer}>
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
                      const foldIcon = getTraceFoldIcon(kind);
                      const collapseKey = `trace-${item.at}-${index}`;
                      const isPanelActive = !!expandedTraceMap[collapseKey];
                      return (
                        <div
                          key={`${item.at}-${index}`}
                          className={styles.traceEntry}
                        >
                          {kind === "push_preview" && traceText ? (
                            renderMarkdownText(
                              traceText,
                              styles.traceAssistantMessage,
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
                                setExpandedTraceMap((prev) => ({
                                  ...prev,
                                  [collapseKey]: nextActive,
                                }));
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
                                      <span className={styles.traceFoldTime}>
                                        {formatTraceTime(item.at)}
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
                              styles.traceMarkdownBlock,
                            )
                          ) : (
                            <pre className={styles.traceJsonBlock}>
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

            {selectedMessage.metadata?.payload ? (
              <div className={styles.messageDetailBlock}>
                <div className={styles.messageDetailLabel}>
                  {t("inbox.detailPayload")}
                </div>
                <pre className={styles.messageDetailPayload}>
                  {JSON.stringify(selectedMessage.metadata.payload, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
