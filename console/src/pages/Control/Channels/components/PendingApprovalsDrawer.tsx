import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Drawer,
  Table,
  Button,
  Space,
  Tooltip,
  Typography,
  Select,
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

type PendingAction = "approve" | "deny" | "dismiss";

const ACTION_API_MAP: Record<
  PendingAction,
  typeof accessControlApi.approveAclPending
> = {
  approve: accessControlApi.approveAclPending,
  deny: accessControlApi.denyAclPending,
  dismiss: accessControlApi.dismissAclPending,
};

const ACTION_SUCCESS_KEY: Record<PendingAction, string> = {
  approve: "channels.approveSuccess",
  deny: "channels.denySuccess",
  dismiss: "channels.dismissSuccess",
};

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
    }
  }, [open, fetchPending]);

  const availableChannels = useMemo(() => {
    const channelSet = new Set(pending.map((entry) => entry.channel));
    return Array.from(channelSet);
  }, [pending]);

  const filteredPending = useMemo(() => {
    if (selectedChannels.length === 0) return pending;
    return pending.filter((entry) => selectedChannels.includes(entry.channel));
  }, [pending, selectedChannels]);

  const selectedEntries = useMemo(
    () =>
      selectedRowKeys.map((key) => {
        const [channel, ...rest] = key.split(":");
        return { channel, user_id: rest.join(":") };
      }),
    [selectedRowKeys],
  );

  const handleRemarkSave = async (entry: PendingEntry, remark: string) => {
    try {
      await accessControlApi.updatePendingRemark(
        entry.channel,
        entry.user_id,
        remark,
      );
      setPending((prev) =>
        prev.map((p) =>
          p.channel === entry.channel && p.user_id === entry.user_id
            ? { ...p, remark }
            : p,
        ),
      );
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleUsernameSave = async (entry: PendingEntry, username: string) => {
    try {
      await accessControlApi.updateUsername(
        entry.channel,
        entry.user_id,
        username,
      );
      setPending((prev) =>
        prev.map((p) =>
          p.channel === entry.channel && p.user_id === entry.user_id
            ? { ...p, username }
            : p,
        ),
      );
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleAction = async (entry: PendingEntry, action: PendingAction) => {
    const key = `${entry.channel}:${entry.user_id}`;
    setActionLoading(key);
    try {
      await ACTION_API_MAP[action]([
        { channel: entry.channel, user_id: entry.user_id },
      ]);
      message.success(t(ACTION_SUCCESS_KEY[action]));
      await fetchPending();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleBatchAction = async (action: PendingAction) => {
    setBatchLoading(true);
    try {
      await ACTION_API_MAP[action](selectedEntries);
      message.success(
        t("channels.batchSuccess", { count: selectedEntries.length }),
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
      width: 100,
      fixed: "left" as const,
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
      title: t("channels.username"),
      dataIndex: "username",
      key: "username",
      width: 120,
      render: (username: string, record: PendingEntry) => (
        <Text
          editable={{
            onChange: (value) => handleUsernameSave(record, value),
            text: username || "",
          }}
        >
          {username || <span style={{ color: "#bbb" }}>-</span>}
        </Text>
      ),
    },
    {
      title: t("channels.userId"),
      dataIndex: "user_id",
      key: "user_id",
      width: 160,
      ellipsis: { showTitle: false },
      render: (userId: string) => (
        <Space size={4}>
          <Text ellipsis={{ tooltip: userId }} style={{ maxWidth: 120 }}>
            {userId}
          </Text>
          <Text copyable={{ text: userId }} />
        </Space>
      ),
    },
    {
      title: t("channels.firstMessage"),
      dataIndex: "first_message",
      key: "first_message",
      width: 160,
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
      width: 130,
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
      width: 150,
      render: (ts: number) => (ts ? new Date(ts * 1000).toLocaleString() : "-"),
    },
    {
      title: t("channels.actions"),
      key: "actions",
      width: 200,
      fixed: "right" as const,
      render: (_: unknown, record: PendingEntry) => {
        const key = `${record.channel}:${record.user_id}`;
        const isLoading = actionLoading === key;
        return (
          <Space size={0}>
            <Button
              type="text"
              size="small"
              loading={isLoading}
              onClick={() => handleAction(record, "approve")}
              style={{ color: "#52c41a", padding: "0 4px" }}
            >
              {t("channels.approve")}
            </Button>
            <Button
              type="text"
              size="small"
              danger
              loading={isLoading}
              onClick={() => handleAction(record, "deny")}
              style={{ padding: "0 4px" }}
            >
              {t("channels.deny")}
            </Button>
            <Button
              type="text"
              size="small"
              loading={isLoading}
              onClick={() => handleAction(record, "dismiss")}
              style={{ padding: "0 4px" }}
            >
              {t("channels.dismiss")}
            </Button>
          </Space>
        );
      },
    },
  ];

  const hasSelection = selectedRowKeys.length > 0;

  return (
    <Drawer
      width={920}
      title={t("channels.pendingApprovals")}
      open={open}
      onClose={onClose}
      destroyOnHidden
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <Select
          mode="multiple"
          allowClear
          placeholder={t("channels.filterByChannel")}
          value={selectedChannels}
          onChange={(values) => {
            setSelectedChannels(values);
            setSelectedRowKeys([]);
          }}
          style={{ minWidth: 200 }}
          options={availableChannels.map((ch) => ({
            label: getChannelLabel(ch as ChannelKey, t),
            value: ch,
          }))}
        />
        <Space>
          {hasSelection && (
            <Text type="secondary" style={{ fontSize: 13 }}>
              {t("channels.selectedCount", { count: selectedRowKeys.length })}
            </Text>
          )}
          <Popconfirm
            title={t("channels.batchApproveConfirm", {
              count: selectedRowKeys.length,
            })}
            onConfirm={() => handleBatchAction("approve")}
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
            onConfirm={() => handleBatchAction("deny")}
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
            onConfirm={() => handleBatchAction("dismiss")}
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
      </div>

      <Table
        dataSource={filteredPending}
        columns={columns}
        rowKey={(r) => `${r.channel}:${r.user_id}`}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
        }}
        size="small"
        loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: 1050 }}
        locale={{
          emptyText: (
            <div style={{ padding: "48px 0" }}>
              {t("channels.noPendingApprovals")}
            </div>
          ),
        }}
      />
    </Drawer>
  );
}
