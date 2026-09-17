import { useEffect, useState, useDeferredValue } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Form, Modal, Table, Button, Tabs } from "@agentscope-ai/design";
import { Descriptions, Segmented } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import {
  createColumns,
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
import { inspectSessionForView } from "./viewSession";
import ConversationShareDialog from "../../Chat/components/ConversationShareDialog";

function SessionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    sessions,
    loading,
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
    accessScope,
    setAccessScope,
  } = useSessions();
  const [filteredSessions, setFilteredSessions] = useState<Session[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [saving, setSaving] = useState(false);
  const [sharingSession, setSharingSession] = useState<Session | null>(null);
  const [form] = Form.useForm<Session>();

  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  // Filter states
  const [filterUserId, setFilterUserId] = useState<string>("");
  const [filterChannel, setFilterChannel] = useState<string>("");
  const [filterTitle, setFilterTitle] = useState<string>("");
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
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
  }, [activeTab]);

  const handleEdit = (session: Session) => {
    setEditingSession(session);
    form.setFieldsValue(session as any);
    setDrawerOpen(true);
  };

  const handleDelete = (sessionId: string) => {
    Modal.confirm({
      title: t("sessions.confirmDelete"),
      content: t("sessions.deleteConfirm"),
      okText: t("cronJobs.deleteText"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        await deleteSession(sessionId);
      },
    });
  };

  const handleView = async (session: Session) => {
    try {
      const inspection = await inspectSessionForView(session.id);
      if (inspection.kind === "chat") {
        navigate(`/chat/${encodeURIComponent(session.id)}`);
        return;
      }

      Modal.info({
        title: t("sessions.emptySessionTitle", "会话尚无消息"),
        content: (
          <>
            <p>
              {t(
                "sessions.emptySessionDescription",
                "该会话已创建，但尚未产生用户或智能体消息。以下为现有会话信息。",
              )}
            </p>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="ID">{session.id}</Descriptions.Item>
              <Descriptions.Item label="SessionID">
                {session.session_id}
              </Descriptions.Item>
              <Descriptions.Item label="UserID">
                {session.user_id || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Channel">
                {session.channel || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="CreatedAt">
                {formatTime(session.created_at)}
              </Descriptions.Item>
            </Descriptions>
          </>
        ),
        okText: t("common.confirm", "确定"),
      });
    } catch (error) {
      console.error("Failed to inspect session:", error);
      message.error(t("sessions.viewFailed", "读取会话内容失败"));
    }
  };

  const handleArchiveToggle = async (session: Session) => {
    if (activeTab === "archived") {
      await unarchiveSession(session.id);
    } else {
      await archiveSession(session.id);
    }
  };

  const handleShare = (session: Session) => setSharingSession(session);

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
        const success = await batchDeleteSessions(selectedRowKeys as string[]);
        if (success) {
          setSelectedRowKeys([]);
        }
      },
    });
  };

  const handleBatchArchive = async () => {
    if (selectedRowKeys.length === 0) return;
    const success = await batchArchiveSessions(selectedRowKeys as string[]);
    if (success) {
      setSelectedRowKeys([]);
    }
  };

  const handleBatchUnarchive = async () => {
    if (selectedRowKeys.length === 0) return;
    const success = await batchUnarchiveSessions(selectedRowKeys as string[]);
    if (success) {
      setSelectedRowKeys([]);
    }
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSession(null);
  };

  const handleSubmit = async (values: Session) => {
    if (editingSession) {
      setSaving(true);
      try {
        const updated = {
          name: values.name,
        };
        const success = await updateSession(editingSession.id, updated);
        if (success) {
          setDrawerOpen(false);
        }
      } finally {
        setSaving(false);
      }
    }
  };

  const isArchivedTab = activeTab === "archived";

  const columns = createColumns({
    onEdit: handleEdit,
    onDelete: handleDelete,
    onView: handleView,
    onArchiveToggle: handleArchiveToggle,
    onShare: handleShare,
    isArchivedTab,
  });

  const rowSelection = {
    fixed: true,
    columnWidth: 50,
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys);
    },
    getCheckboxProps: (record: Session) => ({
      disabled: record.access_role === "viewer",
    }),
  };

  return (
    <div className={styles.sessionsPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("sessions.title") }]}
        extra={
          <div className={styles.headerRight}>
            <FilterBar
              isMobile={isMobile}
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

      <div style={{ padding: "0 16px 12px" }}>
        <Segmented
          value={accessScope}
          onChange={(value) =>
            setAccessScope(value as "all" | "owned" | "shared")
          }
          options={[
            { label: t("sessions.scopeAll"), value: "all" },
            { label: t("sessions.scopeOwned"), value: "owned" },
            { label: t("sessions.scopeShared"), value: "shared" },
          ]}
        />
      </div>

      {isMobile ? (
        <div className={styles.mobileCardList}>
          {filteredSessions.map((session) => (
            <Card
              key={session.id}
              className={styles.mobileSessionCard}
              size="small"
              bodyStyle={{ padding: 24 }}
            >
              <div className={styles.mobileSessionHeader}>
                <span className={styles.mobileSessionName}>
                  {session.name || session.id}
                </span>
                <span className={styles.mobileSessionChannel}>
                  <ChannelIcon channelKey={session.channel} size={24} />
                </span>
              </div>
              <div className={styles.mobileSessionMeta}>
                {session.access_role === "viewer" && (
                  <span>
                    {t("chat.sharedReadOnlyBadge")}
                    {session.shared_by ? ` · ${session.shared_by}` : ""}
                  </span>
                )}
                <span>ID: {session.id}</span>
                {session.user_id && <span>User: {session.user_id}</span>}
                <span>Created: {formatTime(session.created_at)}</span>
              </div>
              <div className={styles.mobileSessionActions}>
                {session.access_role === "viewer" ? (
                  <Button
                    size="small"
                    className={styles.mobileActionBtn}
                    onClick={() => handleView(session)}
                  >
                    {t("common.view")}
                  </Button>
                ) : isArchivedTab ? (
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
                      onClick={() => handleShare(session)}
                    >
                      分享
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
        </div>
      ) : (
        <Card className={styles.tableCard} bodyStyle={{ padding: 0 }}>
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
      <ConversationShareDialog
        open={sharingSession !== null}
        chatId={sharingSession?.id ?? null}
        onClose={() => setSharingSession(null)}
      />
    </div>
  );
}

export default SessionsPage;
