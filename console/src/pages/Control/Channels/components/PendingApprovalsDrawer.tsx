import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Drawer,
  Table,
  Button,
  Space,
  Empty,
  Tooltip,
  Typography,
  Tag,
  Popconfirm,
} from "antd";
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
  const [batchLoading, setBatchLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);

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
    if (open) {
      fetchPending();
      setSelectedRowKeys([]);
      setSelectedChannels([]);
    }
  }, [open, fetchPending]);

  // Derive unique channels that have pending data
  const availableChannels = useMemo(() => {
    const channelSet = new Set(pending.map((entry) => entry.channel));
    return Array.from(channelSet);
  }, [pending]);

  // Filter: empty selection = show all; otherwise show only selected channels
  const filteredPending = useMemo(() => {
    if (selectedChannels.length === 0) return pending;
    return pending.filter((entry) => selectedChannels.includes(entry.channel));
  }, [pending, selectedChannels]);

  const toggleChannelFilter = (channel: string) => {
    setSelectedChannels((prev) =>
      prev.includes(channel)
        ? prev.filter((c) => c !== channel)
        : [...prev, channel]
    );
    setSelectedRowKeys([]);
  };

  // Build entries array from selected row keys
  const selectedEntries = useMemo(
    () =>
      selectedRowKeys.map((key) => {
        const [channel, ...rest] = key.split(":");
        return { channel, user_id: rest.join(":") };
      }),
    [selectedRowKeys]
  );

  const handleRemarkSave = async (entry: PendingEntry, remark: string) => {
    try {
      await accessControlApi.updatePendingRemark(
        entry.channel,
        entry.user_id,
        remark
      );
      // Update local state
      setPending((prev) =>
        prev.map((p) =>
          p.channel === entry.channel && p.user_id === entry.user_id
            ? { ...p, remark }
            : p
        )
      );
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleApprove = async (entry: PendingEntry) => {
    const key = `${entry.channel}:${entry.user_id}`;
    setActionLoading(key);
    try {
      await accessControlApi.approveAclPending([
        { channel: entry.channel, user_id: entry.user_id },
      ]);
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
      await accessControlApi.denyAclPending([
        { channel: entry.channel, user_id: entry.user_id },
      ]);
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
      await accessControlApi.dismissAclPending([
        { channel: entry.channel, user_id: entry.user_id },
      ]);
      message.success(t("channels.dismissSuccess"));
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleBatchApprove = async () => {
    setBatchLoading(true);
    try {
      await accessControlApi.approveAclPending(selectedEntries);
      message.success(
        t("channels.batchSuccess", { count: selectedEntries.length })
      );
      setSelectedRowKeys([]);
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setBatchLoading(false);
    }
  };

  const handleBatchDeny = async () => {
    setBatchLoading(true);
    try {
      await accessControlApi.denyAclPending(selectedEntries);
      message.success(
        t("channels.batchSuccess", { count: selectedEntries.length })
      );
      setSelectedRowKeys([]);
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setBatchLoading(false);
    }
  };

  const handleBatchDismiss = async () => {
    setBatchLoading(true);
    try {
      await accessControlApi.dismissAclPending(selectedEntries);
      message.success(
        t("channels.batchSuccess", { count: selectedEntries.length })
      );
      setSelectedRowKeys([]);
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setBatchLoading(false);
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
      width: 160,
      ellipsis: true,
      render: (userId: string) => (
        <Tooltip title={userId}>
          <Text copyable={{ text: userId }} style={{ maxWidth: 140 }} ellipsis>
            {userId}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: t("channels.firstMessage"),
      dataIndex: "first_message",
      key: "first_message",
      width: 140,
      ellipsis: true,
      render: (msg: string) => (
        <Tooltip title={msg}>
          <span>{msg || "-"}</span>
        </Tooltip>
      ),
    },
    {
      title: t("channels.remark"),
      dataIndex: "remark",
      key: "remark",
      width: 140,
      render: (remark: string, record: PendingEntry) => (
        <Text
          editable={{
            onChange: (value) => handleRemarkSave(record, value),
            text: remark || "",
          }}
        >
          {remark || <span style={{ color: "#bbb" }}>-</span>}
        </Text>
      ),
    },
    {
      title: t("channels.time"),
      dataIndex: "timestamp",
      key: "timestamp",
      width: 140,
      render: (ts: number) => (ts ? new Date(ts * 1000).toLocaleString() : "-"),
    },
    {
      title: t("channels.actions"),
      key: "actions",
      width: 130,
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

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys as string[]),
  };

  const hasSelection = selectedRowKeys.length > 0;

  return (
    <Drawer
      width={860}
      title={t("channels.pendingApprovals")}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {/* Channel filter tags - always visible */}
      {availableChannels.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ marginRight: 8, fontSize: 13 }}>
            {t("channels.filterByChannel")}:
          </Text>
          {availableChannels.map((ch) => (
            <Tag
              key={ch}
              color={selectedChannels.includes(ch) ? "blue" : undefined}
              style={{ cursor: "pointer", marginBottom: 4 }}
              onClick={() => toggleChannelFilter(ch)}
            >
              <Space size={4}>
                <ChannelIcon channelKey={ch as ChannelKey} size={12} />
                {getChannelLabel(ch as ChannelKey, t)}
              </Space>
            </Tag>
          ))}
        </div>
      )}

      {/* Batch action toolbar - always visible */}
      <Space style={{ marginBottom: 12 }} wrap>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {hasSelection
                ? t("channels.selectedCount", {
                    count: selectedRowKeys.length,
                  })
                : t("channels.selectToOperate")}
            </Text>
            <Popconfirm
              title={t("channels.batchApproveConfirm", {
                count: selectedRowKeys.length,
              })}
              onConfirm={handleBatchApprove}
              disabled={!hasSelection}
            >
              <Button
                type="primary"
                size="small"
                icon={<CheckOutlined />}
                disabled={!hasSelection}
                loading={batchLoading}
              >
                {t("channels.batchApprove")}
              </Button>
            </Popconfirm>
            <Popconfirm
              title={t("channels.batchDenyConfirm", {
                count: selectedRowKeys.length,
              })}
              onConfirm={handleBatchDeny}
              disabled={!hasSelection}
            >
              <Button
                size="small"
                icon={<CloseOutlined />}
                disabled={!hasSelection}
                loading={batchLoading}
              >
                {t("channels.batchDeny")}
              </Button>
            </Popconfirm>
            <Popconfirm
              title={t("channels.batchDismissConfirm", {
                count: selectedRowKeys.length,
              })}
              onConfirm={handleBatchDismiss}
              disabled={!hasSelection}
            >
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                disabled={!hasSelection}
                loading={batchLoading}
              >
                {t("channels.batchDismiss")}
              </Button>
            </Popconfirm>
          </Space>

      <Table
        dataSource={filteredPending}
        columns={columns}
        rowKey={(r) => `${r.channel}:${r.user_id}`}
        rowSelection={rowSelection}
        size="small"
        loading={loading}
        pagination={{ pageSize: 15 }}
        scroll={{ x: 790 }}
        locale={{ emptyText: t("channels.noPendingApprovals") }}
      />
    </Drawer>
  );
}
