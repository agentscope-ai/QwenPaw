import { useDeferredValue, useEffect, useLayoutEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LoaderCircle, RefreshCcw, TriangleAlert } from "lucide-react";
import {
  Button,
  Card,
  Checkbox,
  Form,
  Modal,
  Table,
  Tabs,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import {
  useSessionColumns,
  FilterBar,
  SessionDrawer,
  formatTime,
  type Session,
} from "./components";
import { useSessions } from "./useSessions";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import { ChannelIcon } from "../Channels/components";
import styles from "./index.module.less";

const MOBILE_PAGE_SIZE = 20;
const COMPACT_LAYOUT_QUERY = "(max-width: 1024px)";

function SessionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    agentId,
    sessions,
    loading,
    error,
    refreshSessions,
    updateSession,
    deleteSession,
    batchDeleteSessions,
    archiveSession,
    unarchiveSession,
    batchArchiveSessions,
    batchUnarchiveSessions,
    activeTab,
    setActiveTab,
    activeCount,
    archivedCount,
  } = useSessions();
  const [filteredSessions, setFilteredSessions] = useState<Session[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<Session>();

  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [selectionAgentId, setSelectionAgentId] = useState<string | null>(null);
  const [mobileVisibleCount, setMobileVisibleCount] =
    useState(MOBILE_PAGE_SIZE);

  // Filter states
  const [filterUserId, setFilterUserId] = useState<string>("");
  const [filterChannel, setFilterChannel] = useState<string>("");
  const [filterTitle, setFilterTitle] = useState<string>("");
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [isCompactLayout, setIsCompactLayout] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(COMPACT_LAYOUT_QUERY);
    setIsCompactLayout(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsCompactLayout(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const deferredTitle = useDeferredValue(filterTitle);

  const { message } = useAppMessage();

  useEffect(() => {
    const fetchChannelTypes = async () => {
      try {
        const types = await api.listChannelTypes();
        setAvailableChannels(types);
      } catch (error) {
        console.error("Failed to load channel types:", error);
      }
    };
    fetchChannelTypes();
  }, []);

  // Filter effect
  useEffect(() => {
    let filtered: Session[] = sessions;

    if (filterUserId) {
      filtered = filtered.filter(
        (session: Session) =>
          session.user_id?.toLowerCase().includes(filterUserId.toLowerCase()),
      );
    }

    if (filterChannel) {
      filtered = filtered.filter(
        (session: Session) => session.channel === filterChannel,
      );
    }

    if (deferredTitle) {
      filtered = filtered.filter((session: Session) => {
        const name = session.name || "";
        return name.toLowerCase().includes(deferredTitle.toLowerCase());
      });
    }

    setFilteredSessions(filtered);
  }, [sessions, filterUserId, filterChannel, deferredTitle]);

  // Clear selection when switching tabs
  useEffect(() => {
    setSelectedRowKeys([]);
    setSelectionAgentId(null);
  }, [activeTab]);

  useLayoutEffect(() => {
    setSelectedRowKeys([]);
    setSelectionAgentId(null);
    setDrawerOpen(false);
    setEditingSession(null);
    setEditingAgentId(null);
  }, [agentId]);

  useEffect(() => {
    setMobileVisibleCount(MOBILE_PAGE_SIZE);
  }, [activeTab, filterUserId, filterChannel, deferredTitle]);

  const handleEdit = (session: Session) => {
    setEditingSession(session);
    setEditingAgentId(agentId);
    form.setFieldsValue({
      name: session.name,
      user_id: session.user_id,
      session_id: session.session_id,
      channel: session.channel,
    });
    setDrawerOpen(true);
  };

  const handleDelete = (sessionId: string) => {
    const ownerAgentId = agentId;
    Modal.confirm({
      title: t("sessions.confirmDelete"),
      content: t("sessions.deleteConfirm"),
      okText: t("cronJobs.deleteText"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        await deleteSession(sessionId, ownerAgentId);
      },
    });
  };

  const handleView = (session: Session) => {
    navigate(`/chat/${encodeURIComponent(session.id)}`);
  };

  const handleArchiveToggle = async (session: Session) => {
    if (activeTab === "archived") {
      await unarchiveSession(session.id, agentId);
    } else {
      await archiveSession(session.id, agentId);
    }
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning(t("sessions.batchDeleteConfirm", { count: 0 }));
      return;
    }

    Modal.confirm({
      title: t("sessions.confirmDelete"),
      content: t("sessions.batchDeleteConfirm", {
        count: selectedRowKeys.length,
      }),
      okText: t("cronJobs.deleteText"),
      okType: "danger",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        const success = await batchDeleteSessions(
          selectedRowKeys as string[],
          selectionAgentId ?? "",
        );
        if (success) {
          setSelectedRowKeys([]);
        }
      },
    });
  };

  const handleBatchArchive = async () => {
    if (selectedRowKeys.length === 0) return;
    const success = await batchArchiveSessions(
      selectedRowKeys as string[],
      selectionAgentId ?? "",
    );
    if (success) {
      setSelectedRowKeys([]);
    }
  };

  const handleBatchUnarchive = async () => {
    if (selectedRowKeys.length === 0) return;
    const success = await batchUnarchiveSessions(
      selectedRowKeys as string[],
      selectionAgentId ?? "",
    );
    if (success) {
      setSelectedRowKeys([]);
    }
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSession(null);
    setEditingAgentId(null);
  };

  const handleSubmit = async (values: Session) => {
    if (editingSession) {
      setSaving(true);
      try {
        const updated = {
          name: values.name,
        };
        const success = await updateSession(
          editingSession.id,
          updated,
          editingAgentId ?? "",
        );
        if (success) {
          setDrawerOpen(false);
        }
      } finally {
        setSaving(false);
      }
    }
  };

  const isArchivedTab = activeTab === "archived";

  const columns = useSessionColumns({
    onEdit: handleEdit,
    onDelete: handleDelete,
    onView: handleView,
    onArchiveToggle: handleArchiveToggle,
    isArchivedTab,
  });

  const rowSelection = {
    fixed: true,
    columnWidth: 50,
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys);
      setSelectionAgentId(newSelectedRowKeys.length > 0 ? agentId : null);
    },
  };

  const mobileSessions = filteredSessions.slice(0, mobileVisibleCount);
  const hasMoreMobileSessions = mobileVisibleCount < filteredSessions.length;

  const handleMobileSelectionChange = (sessionId: string, checked: boolean) => {
    setSelectionAgentId(agentId);
    setSelectedRowKeys((current) =>
      checked
        ? Array.from(new Set([...current, sessionId]))
        : current.filter((key) => key !== sessionId),
    );
  };

  const handleLoadMoreMobileSessions = () => {
    setMobileVisibleCount((current) =>
      Math.min(current + MOBILE_PAGE_SIZE, filteredSessions.length),
    );
  };

  return (
    <div className={styles.sessionsPage}>
      <PageHeader
        className={styles.pageHeader}
        items={[{ title: t("nav.control") }, { title: t("sessions.title") }]}
        extra={
          <div className={styles.headerRight}>
            <FilterBar
              isMobile={isCompactLayout}
              filterUserId={filterUserId}
              filterChannel={filterChannel}
              filterTitle={filterTitle}
              uniqueChannels={availableChannels}
              onUserIdChange={setFilterUserId}
              onChannelChange={setFilterChannel}
              onTitleChange={setFilterTitle}
            />
            {selectedRowKeys.length > 0 && (
              <>
                {isArchivedTab ? (
                  <Button onClick={handleBatchUnarchive}>
                    {t("sessions.archive.batchUnaction", "Batch Unarchive")} (
                    {selectedRowKeys.length})
                  </Button>
                ) : (
                  <Button onClick={handleBatchArchive}>
                    {t("sessions.archive.batchAction", "Batch Archive")} (
                    {selectedRowKeys.length})
                  </Button>
                )}
                <Button type="primary" danger onClick={handleBatchDelete}>
                  {t("sessions.batchDeleteButton")} ({selectedRowKeys.length})
                </Button>
              </>
            )}
          </div>
        }
      />

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as "active" | "archived")}
        items={[
          {
            key: "active",
            label: `${t("sessions.activeTab", "Active")} (${activeCount})`,
          },
          {
            key: "archived",
            label: `${t(
              "sessions.archivedTab",
              "Archived",
            )} (${archivedCount})`,
          },
        ]}
        style={{ padding: "0 16px" }}
      />

      {isCompactLayout ? (
        <div className={styles.mobileCardList}>
          {loading && mobileSessions.length === 0 && (
            <div
              className={styles.mobileListState}
              role="status"
              aria-live="polite"
            >
              <LoaderCircle
                className={styles.mobileLoadingIcon}
                size={24}
                aria-hidden="true"
              />
              <span>{t("sessions.loading")}</span>
            </div>
          )}
          {!loading && error && (
            <div
              className={`${styles.mobileListState} ${styles.mobileErrorState}`}
              role="alert"
            >
              <TriangleAlert size={24} aria-hidden="true" />
              <span>{t("sessions.loadFailed")}</span>
              <Button
                className={styles.mobileRetryButton}
                onClick={() => void refreshSessions()}
              >
                <RefreshCcw size={16} aria-hidden="true" />
                {t("common.retry")}
              </Button>
            </div>
          )}
          {mobileSessions.map((session) => (
            <Card
              key={session.id}
              className={styles.mobileSessionCard}
              size="small"
              styles={{ body: { padding: 24 } }}
            >
              <div className={styles.mobileSessionHeader}>
                <Checkbox
                  className={styles.mobileSelection}
                  checked={selectedRowKeys.includes(session.id)}
                  aria-label={t("sessions.selectSession", {
                    defaultValue: "Select {{name}}",
                    name: session.name || session.id,
                  })}
                  onChange={(event) =>
                    handleMobileSelectionChange(
                      session.id,
                      event.target.checked,
                    )
                  }
                />
                <span className={styles.mobileSessionName}>
                  {session.name || session.id}
                </span>
                <span className={styles.mobileSessionChannel}>
                  <ChannelIcon channelKey={session.channel} size={24} />
                </span>
              </div>
              <div className={styles.mobileSessionMeta}>
                <span>ID: {session.id}</span>
                {session.user_id && <span>User: {session.user_id}</span>}
                <span>Created: {formatTime(session.created_at)}</span>
              </div>
              <div className={styles.mobileSessionActions}>
                {isArchivedTab ? (
                  <>
                    <Button
                      size="small"
                      className={styles.mobileActionBtn}
                      onClick={() => handleArchiveToggle(session)}
                    >
                      {t("sessions.archive.unaction", "Unarchive")}
                    </Button>
                    <Button
                      size="small"
                      className={styles.mobileActionBtn}
                      danger
                      onClick={() => handleDelete(session.id)}
                    >
                      {t("common.delete")}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      size="small"
                      className={styles.mobileActionBtn}
                      onClick={() => handleEdit(session)}
                    >
                      {t("common.edit")}
                    </Button>
                    <Button
                      size="small"
                      className={styles.mobileActionBtn}
                      onClick={() => handleView(session)}
                    >
                      {t("common.view")}
                    </Button>
                    <Button
                      size="small"
                      className={styles.mobileActionBtn}
                      onClick={() => handleArchiveToggle(session)}
                    >
                      {t("sessions.archive.action", "Archive")}
                    </Button>
                    <Button
                      size="small"
                      className={styles.mobileActionBtn}
                      danger
                      onClick={() => handleDelete(session.id)}
                    >
                      {t("common.delete")}
                    </Button>
                  </>
                )}
              </div>
            </Card>
          ))}
          {hasMoreMobileSessions && (
            <div className={styles.mobileLoadMore}>
              <Button
                className={styles.mobileLoadMoreButton}
                onClick={handleLoadMoreMobileSessions}
              >
                {t("common.loadMore", "Load more")}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <Card className={styles.tableCard} styles={{ body: { padding: 0 } }}>
          <Table
            columns={columns}
            dataSource={filteredSessions}
            loading={loading}
            rowKey="id"
            rowSelection={rowSelection}
            rowClassName={(record) =>
              selectedRowKeys.includes(record.id) ? styles.selectedRow : ""
            }
            scroll={{ x: 1500 }}
            pagination={{
              pageSize: 10,
              showSizeChanger: false,
            }}
          />
        </Card>
      )}

      <SessionDrawer
        open={drawerOpen}
        editingSession={editingSession}
        form={form}
        saving={saving}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default SessionsPage;
