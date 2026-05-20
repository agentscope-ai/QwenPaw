import { useState, useEffect, useCallback } from "react";
import { Drawer, Table, Button, Space, Empty, Tooltip, Typography } from "antd";
import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  accessControlApi,
  type PendingEntry,
} from "../../../../api/modules/accessControl";
import { getChannelLabel, type ChannelKey } from "./constants";
import { ChannelIcon } from "./ChannelIcon";

const { Text } = Typography;

interface PendingApprovalsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function PendingApprovalsDrawer({
  open,
  onClose,
}: PendingApprovalsDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [pending, setPending] = useState<PendingEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchPending = useCallback(async () => {
    setLoading(true);
    try {
      const data = await accessControlApi.getAclAllPending();
      setPending(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) fetchPending();
  }, [open, fetchPending]);

  const handleApprove = async (entry: PendingEntry) => {
    const key = `${entry.channel}:${entry.user_id}`;
    setActionLoading(key);
    try {
      await accessControlApi.approveAclPending(entry.channel, entry.user_id);
      message.success(t("channels.approveSuccess"));
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeny = async (entry: PendingEntry) => {
    const key = `${entry.channel}:${entry.user_id}`;
    setActionLoading(key);
    try {
      await accessControlApi.denyAclPending(entry.channel, entry.user_id);
      message.success(t("channels.denySuccess"));
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleDismiss = async (entry: PendingEntry) => {
    const key = `${entry.channel}:${entry.user_id}`;
    setActionLoading(key);
    try {
      await accessControlApi.dismissAclPending(entry.channel, entry.user_id);
      message.success(t("channels.dismissSuccess"));
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const columns = [
    {
      title: t("channels.channel"),
      dataIndex: "channel",
      key: "channel",
      width: 80,
      render: (channel: string) => (
        <Tooltip title={getChannelLabel(channel as ChannelKey, t)}>
          <Space size={4}>
            <ChannelIcon channelKey={channel as ChannelKey} size={16} />
            <span>{getChannelLabel(channel as ChannelKey, t)}</span>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: t("channels.userId"),
      dataIndex: "user_id",
      key: "user_id",
      width: 180,
      ellipsis: true,
      render: (userId: string) => (
        <Tooltip title={userId}>
          <Text copyable={{ text: userId }} style={{ maxWidth: 160 }} ellipsis>
            {userId}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: t("channels.firstMessage"),
      dataIndex: "first_message",
      key: "first_message",
      ellipsis: true,
      render: (msg: string) => (
        <Tooltip title={msg}>
          <span>{msg || "-"}</span>
        </Tooltip>
      ),
    },
    {
      title: t("channels.time"),
      dataIndex: "timestamp",
      key: "timestamp",
      width: 150,
      render: (ts: number) => (ts ? new Date(ts * 1000).toLocaleString() : "-"),
    },
    {
      title: t("channels.actions"),
      key: "actions",
      width: 160,
      fixed: "right" as const,
      render: (_: unknown, record: PendingEntry) => {
        const key = `${record.channel}:${record.user_id}`;
        const isLoading = actionLoading === key;
        return (
          <Space size={4} wrap>
            <Tooltip title={t("channels.approve")}>
              <Button
                type="primary"
                size="small"
                icon={<CheckOutlined />}
                loading={isLoading}
                onClick={() => handleApprove(record)}
              />
            </Tooltip>
            <Tooltip title={t("channels.deny")}>
              <Button
                danger
                size="small"
                icon={<CloseOutlined />}
                loading={isLoading}
                onClick={() => handleDeny(record)}
              />
            </Tooltip>
            <Tooltip title={t("channels.dismiss")}>
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                loading={isLoading}
                onClick={() => handleDismiss(record)}
              />
            </Tooltip>
          </Space>
        );
      },
    },
  ];

  return (
    <Drawer
      width={780}
      title={t("channels.pendingApprovals")}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {pending.length === 0 && !loading ? (
        <Empty description={t("channels.noPendingApprovals")} />
      ) : (
        <Table
          dataSource={pending}
          columns={columns}
          rowKey={(r) => `${r.channel}:${r.user_id}`}
          size="small"
          loading={loading}
          pagination={{ pageSize: 15 }}
          scroll={{ x: 700 }}
        />
      )}
    </Drawer>
  );
}
