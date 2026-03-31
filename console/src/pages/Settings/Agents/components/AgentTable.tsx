import { Table, Button, Space, Popconfirm, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { EditOutlined, DeleteOutlined, RobotOutlined } from "@ant-design/icons";
import type { AgentSummary } from "../../../../api/types/agents";
import { useTheme } from "../../../../contexts/ThemeContext";
import { SortableAgentRow, DragHandle } from "./SortableAgentRow";
import styles from "../index.module.less";

interface AgentTableProps {
  agents: AgentSummary[];
  loading: boolean;
  reordering: boolean;
  onEdit: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onReorder: (activeId: string, overId: string) => void;
}

export function AgentTable({
  agents,
  loading,
  reordering,
  onEdit,
  onDelete,
  onReorder,
}: AgentTableProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 6,
      },
    }),
  );

  // Inline style for disabled buttons — CSS cannot reliably override AntD's disabled styles
  const disabledStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.35)", opacity: 1 }
    : {};

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }

    onReorder(String(active.id), String(over.id));
  };

  const columns: ColumnsType<AgentSummary> = [
    {
      title: "",
      key: "sort",
      width: 56,
      align: "center",
      render: () => (
        <Tooltip title={t("agent.dragHandleTooltip")}>
          <span>
            <DragHandle disabled={reordering || loading} />
          </span>
        </Tooltip>
      ),
    },
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      render: (text: string) => (
        <Space>
          <RobotOutlined style={{ fontSize: 16 }} />
          <span>{text}</span>
        </Space>
      ),
    },
    {
      title: t("agent.id"),
      dataIndex: "id",
      key: "id",
    },
    {
      title: t("agent.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("agent.workspace"),
      dataIndex: "workspace_dir",
      key: "workspace_dir",
      ellipsis: true,
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 300,
      render: (_: any, record: AgentSummary) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
            disabled={record.id === "default"}
            style={record.id === "default" ? disabledStyle : undefined}
            title={
              record.id === "default"
                ? t("agent.defaultNotEditable")
                : undefined
            }
          >
            {t("common.edit")}
          </Button>
          <Popconfirm
            title={t("agent.deleteConfirm")}
            description={t("agent.deleteConfirmDesc")}
            onConfirm={() => onDelete(record.id)}
            disabled={record.id === "default"}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={record.id === "default"}
              style={record.id === "default" ? disabledStyle : undefined}
              title={
                record.id === "default"
                  ? t("agent.defaultNotDeletable")
                  : undefined
              }
            >
              {t("common.delete")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.tableCard}>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={agents.map((agent) => agent.id)}
          strategy={verticalListSortingStrategy}
        >
          <Table
            dataSource={agents}
            columns={columns}
            loading={loading}
            rowKey="id"
            components={{
              body: {
                row: SortableAgentRow,
              },
            }}
            pagination={{
              pageSize: 10,
              showSizeChanger: false,
            }}
          />
        </SortableContext>
      </DndContext>
    </div>
  );
}
