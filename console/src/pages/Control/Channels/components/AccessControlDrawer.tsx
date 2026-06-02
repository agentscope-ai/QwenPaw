import { useState, useEffect, useCallback } from "react";
import {
  Drawer,
  Tabs,
  Table,
  Button,
  Input,
  Select,
  Modal,
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

interface AccessControlDrawerProps {
  open: boolean;
  onClose: () => void;
}

function toEntries(
  map: Record<string, { remark: string; username: string }> | undefined,
): ACLUserEntry[] {
  if (!map) return [];
  return Object.entries(map).map(([userId, info]) => ({
    userId,
    remark: info?.remark ?? "",
    username: info?.username ?? "",
  }));
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
  const [newUsername, setNewUsername] = useState("");
  const [newRemark, setNewRemark] = useState("");
  const [activeTab, setActiveTab] = useState<"whitelist" | "blacklist">(
    "whitelist",
  );
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);

  const fetchACLs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await accessControlApi.getAclAll();
      setAllACLs(data);
      const keys = Object.keys(data);
      if (keys.length === 0) {
        setSelectedChannel(null);
      } else if (!selectedChannel || !keys.includes(selectedChannel)) {
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
    const addApi =
      activeTab === "whitelist"
        ? accessControlApi.addAclWhitelist
        : accessControlApi.addAclBlacklist;
    try {
      await addApi([
        {
          channel: selectedChannel,
          user_id: newUserId.trim(),
          remark: newRemark.trim(),
          username: newUsername.trim(),
        },
      ]);
      message.success(t("channels.userAdded"));
      setNewUserId("");
      setNewUsername("");
      setNewRemark("");
      await fetchACLs();
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const handleRemove = async (userId: string) => {
    if (!selectedChannel) return;
    const removeApi =
      activeTab === "whitelist"
        ? accessControlApi.removeAclWhitelist
        : accessControlApi.removeAclBlacklist;
    try {
      await removeApi([{ channel: selectedChannel, user_id: userId }]);
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
      setAllACLs((prev) => {
        const channelData = prev[selectedChannel];
        if (!channelData) return prev;
        const list = channelData[activeTab];
        const existing = list[userId] ?? { remark: "", username: "" };
        return {
          ...prev,
          [selectedChannel]: {
            ...channelData,
            [activeTab]: {
              ...list,
              [userId]: { ...existing, remark },
            },
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
    const removeApi =
      activeTab === "whitelist"
        ? accessControlApi.removeAclWhitelist
        : accessControlApi.removeAclBlacklist;
    try {
      await removeApi(
        selectedRowKeys.map((userId) => ({
          channel: selectedChannel,
          user_id: userId as string,
        })),
      );
      message.success(
        t("channels.batchSuccess", { count: selectedRowKeys.length }),
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
    ? toEntries(currentACL[activeTab])
    : [];

  const handleUsernameSave = async (userId: string, username: string) => {
    if (!selectedChannel) return;
    try {
      await accessControlApi.updateUsername(selectedChannel, userId, username);
      setAllACLs((prev) => {
        const channelData = prev[selectedChannel];
        if (!channelData) return prev;
        const list = channelData[activeTab];
        const existing = list[userId] ?? { remark: "", username: "" };
        return {
          ...prev,
          [selectedChannel]: {
            ...channelData,
            [activeTab]: {
              ...list,
              [userId]: { ...existing, username },
            },
          },
        };
      });
    } catch {
      message.error(t("channels.operationFailed"));
    }
  };

  const columns = [
    {
      title: t("channels.username"),
      dataIndex: "username",
      key: "username",
      width: 120,
      render: (username: string, record: ACLUserEntry) => (
        <Typography.Text
          editable={{
            onChange: (value) => handleUsernameSave(record.userId, value),
            text: username || "",
          }}
        >
          {username || <span style={{ color: "#bbb" }}>-</span>}
        </Typography.Text>
      ),
    },
    {
      title: t("channels.userId"),
      dataIndex: "userId",
      key: "userId",
      ellipsis: { showTitle: false },
      render: (userId: string) => (
        <Space size={4}>
          <Typography.Text
            ellipsis={{ tooltip: userId }}
            style={{ maxWidth: 180 }}
          >
            {userId}
          </Typography.Text>
          <Typography.Text copyable={{ text: userId }} />
        </Space>
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
      width: 80,
      render: (_: unknown, record: ACLUserEntry) => (
        <Popconfirm
          title={`Remove ${record.userId}?`}
          onConfirm={() => handleRemove(record.userId)}
        >
          <Button type="text" danger size="small">
            {t("channels.batchRemove")}
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Drawer
      width={700}
      title={t("channels.manageAccessControl")}
      open={open}
      onClose={onClose}
      destroyOnHidden
    >
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
        tabBarExtraContent={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setAddModalOpen(true)}
            disabled={!selectedChannel}
          >
            {t("channels.addUser")}
          </Button>
        }
      />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <Select
          value={selectedChannel}
          onChange={(value) => {
            setSelectedChannel(value);
            setSelectedRowKeys([]);
          }}
          style={{ width: 180 }}
          disabled={channelKeys.length === 0}
          placeholder={t("channels.filterByChannel")}
          options={channelKeys.map((key) => ({
            label: getChannelLabel(key as ChannelKey, t),
            value: key,
          }))}
        />
        <Space>
          {selectedRowKeys.length > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              {t("channels.selectedCount", { count: selectedRowKeys.length })}
            </Typography.Text>
          )}
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
            </Button>
          </Popconfirm>
        </Space>
      </div>

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
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{
          emptyText: (
            <div style={{ padding: "48px 0" }}>
              {activeTab === "whitelist"
                ? t("channels.noWhitelistUsers")
                : t("channels.noBlacklistUsers")}
            </div>
          ),
        }}
      />

      <Modal
        title={t("channels.addUser")}
        open={addModalOpen}
        onCancel={() => {
          setAddModalOpen(false);
          setNewUserId("");
          setNewUsername("");
          setNewRemark("");
        }}
        onOk={async () => {
          await handleAdd();
          setAddModalOpen(false);
        }}
        okButtonProps={{ disabled: !newUserId.trim() }}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          <div>
            <Typography.Text
              strong
              style={{ display: "block", marginBottom: 6 }}
            >
              {t("channels.userId")}
            </Typography.Text>
            <Input
              placeholder={t("channels.addUserPlaceholder")}
              value={newUserId}
              onChange={(e) => setNewUserId(e.target.value)}
            />
          </div>
          <div>
            <Typography.Text
              strong
              style={{ display: "block", marginBottom: 6 }}
            >
              {t("channels.username")}
            </Typography.Text>
            <Input
              placeholder={t("channels.usernamePlaceholder")}
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
            />
          </div>
          <div>
            <Typography.Text
              strong
              style={{ display: "block", marginBottom: 6 }}
            >
              {t("channels.remark")}
            </Typography.Text>
            <Input
              placeholder={t("channels.remarkPlaceholder")}
              value={newRemark}
              onChange={(e) => setNewRemark(e.target.value)}
            />
          </div>
        </Space>
      </Modal>
    </Drawer>
  );
}
