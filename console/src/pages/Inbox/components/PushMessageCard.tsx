import { Card, Button, Tag, Avatar, Popconfirm } from "antd";
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
}

const CHANNEL_ICONS = {
  wechat: MessageCircle,
  slack: Hash,
  telegram: Send,
  discord: MessageSquare,
  email: Mail,
};

const CHANNEL_COLORS = {
  wechat: "#07C160",
  slack: "#4A154B",
  telegram: "#0088CC",
  discord: "#5865F2",
  email: "#EA4335",
};

export function PushMessageCard({
  message,
  onMarkAsRead,
  onView,
  onDelete,
}: PushMessageCardProps) {
  const { t } = useTranslation();
  const IconComponent = CHANNEL_ICONS[message.channelType];
  const channelColor = CHANNEL_COLORS[message.channelType];

  return (
    <Card
      className={`${styles.messageCard} ${!message.read ? styles.unread : ""}`}
      hoverable
      bodyStyle={{ padding: 14 }}
      onClick={() => onView(message.id)}
    >
      <div className={styles.cardHeader}>
        <div className={styles.channelInfo}>
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
        </div>
      </div>
      <div className={styles.cardBody}>
        <h4 className={styles.messageTitle}>{message.title}</h4>
        <p className={styles.messageContent}>{message.content}</p>
      </div>
      <div className={styles.cardFooter}>
        <div className={styles.actions}>
          {!message.read ? (
            <Button
              size="small"
              type="primary"
              onClick={(event) => {
                event.stopPropagation();
                onMarkAsRead(message.id);
              }}
            >
              {t("inbox.markRead")}
            </Button>
          ) : null}
          <Popconfirm
            title={t("inbox.deleteMessageConfirm")}
            onConfirm={() => onDelete(message.id)}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Button
              size="small"
              danger
              icon={<Trash2 size={14} />}
              onClick={(event) => event.stopPropagation()}
            >
              {t("common.delete")}
            </Button>
          </Popconfirm>
        </div>
      </div>
    </Card>
  );
}
