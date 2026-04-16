import { Table, Tag, Button, Popconfirm } from "antd";
import {
  StopOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import type { Meeting, MeetingStatus, MeetingType } from "@/api/types/meetings";

interface MeetingTableProps {
  meetings: Meeting[];
  loading: boolean;
  onDelete: (meetingId: string) => void;
  onStart: (meetingId: string) => void;
  onStop: (meetingId: string) => void;
  onRestart: (meetingId: string) => void;
  onView: (meeting: Meeting) => void;
  onEdit: (meeting: Meeting) => void;
  onRowClick: (meeting: Meeting) => void;
}

const STATUS_COLOR: Record<MeetingStatus, string> = {
  CREATED: "default",
  INITIALIZED: "processing",
  RUNNING: "processing",
  COMPLETED: "success",
  STOPPED: "warning",
  FAILED: "error",
};

const TYPE_COLOR: Record<MeetingType, string> = {
  REGULAR: "blue",
  TEMPORARY: "orange",
};

function formatDate(iso?: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export function MeetingTable({
  meetings,
  loading,
  onDelete,
  onStart,
  onStop,
  onRestart,
  onView,
  onEdit,
  onRowClick,
}: MeetingTableProps) {
  const { t } = useTranslation();

  const columns: ColumnsType<Meeting> = [
    {
      title: t("meetings.columns.name"),
      dataIndex: "meeting_name",
      key: "meeting_name",
      render: (name: string) => <strong>{name}</strong>,
    },
    {
      title: t("meetings.columns.type"),
      dataIndex: "meeting_type",
      key: "meeting_type",
      render: (type: MeetingType) => <Tag color={TYPE_COLOR[type]}>{type}</Tag>,
    },
    {
      title: t("meetings.columns.status"),
      dataIndex: "status",
      key: "status",
      render: (status: MeetingStatus) => (
        <Tag color={STATUS_COLOR[status]}>{status}</Tag>
      ),
    },
    {
      title: t("meetings.columns.topic"),
      key: "topic",
      render: (_: unknown, record: Meeting) =>
        record.topic?.title || record.topic_title || "-",
    },
    {
      title: t("meetings.columns.participants"),
      key: "participants",
      render: (_: unknown, record: Meeting) =>
        record.participants_count ?? record.participants?.length ?? 0,
    },
    {
      title: t("meetings.columns.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      render: (v: string) => formatDate(v),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 320,
      render: (_: unknown, record: Meeting) => {
        const isRunning = record.status === "RUNNING";
        const isCreated = record.status === "CREATED";
        const isCompleted = record.status === "COMPLETED";
        const isStopped = record.status === "STOPPED";
        const isFailed = record.status === "FAILED";
        const canStart = isCreated;
        const canStop = isRunning;
        const canRestart = isCreated || isCompleted || isStopped || isFailed;

        return (
          <>
            {canStart && (
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={(e) => {
                  e.stopPropagation();
                  onStart(record.meeting_id);
                }}
              >
                {t("meetings.start")}
              </Button>
            )}
            {canStop && (
              <Button
                type="link"
                size="small"
                danger
                icon={<StopOutlined />}
                onClick={(e) => {
                  e.stopPropagation();
                  onStop(record.meeting_id);
                }}
              >
                {t("meetings.stop")}
              </Button>
            )}
            {canRestart && (
              <Popconfirm
                title={t("meetings.restartConfirm")}
                onConfirm={(e) => {
                  e?.stopPropagation();
                  onRestart(record.meeting_id);
                }}
                onCancel={(e) => e?.stopPropagation()}
                okText={t("common.confirm")}
                cancelText={t("common.cancel")}
              >
                <Button
                  type="link"
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={(e) => e.stopPropagation()}
                >
                  {t("meetings.restart")}
                </Button>
              </Popconfirm>
            )}
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={(e) => {
                e.stopPropagation();
                onView(record);
              }}
            >
              {t("meetings.view")}
            </Button>
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(record);
              }}
            >
              {t("meetings.edit")}
            </Button>
            <Popconfirm
              title={t("meetings.deleteConfirm")}
              onConfirm={(e) => {
                e?.stopPropagation();
                onDelete(record.meeting_id);
              }}
              onCancel={(e) => e?.stopPropagation()}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="link"
                danger
                size="small"
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
              >
                {t("meetings.delete")}
              </Button>
            </Popconfirm>
          </>
        );
      },
    },
  ];

  return (
    <Table<Meeting>
      columns={columns}
      dataSource={meetings}
      rowKey="meeting_id"
      loading={loading}
      pagination={{
        pageSize: 20,
        showTotal: (total) => t("common.total", { count: total }),
      }}
      onRow={(record) => ({
        onClick: () => onRowClick(record),
        style: { cursor: "pointer" },
      })}
    />
  );
}
