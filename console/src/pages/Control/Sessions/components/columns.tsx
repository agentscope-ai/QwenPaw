import { Button, Tag } from "@agentscope-ai/design";
import type { TFunction } from "i18next";
import type { ColumnsType } from "antd/es/table";
import { formatTime, type Session } from "./constants";
import { CHANNEL_COLORS } from "../../../../constants/channel";
import styles from "../index.module.less";

interface ColumnHandlers {
  onEdit: (session: Session) => void;
  onDelete: (sessionId: string) => void;
  onView: (session: Session) => void;
  t: TFunction;
}

/** Normalize ISO string to UTC for consistent sorting across mixed timezone formats. */
const toUTCTime = (ts: string | null | undefined): number => {
  if (!ts) return 0;
  const normalized =
    /[Z+\-]\d{2}:?\d{2}$/.test(ts) || ts.endsWith("Z") ? ts : ts + "Z";
  return new Date(normalized).getTime();
};

export const createColumns = (
  handlers: ColumnHandlers,
): ColumnsType<Session> => {
  return [
    {
      title: handlers.t("sessions.id"),
      dataIndex: "id",
      key: "id",
      width: 250,
    },
    {
      title: handlers.t("sessions.name"),
      dataIndex: "name",
      key: "name",
      width: 200,
    },
    {
      title: handlers.t("sessions.sessionId"),
      dataIndex: "session_id",
      key: "session_id",
      width: 180,
    },
    {
      title: handlers.t("sessions.userId"),
      dataIndex: "user_id",
      key: "user_id",
      width: 150,
    },
    {
      title: handlers.t("sessions.channel"),
      dataIndex: "channel",
      key: "channel",
      width: 120,
      render: (channel: string) => (
        <Tag color={CHANNEL_COLORS[channel] || "default"}>{channel}</Tag>
      ),
    },
    {
      title: handlers.t("sessions.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (timestamp: string | number | null) => formatTime(timestamp),
      sorter: (a: Session, b: Session) =>
        toUTCTime(a.created_at) - toUTCTime(b.created_at),
    },
    {
      title: handlers.t("sessions.updatedAt"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (timestamp: string | number | null) => formatTime(timestamp),
      sorter: (a: Session, b: Session) =>
        toUTCTime(a.updated_at) - toUTCTime(b.updated_at),
      defaultSortOrder: "descend",
    },
    {
      title: handlers.t("sessions.action"),
      key: "action",
      width: 180,
      fixed: "right",
      render: (_: unknown, record: Session) => (
        <div className={styles.actionColumn}>
          <Button
            type="link"
            size="small"
            onClick={() => handlers.onEdit(record)}
          >
            {handlers.t("common.edit")}
          </Button>
          <Button
            type="link"
            size="small"
            style={{ color: "#52c41a" }}
            onClick={() => handlers.onView(record)}
          >
            {handlers.t("common.view")}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            onClick={() => handlers.onDelete(record.id)}
          >
            {handlers.t("common.delete")}
          </Button>
        </div>
      ),
    },
  ];
};
