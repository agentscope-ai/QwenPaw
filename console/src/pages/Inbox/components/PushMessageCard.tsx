import { Card, Button, Tag, Avatar, Popconfirm, Checkbox } from "antd";
import {
  MessageCircle,
  Hash,
  Send,
  MessageSquare,
  Mail,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { PushMessage } from "../types";
import styles from "./PushMessageCard.module.less";

interface PushMessageCardProps {
  message: PushMessage;
  onMarkAsRead: (id: string) => void;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
  selected?: boolean;
  onSelectChange?: (id: string, checked: boolean) => void;
}

const CHANNEL_ICONS = {
  wechat: MessageCircle,
  slack: Hash,
  telegram: Send,
  discord: MessageSquare,
  email: Mail,
  heartbeat: MessageCircle,
};

const CHANNEL_COLORS = {
  wechat: "#07C160",
  slack: "#4A154B",
  telegram: "#0088CC",
  discord: "#5865F2",
  email: "#EA4335",
  heartbeat: "#5865F2",
};

const normalizeCronTaskName = (title: string): string =>
  title
    .replace(/^(cron result|heartbeat result)\s*[:：]\s*/i, "")
    .replace(/^(定时任务结果|心跳结果)\s*[:：]\s*/i, "")
    .trim();

export function PushMessageCard(props: PushMessageCardProps) {
  const { message, onView, onDelete, selected = false, onSelectChange } = props;
  const { t } = useTranslation();
  const IconComponent = CHANNEL_ICONS[message.channelType];
  const channelColor = CHANNEL_COLORS[message.channelType];
  const sourceType = (message.metadata?.sourceType || "").toLowerCase();
  const isCronMessage = sourceType === "cron";
  const displayTitle = isCronMessage
    ? t("inbox.pushCronHeader", { name: normalizeCronTaskName(message.title) })
    : message.title;

  return (
    <Card
      className={`${styles.messageCard} ${!message.read ? styles.unread : ""}`}
      hoverable
      bodyStyle={{ padding: 14 }}
      onClick={() => onView(message.id)}
    >
      <div className={styles.cardHeader}>
        <div className={styles.channelInfo}>
          {onSelectChange ? (
            <Checkbox
              checked={selected}
              onChange={(event) => {
                event.stopPropagation();
                onSelectChange(message.id, event.target.checked);
              }}
              onClick={(event) => event.stopPropagation()}
            />
          ) : null}
          <Avatar
            size={36}
            style={{ backgroundColor: channelColor }}
            icon={<IconComponent size={18} />}
          />
          <div className={styles.channelDetails}>
            <div className={styles.channelName}>{message.channelName}</div>
            <div className={styles.senderInfo}>
              {t("inbox.from")} {message.sender.username}
            </div>
          </div>
        </div>
        <div className={styles.headerRight}>
          {!message.read ? <span className={styles.unreadDot} /> : null}
          {message.metadata?.priority &&
          message.metadata.priority !== "normal" ? (
            <Tag
              color={
                message.metadata.priority === "urgent" ? "error" : "warning"
              }
            >
              {message.metadata.priority.toUpperCase()}
            </Tag>
          ) : null}
          <Popconfirm
            title={t("inbox.deleteMessageConfirm")}
            onConfirm={(event) => {
              event?.stopPropagation();
              onDelete(message.id);
            }}
            onCancel={(event) => {
              event?.stopPropagation();
            }}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Button
              size="small"
              type="text"
              danger
              icon={<Trash2 size={14} />}
              onClick={(event) => event.stopPropagation()}
            />
          </Popconfirm>
        </div>
      </div>
      <div className={styles.cardBody}>
        <h4 className={styles.messageTitle}>{displayTitle}</h4>
        <p className={styles.messageContent}>{message.content}</p>
      </div>
    </Card>
  );
}
