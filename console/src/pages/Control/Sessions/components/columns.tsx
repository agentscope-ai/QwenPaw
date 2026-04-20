import { Button, Tag } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();

  return [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 250,
    },
    {
      title: "Name",
      dataIndex: "name",
      key: "name",
      width: 200,
    },
    {
      title: "SessionID",
      dataIndex: "session_id",
      key: "session_id",
      width: 180,
    },
    {
      title: "UserID",
      dataIndex: "user_id",
      key: "user_id",
      width: 150,
    },
    {
      title: "Channel",
      dataIndex: "channel",
      key: "channel",
      width: 120,
      render: (channel: string) => (
        <Tag color={CHANNEL_COLORS[channel] || "default"}>{channel}</Tag>
      ),
    },
    {
      title: "CreatedAt",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (timestamp: string | number | null) => formatTime(timestamp),
      sorter: (a: Session, b: Session) =>
        toUTCTime(a.created_at) - toUTCTime(b.created_at),
    },
    {
      title: "UpdatedAt",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (timestamp: string | number | null) => formatTime(timestamp),
      sorter: (a: Session, b: Session) =>
        toUTCTime(a.updated_at) - toUTCTime(b.updated_at),
      defaultSortOrder: "descend",
    },
    {
      title: "Action",
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
            {t("common.edit")}
          </Button>
          <Button
            type="link"
            size="small"
            style={{ color: "#52c41a" }}
            onClick={() => handlers.onView(record)}
          >
            {t("common.view")}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            onClick={() => handlers.onDelete(record.id)}
          >
            {t("common.delete")}
          </Button>
        </div>
      ),
    },
  ];
};
