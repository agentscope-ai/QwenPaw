import { Card, Button, Tag, Avatar, Popconfirm, Checkbox, Tooltip } from "antd";
import {
  MessageCircle,
  Hash,
  Send,
  MessageSquare,
  Mail,
  RefreshCw,
  Trash2,
  Archive,
  RotateCcw,
  Brain,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { PushMessage, MessageTab } from "../types";
import styles from "./PushMessageCard.module.less";

interface PushMessageCardProps {
  message: PushMessage;
  /** Which tab this card is rendered in — controls available actions. */
  tab: MessageTab;
  onMarkAsRead: (id: string) => void;
  onView: (id: string) => void;
  onArchive?: (id: string) => void;
  onTrash?: (id: string) => void;
  onRestore?: (id: string) => void;
  onPermanentDelete?: (id: string) => void;
  selected?: boolean;
  onSelectChange?: (id: string, checked: boolean) => void;
}

const CHANNEL_ICONS = {
  wechat: MessageCircle,
  slack: Hash,
  telegram: Send,
  discord: MessageSquare,
  email: Mail,
  memory: Brain,
  heartbeat: MessageCircle,
  skill: RefreshCw,
};

const CHANNEL_COLORS = {
  wechat: "#07C160",
  slack: "#4A154B",
  telegram: "#0088CC",
  discord: "#5865F2",
  email: "#EA4335",
  memory: "#7C3AED",
  heartbeat: "#5865F2",
  skill: "#1677ff",
};

const normalizeCronTaskName = (title: string): string =>
  title
    .replace(/^(cron result|heartbeat result)\s*[:：]\s*/i, "")
    .replace(/^(定时任务结果|心跳结果)\s*[:：]\s*/i, "")
    .trim();

export function PushMessageCard(props: PushMessageCardProps) {
  const {
    message,
    tab,
    onView,
    onArchive,
    onTrash,
    onRestore,
    onPermanentDelete,
    selected = false,
    onSelectChange,
  } = props;
  const { t } = useTranslation();
  const IconComponent = CHANNEL_ICONS[message.channelType];
  const channelColor = CHANNEL_COLORS[message.channelType];
  const sourceType = (message.metadata?.sourceType || "").toLowerCase();
  const isCronMessage = sourceType === "cron";
  const displayTitle = isCronMessage
    ? t("inbox.pushCronHeader", { name: normalizeCronTaskName(message.title) })
    : message.title;

  // ── Action buttons per tab ───────────────────────────────────────────

  const renderActions = () => {
    const buttons: React.ReactNode[] = [];

    if (tab === "messages") {
      // Archive button
      if (onArchive) {
        buttons.push(
          <Tooltip key="archive" title={t("inbox.archive")}>
            <Popconfirm
              title={t("inbox.archiveConfirm")}
              onConfirm={(event) => {
                event?.stopPropagation();
                onArchive(message.id);
              }}
              onCancel={(event) => event?.stopPropagation()}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                size="small"
                type="text"
                icon={<Archive size={14} />}
                onClick={(event) => event.stopPropagation()}
              />
            </Popconfirm>
          </Tooltip>,
        );
      }
      // Move to trash button
      if (onTrash) {
        buttons.push(
          <Tooltip key="trash" title={t("inbox.moveToTrash")}>
            <Popconfirm
              title={t("inbox.moveToTrashConfirm")}
              onConfirm={(event) => {
                event?.stopPropagation();
                onTrash(message.id);
              }}
              onCancel={(event) => event?.stopPropagation()}
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
          </Tooltip>,
        );
      }
    }

    if (tab === "archived") {
      // Restore button
      if (onRestore) {
        buttons.push(
          <Tooltip key="restore" title={t("inbox.restore")}>
            <Button
              size="small"
              type="text"
              icon={<RotateCcw size={14} />}
              onClick={(event) => {
                event.stopPropagation();
                onRestore(message.id);
              }}
            />
          </Tooltip>,
        );
      }
      // Move to trash
      if (onTrash) {
        buttons.push(
          <Tooltip key="trash" title={t("inbox.moveToTrash")}>
            <Popconfirm
              title={t("inbox.moveToTrashConfirm")}
              onConfirm={(event) => {
                event?.stopPropagation();
                onTrash(message.id);
              }}
              onCancel={(event) => event?.stopPropagation()}
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
          </Tooltip>,
        );
      }
    }

    if (tab === "trash") {
      // Restore button
      if (onRestore) {
        buttons.push(
          <Tooltip key="restore" title={t("inbox.restore")}>
            <Button
              size="small"
              type="text"
              icon={<RotateCcw size={14} />}
              onClick={(event) => {
                event.stopPropagation();
                onRestore(message.id);
              }}
            />
          </Tooltip>,
        );
      }
      // Permanent delete
      if (onPermanentDelete) {
        buttons.push(
          <Tooltip key="permdelete" title={t("inbox.permanentDelete")}>
            <Popconfirm
              title={t("inbox.permanentDeleteConfirm")}
              onConfirm={(event) => {
                event?.stopPropagation();
                onPermanentDelete(message.id);
              }}
              onCancel={(event) => event?.stopPropagation()}
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
          </Tooltip>,
        );
      }
    }

    return <>{buttons}</>;
  };

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
          {renderActions()}
        </div>
      </div>
      <div className={styles.cardBody}>
        <h4 className={styles.messageTitle}>{displayTitle}</h4>
        <p className={styles.messageContent}>{message.content}</p>
      </div>
    </Card>
  );
}
