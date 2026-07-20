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
import { EyeOff, Eye, Pin, PinOff } from "lucide-react";
import type { AgentSummary } from "../../../../api/types/agents";
import { useTheme } from "../../../../contexts/ThemeContext";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { SortableAgentRow, DragHandle } from "./SortableAgentRow";
import { providerIcon } from "../../Models/components/providerIcon";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import styles from "../index.module.less";

interface AgentTableProps {
  agents: AgentSummary[];
  loading: boolean;
  reordering: boolean;
  onEdit: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onToggle: (agentId: string, currentEnabled: boolean) => void;
  onPin: (agentId: string, currentPinned: boolean) => void;
  onReorder: (activeId: string, overId: string) => void;
}

export function AgentTable({
  agents,
  loading,
  reordering,
  onEdit,
  onDelete,
  onToggle,
  onPin,
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

  const disabledStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.35)", opacity: 1 }
    : {};

  const iconStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.85)" }
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
      render: (_value: unknown, record: AgentSummary) => (
        <Tooltip title={t("agent.dragHandleTooltip")}>
          <span>
            <DragHandle
              disabled={reordering || loading || record.id === "default"}
            />
          </span>
        </Tooltip>
      ),
    },
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      width: 300,
      render: (_text: string, record: AgentSummary) => (
        <Space>
          <AgentStatusIndicator
            status={record.startup_status}
            enabled={record.enabled}
          />
          <RobotOutlined
            style={{
              fontSize: 16,
              opacity: record.enabled ? 1 : 0.5,
            }}
          />
          <span style={{ opacity: record.enabled ? 1 : 0.5 }}>
            {getAgentDisplayName(record, t)}
          </span>
          {(record.id === "default" || record.pinned) && (
            <Pin size={13} aria-label={t("agent.pinned")} />
          )}
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
      title: t("agent.modelColumn"),
      key: "active_model",
      width: 260,
      ellipsis: true,
      render: (_value: unknown, record: AgentSummary) => {
        if (!record.active_model) {
          return (
            <span style={{ opacity: 0.45 }}>{t("agent.modelPlaceholder")}</span>
          );
        }
        return (
          <Space size={6}>
            <img
              src={providerIcon(record.active_model.provider_id)}
              alt=""
              style={{ width: 16, height: 16 }}
            />
            <Tooltip title={record.active_model.model}>
              <span>{record.active_model.model}</span>
            </Tooltip>
          </Space>
        );
      },
    },
    {
      title: t("common.actions"),
      key: "actions",
      render: (_value: unknown, record: AgentSummary) => {
        const startupInProgress =
          record.startup_status === "pending" ||
          record.startup_status === "starting";
        const toggleDisabled = record.id === "default" || startupInProgress;
        const pinActionLabel =
          record.id === "default"
            ? t("agent.defaultPinned")
            : record.pinned
            ? t("agent.unpinAgent")
            : t("agent.pinAgent");

        return (
          <Space>
            <Tooltip title={pinActionLabel}>
              <Button
                type="text"
                size="middle"
                aria-label={pinActionLabel}
                icon={
                  record.id === "default" || record.pinned ? (
                    <Pin size={14} />
                  ) : (
                    <PinOff size={14} />
                  )
                }
                onClick={() => onPin(record.id, Boolean(record.pinned))}
                disabled={record.id === "default"}
                style={record.id === "default" ? disabledStyle : iconStyle}
              />
            </Tooltip>
            <Button
              type="text"
              size="middle"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
              disabled={record.id === "default"}
              style={record.id === "default" ? disabledStyle : iconStyle}
              title={
                record.id === "default"
                  ? t("agent.defaultNotEditable")
                  : undefined
              }
            />
            <Popconfirm
              title={
                record.enabled
                  ? t("agent.disableConfirm")
                  : t("agent.enableConfirm")
              }
              description={
                record.enabled
                  ? t("agent.disableConfirmDesc")
                  : t("agent.enableConfirmDesc")
              }
              onConfirm={() => onToggle(record.id, record.enabled)}
              disabled={toggleDisabled}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="text"
                size="middle"
                icon={record.enabled ? <EyeOff size={14} /> : <Eye size={14} />}
                disabled={toggleDisabled}
                style={record.id === "default" ? disabledStyle : iconStyle}
                title={
                  record.id === "default"
                    ? t("agent.defaultNotDisablable")
                    : startupInProgress
                    ? t("agent.status.waitUntilStarted")
                    : undefined
                }
              />
            </Popconfirm>
            <Popconfirm
              title={t("agent.deleteConfirm")}
              description={t("agent.deleteConfirmDesc")}
              onConfirm={() => onDelete(record.id)}
              disabled={toggleDisabled}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="link"
                size="middle"
                danger
                icon={<DeleteOutlined />}
                disabled={toggleDisabled}
                style={record.id === "default" ? disabledStyle : undefined}
                title={
                  record.id === "default"
                    ? t("agent.defaultNotDeletable")
                    : startupInProgress
                    ? t("agent.status.waitUntilStarted")
                    : undefined
                }
              />
            </Popconfirm>
          </Space>
        );
      },
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
            pagination={false}
          />
        </SortableContext>
      </DndContext>
    </div>
  );
}
