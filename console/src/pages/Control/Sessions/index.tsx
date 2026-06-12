import { useEffect, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Form, Modal, Table, Button } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import { MenuOutlined, SettingOutlined } from "@ant-design/icons";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  createColumns,
  DEFAULT_SESSION_COLUMN_ORDER,
  FilterBar,
  SessionDrawer,
  type Session,
  type SessionColumnKey,
} from "./components";
import { useSessions } from "./useSessions";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

const SESSION_COLUMN_ORDER_STORAGE_KEY = "qwenpaw.sessions.columnOrder";
const FIXED_SESSION_COLUMN_KEY: SessionColumnKey = "action";
const CONFIGURABLE_SESSION_COLUMN_ORDER = DEFAULT_SESSION_COLUMN_ORDER.filter(
  (key) => key !== FIXED_SESSION_COLUMN_KEY,
);

const normalizeColumnOrder = (order: unknown): SessionColumnKey[] => {
  const validKeys = new Set<SessionColumnKey>(DEFAULT_SESSION_COLUMN_ORDER);
  const customOrder = Array.isArray(order) ? order : [];
  const normalized = customOrder.filter(
    (key): key is SessionColumnKey =>
      typeof key === "string" && validKeys.has(key as SessionColumnKey),
  );

  DEFAULT_SESSION_COLUMN_ORDER.forEach((key) => {
    if (!normalized.includes(key)) normalized.push(key);
  });

  return normalized;
};

const normalizeConfigurableColumnOrder = (
  order: unknown,
): SessionColumnKey[] => {
  const validKeys = new Set<SessionColumnKey>(
    CONFIGURABLE_SESSION_COLUMN_ORDER,
  );
  const customOrder = Array.isArray(order) ? order : [];
  const normalized = customOrder.filter(
    (key): key is SessionColumnKey =>
      typeof key === "string" && validKeys.has(key as SessionColumnKey),
  );

  CONFIGURABLE_SESSION_COLUMN_ORDER.forEach((key) => {
    if (!normalized.includes(key)) normalized.push(key);
  });

  return normalized;
};

interface SortableColumnOrderItemProps {
  columnKey: SessionColumnKey;
  index: number;
  label: string;
}

function SortableColumnOrderItem({
  columnKey,
  index,
  label,
}: SortableColumnOrderItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: columnKey });

  const itemStyle: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      className={[
        styles.columnOrderItem,
        isDragging ? styles.columnOrderItemDragging : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={itemStyle}
      {...attributes}
      {...listeners}
    >
      <span className={styles.columnOrderIndex}>{index + 1}</span>
      <span className={styles.columnOrderDragIcon} aria-hidden="true">
        <MenuOutlined />
      </span>
      <span className={styles.columnOrderLabel}>{label}</span>
    </div>
  );
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
  const [form] = Form.useForm<Session>();

  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  // Filter states
  const [filterUserId, setFilterUserId] = useState<string>("");
  const [filterChannel, setFilterChannel] = useState<string>("");
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [columnOrder, setColumnOrder] = useState<SessionColumnKey[]>(
    DEFAULT_SESSION_COLUMN_ORDER,
  );
  const [columnSettingsOpen, setColumnSettingsOpen] = useState(false);
  const [draftColumnOrder, setDraftColumnOrder] = useState<SessionColumnKey[]>(
    CONFIGURABLE_SESSION_COLUMN_ORDER,
  );
  const columnOrderSensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 4 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const { message } = useAppMessage();

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(
        SESSION_COLUMN_ORDER_STORAGE_KEY,
      );
      if (!stored) return;

      const normalized = normalizeColumnOrder(JSON.parse(stored));
      setColumnOrder(normalized);
      setDraftColumnOrder(normalizeConfigurableColumnOrder(normalized));
    } catch (error) {
      console.error("❌ Failed to load session column order:", error);
      window.localStorage.removeItem(SESSION_COLUMN_ORDER_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    const fetchChannelTypes = async () => {
      try {
        const types = await api.listChannelTypes();
        setAvailableChannels(types);
      } catch (error) {
        console.error("❌ Failed to load channel types:", error);
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

    setFilteredSessions(filtered);
  }, [sessions, filterUserId, filterChannel]);

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

  const handleView = (session: Session) => {
    navigate(`/chat/${encodeURIComponent(session.id)}`);
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
        const success = await batchDeleteSessions(selectedRowKeys as string[]);
        if (success) {
          setSelectedRowKeys([]);
        }
      },
    });
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

  const handleOpenColumnSettings = () => {
    setDraftColumnOrder(normalizeConfigurableColumnOrder(columnOrder));
    setColumnSettingsOpen(true);
  };

  const handleColumnDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;

    setDraftColumnOrder((current) => {
      const activeKey = active.id as SessionColumnKey;
      const overKey = over.id as SessionColumnKey;
      const oldIndex = current.indexOf(activeKey);
      const newIndex = current.indexOf(overKey);

      if (oldIndex < 0 || newIndex < 0) {
        return current;
      }

      return arrayMove(current, oldIndex, newIndex);
    });
  };

  const handleSaveColumnOrder = () => {
    const normalized = [
      ...normalizeConfigurableColumnOrder(draftColumnOrder),
      FIXED_SESSION_COLUMN_KEY,
    ];
    setColumnOrder(normalized);
    window.localStorage.setItem(
      SESSION_COLUMN_ORDER_STORAGE_KEY,
      JSON.stringify(normalized),
    );
    setColumnSettingsOpen(false);
  };

  const handleResetColumnOrder = () => {
    setDraftColumnOrder(CONFIGURABLE_SESSION_COLUMN_ORDER);
  };

  const columns = createColumns({
    onEdit: handleEdit,
    onDelete: handleDelete,
    onView: handleView,
    t,
    columnOrder,
  });

  const columnLabels: Record<SessionColumnKey, string> = {
    id: t("sessions.columns.id"),
    name: t("sessions.columns.name"),
    session_id: t("sessions.columns.sessionId"),
    user_id: t("sessions.columns.userId"),
    channel: t("sessions.columns.channel"),
    created_at: t("sessions.columns.createdAt"),
    updated_at: t("sessions.columns.updatedAt"),
    action: t("sessions.columns.action"),
  };

  const rowSelection = {
    fixed: true,
    columnWidth: 50,
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys);
    },
  };

  return (
    <div className={styles.sessionsPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("sessions.title") }]}
        extra={
          <div className={styles.headerRight}>
            <FilterBar
              filterUserId={filterUserId}
              filterChannel={filterChannel}
              uniqueChannels={availableChannels}
              onUserIdChange={setFilterUserId}
              onChannelChange={setFilterChannel}
            />
            <Button
              icon={<SettingOutlined />}
              onClick={handleOpenColumnSettings}
            >
              {t("sessions.columnOrder")}
            </Button>
            {selectedRowKeys.length > 0 && (
              <Button type="primary" danger onClick={handleBatchDelete}>
                {t("sessions.batchDeleteButton")} ({selectedRowKeys.length})
              </Button>
            )}
          </div>
        }
      />

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

      <SessionDrawer
        open={drawerOpen}
        editingSession={editingSession}
        form={form}
        saving={saving}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />

      <Modal
        title={t("sessions.columnOrder")}
        open={columnSettingsOpen}
        onOk={handleSaveColumnOrder}
        onCancel={() => setColumnSettingsOpen(false)}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        width={420}
        footer={[
          <Button key="reset" onClick={handleResetColumnOrder}>
            {t("common.reset")}
          </Button>,
          <Button key="cancel" onClick={() => setColumnSettingsOpen(false)}>
            {t("common.cancel")}
          </Button>,
          <Button key="save" type="primary" onClick={handleSaveColumnOrder}>
            {t("common.save")}
          </Button>,
        ]}
      >
        <DndContext
          sensors={columnOrderSensors}
          collisionDetection={closestCenter}
          onDragEnd={handleColumnDragEnd}
        >
          <SortableContext
            items={draftColumnOrder}
            strategy={verticalListSortingStrategy}
          >
            <div className={styles.columnOrderList}>
              {draftColumnOrder.map((key, index) => (
                <SortableColumnOrderItem
                  key={key}
                  columnKey={key}
                  index={index}
                  label={columnLabels[key]}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      </Modal>
    </div>
  );
}

export default SessionsPage;
