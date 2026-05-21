import { useState, useEffect, useCallback } from "react";
import {
  Drawer,
  Tabs,
  Table,
  Button,
  Input,
  Tag,
  Popconfirm,
  Space,
  Typography,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type React from "react";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  accessControlApi,
  type ACLData,
  type ACLUserEntry,
} from "../../../../api/modules/accessControl";
import { getChannelLabel, type ChannelKey } from "./constants";
import { ChannelIcon } from "./ChannelIcon";

interface AccessControlDrawerProps {
  open: boolean;
  onClose: () => void;
}

/** Convert Record<string, string> to flat array for Table */
function toEntries(map: Record<string, string> | undefined): ACLUserEntry[] {
  if (!map) return [];
  return Object.entries(map).map(([userId, remark]) => ({ userId, remark }));
}

export function AccessControlDrawer({
  open,
  onClose,
}: AccessControlDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [allACLs, setAllACLs] = useState<Record<string, ACLData>>({});
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [newUserId, setNewUserId] = useState("");
  const [newRemark, setNewRemark] = useState("");
  const [activeTab, setActiveTab] = useState<"whitelist" | "blacklist">(
    "whitelist",
  );
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);

  const fetchACLs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await accessControlApi.getAclAll();
      setAllACLs(data);
      const keys = Object.keys(data);
      if (!selectedChannel && keys.length > 0) {
        setSelectedChannel(keys[0]);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [selectedChannel]);

  useEffect(() => {
    if (open) fetchACLs();
  }, [open, fetchACLs]);

  const channelKeys = Object.keys(allACLs);
  const currentACL = selectedChannel ? allACLs[selectedChannel] : null;

  const handleAdd = async () => {
    if (!selectedChannel || !newUserId.trim()) return;
    try {
      if (activeTab === "whitelist") {
        await accessControlApi.addAclWhitelist(
          selectedChannel,
          newUserId.trim(),
          newRemark.trim(),
        );
      } else {
        await accessControlApi.addAclBlacklist(
          selectedChannel,
          newUserId.trim(),
          newRemark.trim(),
        );
      }
      message.success(t("channels.userAdded"));
      setNewUserId("");
      setNewRemark("");
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleRemove = async (userId: string) => {
    if (!selectedChannel) return;
    try {
      if (activeTab === "whitelist") {
        await accessControlApi.removeAclWhitelist(selectedChannel, userId);
      } else {
        await accessControlApi.removeAclBlacklist(selectedChannel, userId);
      }
      message.success(t("channels.userRemoved"));
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleRemarkSave = async (userId: string, remark: string) => {
    if (!selectedChannel) return;
    try {
      await accessControlApi.updateAclRemark(selectedChannel, userId, remark);
      // Update local state immediately without refetching
      setAllACLs((prev) => {
        const channelData = prev[selectedChannel];
        if (!channelData) return prev;
        const listKey = activeTab;
        return {
          ...prev,
          [selectedChannel]: {
            ...channelData,
            [listKey]: { ...channelData[listKey], [userId]: remark },
          },
        };
      });
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleBatchRemove = async () => {
    if (!selectedChannel || selectedRowKeys.length === 0) return;
    setBatchLoading(true);
    try {
      for (const userId of selectedRowKeys) {
        if (activeTab === "whitelist") {
          await accessControlApi.removeAclWhitelist(
            selectedChannel,
            userId as string
          );
        } else {
          await accessControlApi.removeAclBlacklist(
            selectedChannel,
            userId as string
          );
        }
      }
      message.success(
        t("channels.batchSuccess", { count: selectedRowKeys.length })
      );
      setSelectedRowKeys([]);
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    } finally {
      setBatchLoading(false);
    }
  };

  const listData: ACLUserEntry[] = currentACL
    ? activeTab === "whitelist"
      ? toEntries(currentACL.whitelist)
      : toEntries(currentACL.blacklist)
    : [];

  const columns = [
    {
      title: t("channels.userId"),
      dataIndex: "userId",
      key: "userId",
      ellipsis: true,
      render: (userId: string) => (
        <Typography.Text
          copyable={{ text: userId }}
          ellipsis
          style={{ maxWidth: 180 }}
        >
          {userId}
        </Typography.Text>
      ),
    },
    {
      title: t("channels.remark"),
      dataIndex: "remark",
      key: "remark",
      width: 160,
      render: (remark: string, record: ACLUserEntry) => (
        <Typography.Text
          editable={{
            onChange: (value) => handleRemarkSave(record.userId, value),
            text: remark,
          }}
        >
          {remark || <span style={{ color: "#bbb" }}>-</span>}
        </Typography.Text>
      ),
    },
    {
      title: t("channels.actions"),
      key: "actions",
      width: 60,
      render: (_: unknown, record: ACLUserEntry) => (
        <Popconfirm
          title={`Remove ${record.userId}?`}
          onConfirm={() => handleRemove(record.userId)}
        >
          <Button type="text" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  return (
    <Drawer
      width={560}
      title={t("channels.manageAccessControl")}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {channelKeys.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            marginBottom: 16,
          }}
        >
          {channelKeys.map((key) => (
            <Tag
              key={key}
              color={selectedChannel === key ? "blue" : undefined}
              style={{
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 4,
                padding: "4px 8px",
              }}
              onClick={() => {
                setSelectedChannel(key);
                setSelectedRowKeys([]);
              }}
            >
              <ChannelIcon channelKey={key as ChannelKey} size={16} />
              {getChannelLabel(key as ChannelKey, t)}
            </Tag>
          ))}
        </div>
      )}

      <Tabs
        activeKey={activeTab}
        onChange={(k) => {
          setActiveTab(k as "whitelist" | "blacklist");
          setSelectedRowKeys([]);
        }}
        items={[
          { key: "whitelist", label: t("channels.whitelist") },
          { key: "blacklist", label: t("channels.blacklist") },
        ]}
      />

      <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
        <Input
          placeholder={t("channels.addUserPlaceholder")}
          value={newUserId}
          onChange={(e) => setNewUserId(e.target.value)}
          onPressEnter={handleAdd}
          style={{ flex: 1 }}
        />
        <Input
          placeholder={t("channels.remarkPlaceholder")}
          value={newRemark}
          onChange={(e) => setNewRemark(e.target.value)}
          onPressEnter={handleAdd}
          style={{ flex: 1 }}
        />
        <Button
          icon={<PlusOutlined />}
          onClick={handleAdd}
          disabled={!newUserId.trim()}
        >
          {t("channels.addUser")}
        </Button>
      </Space.Compact>

      <Table
        dataSource={listData}
        columns={columns}
        rowKey={(record) => record.userId}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        size="small"
        loading={loading}
        pagination={{ pageSize: 10 }}
        locale={{
          emptyText:
            activeTab === "whitelist"
              ? t("channels.noWhitelistUsers")
              : t("channels.noBlacklistUsers"),
        }}
      />

      {/* Batch actions at bottom */}
      <Space style={{ marginTop: 8 }}>
        <Popconfirm
          title={t("channels.batchRemoveConfirm", {
            count: selectedRowKeys.length,
          })}
          onConfirm={handleBatchRemove}
          disabled={selectedRowKeys.length === 0}
        >
          <Button
            danger
            size="small"
            icon={<DeleteOutlined />}
            disabled={selectedRowKeys.length === 0}
            loading={batchLoading}
          >
            {t("channels.batchRemove")}
            {selectedRowKeys.length > 0 && ` (${selectedRowKeys.length})`}
          </Button>
        </Popconfirm>
      </Space>
    </Drawer>
  );
}
