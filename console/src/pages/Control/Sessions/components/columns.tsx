import { Button, Tag } from "@agentscope-ai/design";
import type { TFunction } from "i18next";
import type { ColumnsType } from "antd/es/table";
import { formatTime, type Session } from "./constants";
import { CHANNEL_COLORS } from "../../../../constants/channel";
import styles from "../index.module.less";

export type SessionColumnKey =
  | "id"
  | "name"
  | "session_id"
  | "user_id"
  | "channel"
  | "created_at"
  | "updated_at"
  | "action";

export const DEFAULT_SESSION_COLUMN_ORDER: SessionColumnKey[] = [
  "id",
  "name",
  "session_id",
  "user_id",
  "channel",
  "created_at",
  "updated_at",
  "action",
];

interface ColumnHandlers {
  onEdit: (session: Session) => void;
  onDelete: (sessionId: string) => void;
  onView: (session: Session) => void;
  t: TFunction;
  columnOrder?: SessionColumnKey[];
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
  const columnsByKey: Record<SessionColumnKey, ColumnsType<Session>[number]> = {
    id: {
      title: handlers.t("sessions.columns.id"),
      dataIndex: "id",
      key: "id",
      width: 250,
    },
    name: {
      title: handlers.t("sessions.columns.name"),
      dataIndex: "name",
      key: "name",
      width: 200,
    },
    session_id: {
      title: handlers.t("sessions.columns.sessionId"),
      dataIndex: "session_id",
      key: "session_id",
      width: 180,
    },
    user_id: {
      title: handlers.t("sessions.columns.userId"),
      dataIndex: "user_id",
      key: "user_id",
      width: 150,
    },
    channel: {
      title: handlers.t("sessions.columns.channel"),
      dataIndex: "channel",
      key: "channel",
      width: 120,
      render: (channel: string) => (
        <Tag color={CHANNEL_COLORS[channel] || "default"}>{channel}</Tag>
      ),
    },
    created_at: {
      title: handlers.t("sessions.columns.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (timestamp: string | number | null) => formatTime(timestamp),
      sorter: (a: Session, b: Session) =>
        toUTCTime(a.created_at) - toUTCTime(b.created_at),
    },
    updated_at: {
      title: handlers.t("sessions.columns.updatedAt"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (timestamp: string | number | null) => formatTime(timestamp),
      sorter: (a: Session, b: Session) =>
        toUTCTime(a.updated_at) - toUTCTime(b.updated_at),
      defaultSortOrder: "descend",
    },
    action: {
      title: handlers.t("sessions.columns.action"),
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
  };

  const order = handlers.columnOrder?.length
    ? handlers.columnOrder
    : DEFAULT_SESSION_COLUMN_ORDER;

  return order.map((key) => columnsByKey[key]).filter(Boolean);
};
