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
  Tabs,
  Divider,
  Modal,
  Input,
} from "antd";
import { Check, Plus, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  mailAccessControlApi,
  type MailACLData,
  type MailACLUserEntry,
  type MailPendingEntry,
  type MailUserInfo,
} from "../../../api/modules/mailAccessControl";

const { Text } = Typography;

type PendingAction = "approve" | "deny" | "dismiss";

const ACTION_API_MAP: Record<
  PendingAction,
  typeof mailAccessControlApi.approveMailPending
> = {
  approve: mailAccessControlApi.approveMailPending,
  deny: mailAccessControlApi.denyMailPending,
  dismiss: mailAccessControlApi.dismissMailPending,
};

function toMailEntries(
  agentId: string,
  map: Record<string, MailUserInfo> | undefined,
): MailACLUserEntry[] {
  if (!map) return [];
  return Object.entries(map).map(([address, info]) => ({
    agent_id: agentId,
    address,
    display_name: info?.display_name ?? "",
    remark: info?.remark ?? "",
  }));
}

/**
 * Parse a human-readable sender name out of the raw display name.
 * Returns "-" when the name is empty or identical to the email address.
 */
function parseSenderName(displayName: string, address: string): string {
  if (!displayName) return "-";
  // Extract the part before <...> as the nickname
  const match = displayName.match(/^(.*?)</);
  let nick = (match ? match[1] : displayName).trim();
  // Strip wrapping quotes
  nick = nick.replace(/^["']+|["']+$/g, "").trim();
  if (!nick) return "-";
  // Nickname identical to the email address -> show "-"
  if (nick.toLowerCase() === address.toLowerCase()) return "-";
  return nick;
}

/**
 * Validate a sender address: either a normal email (user@domain.com)
 * or a domain wildcard (*@domain.com).
 */
function isValidSenderAddress(address: string): boolean {
  const email = /^[^\s@*]+@[^\s@]+\.[^\s@]+$/;
  const wildcard = /^\*@[^\s@*]+\.[^\s@]+$/;
  return email.test(address) || wildcard.test(address);
}

interface MailAccessControlDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function MailAccessControlDrawer({
  open,
  onClose,
}: MailAccessControlDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  // --- Pending section state ---
  const [pending, setPending] = useState<MailPendingEntry[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [selectedPendingKeys, setSelectedPendingKeys] = useState<string[]>([]);
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);

  // --- List section state ---
  const [allACLs, setAllACLs] = useState<Record<string, MailACLData>>({});
  const [listLoading, setListLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"whitelist" | "blacklist">(
    "whitelist",
  );
  const [selectedAgent, setSelectedAgent] = useState<string | undefined>(
    undefined,
  );
  const [selectedListKeys, setSelectedListKeys] = useState<string[]>([]);
  const [listBatchLoading, setListBatchLoading] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newAddress, setNewAddress] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newRemark, setNewRemark] = useState("");
  const [mailAgents, setMailAgents] = useState<string[]>([]);

  // --- Fetch pending ---
  const fetchPending = useCallback(async () => {
    setPendingLoading(true);
    try {
      const data = await mailAccessControlApi.getMailPendingAll();
      setPending(data);
    } catch {
      // silent
    } finally {
      setPendingLoading(false);
    }
  }, []);

  // --- Fetch lists ---
  const fetchLists = useCallback(async () => {
    setListLoading(true);
    try {
      const data = await mailAccessControlApi.getMailAclAll();
      setAllACLs(data || {});
    } catch {
      // silent
    } finally {
      setListLoading(false);
    }
  }, []);

  // --- Fetch mail-enabled agents ---
  const fetchMailAgents = useCallback(async () => {
    try {
      const data = await mailAccessControlApi.getMailAgents();
      setMailAgents(data?.agents || []);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchPending();
      fetchLists();
      fetchMailAgents();
      setSelectedPendingKeys([]);
      setSelectedListKeys([]);
    }
  }, [open, fetchPending, fetchLists, fetchMailAgents]);

  // --- Pending helpers ---
  const availableAgents = useMemo(() => mailAgents, [mailAgents]);

  const filteredPending = useMemo(() => {
    if (selectedAgents.length === 0) return pending;
    return pending.filter((entry) => selectedAgents.includes(entry.agent_id));
  }, [pending, selectedAgents]);

  const selectedPendingEntries = useMemo(
    () =>
      selectedPendingKeys.map((key) => {
        const [agent_id, ...rest] = key.split(":");
        return { agent_id, address: rest.join(":") };
      }),
    [selectedPendingKeys],
  );

  const handlePendingRemarkSave = async (
    entry: MailPendingEntry,
    remark: string,
  ) => {
    try {
      await mailAccessControlApi.updateMailPendingRemark(
        entry.agent_id,
        entry.sender_address,
        remark,
      );
      setPending((prev) =>
        prev.map((p) =>
          p.agent_id === entry.agent_id &&
          p.sender_address === entry.sender_address
            ? { ...p, remark }
            : p,
        ),
      );
    } catch {
      message.error(t("common.operationFailed"));
    }
  };

  const handlePendingAction = async (
    entry: MailPendingEntry,
    action: PendingAction,
  ) => {
    const key = `${entry.agent_id}:${entry.sender_address}`;
    setActionLoading(key);
    try {
      await ACTION_API_MAP[action]([
        { agent_id: entry.agent_id, address: entry.sender_address },
      ]);
      message.success(t(`inbox.${action}`));
      await fetchPending();
      await fetchLists();
    } catch {
      message.error(t("common.operationFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleBatchPendingAction = async (action: PendingAction) => {
    setBatchLoading(true);
    try {
      await ACTION_API_MAP[action](selectedPendingEntries);
      message.success(
        t(`inbox.batch${action.charAt(0).toUpperCase() + action.slice(1)}`),
      );
      setSelectedPendingKeys([]);
      await fetchPending();
      await fetchLists();
    } catch {
      message.error(t("common.operationFailed"));
    } finally {
      setBatchLoading(false);
    }
  };

  // --- List helpers ---
  const listData: MailACLUserEntry[] = useMemo(() => {
    if (!selectedAgent) {
      // No agent selected: merge all agents' data, each entry keeps its own agent_id
      const merged: MailACLUserEntry[] = [];
      Object.entries(allACLs).forEach(([agentId, acl]) => {
        const map = activeTab === "whitelist" ? acl.whitelist : acl.blacklist;
        merged.push(...toMailEntries(agentId, map));
      });
      return merged;
    }
    const acl = allACLs[selectedAgent];
    if (!acl) return [];
    const map = activeTab === "whitelist" ? acl.whitelist : acl.blacklist;
    return toMailEntries(selectedAgent, map);
  }, [activeTab, selectedAgent, allACLs]);

  const handleRemoveFromList = async (record: MailACLUserEntry) => {
    const removeApi =
      activeTab === "whitelist"
        ? mailAccessControlApi.removeMailWhitelist
        : mailAccessControlApi.removeMailBlacklist;
    try {
      await removeApi([{ agent_id: record.agent_id, address: record.address }]);
      message.success(t("inbox.removeSuccess"));
      await fetchLists();
    } catch {
      message.error(t("common.operationFailed"));
    }
  };

  const handleBatchRemove = async () => {
    if (selectedListKeys.length === 0) return;
    setListBatchLoading(true);
    const removeApi =
      activeTab === "whitelist"
        ? mailAccessControlApi.removeMailWhitelist
        : mailAccessControlApi.removeMailBlacklist;
    try {
      await removeApi(
        selectedListKeys.map((key) => {
          const [agent_id, ...rest] = key.split(":");
          return { agent_id, address: rest.join(":") };
        }),
      );
      message.success(t("inbox.removeSuccess"));
      setSelectedListKeys([]);
      await fetchLists();
    } catch {
      message.error(t("common.operationFailed"));
    } finally {
      setListBatchLoading(false);
    }
  };

  const handleAddToList = async () => {
    if (!newAddress.trim()) return;
    if (!isValidSenderAddress(newAddress.trim())) {
      message.error(t("inbox.invalidAddress"));
      return;
    }
    const addApi =
      activeTab === "whitelist"
        ? mailAccessControlApi.addMailWhitelist
        : mailAccessControlApi.addMailBlacklist;
    try {
      await addApi([
        {
          agent_id: selectedAgent || "",
          address: newAddress.trim(),
          remark: newRemark.trim() || undefined,
          display_name: newDisplayName.trim() || undefined,
        },
      ]);
      message.success(
        selectedAgent ? t("inbox.addSender") : t("inbox.addedToAllAgents"),
      );
      setNewAddress("");
      setNewDisplayName("");
      setNewRemark("");
      setAddModalOpen(false);
      await fetchLists();
    } catch {
      message.error(t("common.operationFailed"));
    }
  };

  // --- Pending columns ---
  const pendingColumns = [
    {
      title: "Agent",
      dataIndex: "agent_id",
      key: "agent_id",
      width: 100,
    },
    {
      title: t("inbox.senderAddress"),
      dataIndex: "sender_address",
      key: "sender_address",
      width: 180,
      render: (address: string) => (
        <Space size={4}>
          <Text ellipsis={{ tooltip: address }} style={{ maxWidth: 140 }}>
            {address}
          </Text>
          <Text copyable={{ text: address }} />
        </Space>
      ),
    },
    {
      title: t("inbox.displayName"),
      dataIndex: "display_name",
      key: "display_name",
      width: 100,
      render: (name: string, record: MailPendingEntry) => {
        const parsed = parseSenderName(name, record.sender_address);
        return parsed === "-" ? (
          <span style={{ color: "#bbb" }}>-</span>
        ) : (
          parsed
        );
      },
    },
    {
      title: t("inbox.emailSubject"),
      dataIndex: "subject",
      key: "subject",
      width: 140,
      ellipsis: true,
      render: (subject: string) => (
        <Tooltip title={subject}>
          <span>{subject || "-"}</span>
        </Tooltip>
      ),
    },
    {
      title: t("inbox.bodyPreview"),
      dataIndex: "body_preview",
      key: "body_preview",
      width: 140,
      ellipsis: true,
      render: (body: string) => (
        <Tooltip title={body}>
          <span>{body || "-"}</span>
        </Tooltip>
      ),
    },
    {
      title: t("inbox.time"),
      dataIndex: "timestamp",
      key: "timestamp",
      width: 140,
      render: (ts: number) => (ts ? new Date(ts * 1000).toLocaleString() : "-"),
    },
    {
      title: t("inbox.remark"),
      dataIndex: "remark",
      key: "remark",
      width: 120,
      render: (remark: string, record: MailPendingEntry) => (
        <Text
          editable={{
            onChange: (value) => handlePendingRemarkSave(record, value),
            text: remark || "",
          }}
        >
          {remark || <span style={{ color: "#bbb" }}>-</span>}
        </Text>
      ),
    },
    {
      title: t("inbox.actions"),
      key: "actions",
      width: 220,
      fixed: "right" as const,
      render: (_: unknown, record: MailPendingEntry) => {
        const key = `${record.agent_id}:${record.sender_address}`;
        const isLoading = actionLoading === key;
        return (
          <Space size={0}>
            <Button
              type="text"
              size="small"
              icon={<Check size={14} />}
              loading={isLoading}
              onClick={() => handlePendingAction(record, "approve")}
              style={{ color: "#52c41a", padding: "0 4px" }}
            >
              {t("inbox.approveSender")}
            </Button>
            <Button
              type="text"
              size="small"
              icon={<X size={14} />}
              danger
              loading={isLoading}
              onClick={() => handlePendingAction(record, "deny")}
              style={{ padding: "0 4px" }}
            >
              {t("inbox.deny")}
            </Button>
            <Button
              type="text"
              size="small"
              icon={<Trash2 size={14} />}
              loading={isLoading}
              onClick={() => handlePendingAction(record, "dismiss")}
              style={{ padding: "0 4px" }}
            >
              {t("inbox.dismiss")}
            </Button>
          </Space>
        );
      },
    },
  ];

  // --- List columns ---
  const listColumns = [
    {
      title: "Agent",
      dataIndex: "agent_id",
      key: "agent_id",
      width: 110,
    },
    {
      title: t("inbox.senderAddress"),
      dataIndex: "address",
      key: "address",
      ellipsis: { showTitle: false },
      render: (address: string) => (
        <Space size={4}>
          <Text ellipsis={{ tooltip: address }} style={{ maxWidth: 180 }}>
            {address}
          </Text>
          <Text copyable={{ text: address }} />
        </Space>
      ),
    },
    {
      title: t("inbox.displayName"),
      dataIndex: "display_name",
      key: "display_name",
      width: 140,
      render: (display_name: string, record: MailACLUserEntry) => {
        const parsed = parseSenderName(display_name, record.address);
        return parsed === "-" ? (
          <span style={{ color: "#bbb" }}>-</span>
        ) : (
          parsed
        );
      },
    },
    {
      title: t("inbox.remark"),
      dataIndex: "remark",
      key: "remark",
      width: 160,
      render: (remark: string) =>
        remark || <span style={{ color: "#bbb" }}>-</span>,
    },
    {
      title: t("inbox.actions"),
      key: "actions",
      width: 80,
      render: (_: unknown, record: MailACLUserEntry) => (
        <Popconfirm
          title={t("inbox.confirmRemove")}
          onConfirm={() => handleRemoveFromList(record)}
        >
          <Button type="text" danger size="small" icon={<Trash2 size={14} />} />
        </Popconfirm>
      ),
    },
  ];

  const hasPendingSelection = selectedPendingKeys.length > 0;

  return (
    <Drawer
      width={800}
      title={t("inbox.mailAccessControl")}
      open={open}
      onClose={onClose}
      destroyOnHidden
    >
      {/* === Pending section === */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <Text strong style={{ fontSize: 15 }}>
          {t("inbox.pendingSenders")}
        </Text>
        <Select
          mode="multiple"
          allowClear
          placeholder={t("inbox.filterByAgent")}
          value={selectedAgents}
          onChange={(values) => {
            setSelectedAgents(values);
            setSelectedPendingKeys([]);
          }}
          style={{ minWidth: 200 }}
          options={availableAgents.map((id) => ({ label: id, value: id }))}
        />
      </div>

      {hasPendingSelection && (
        <Space style={{ marginBottom: 8 }}>
          <Popconfirm
            title={t("inbox.confirmApprove")}
            onConfirm={() => handleBatchPendingAction("approve")}
          >
            <Button
              type="primary"
              size="small"
              icon={<Check size={14} />}
              loading={batchLoading}
            >
              {t("inbox.batchApprove")}
            </Button>
          </Popconfirm>
          <Popconfirm
            title={t("inbox.confirmDeny")}
            onConfirm={() => handleBatchPendingAction("deny")}
          >
            <Button size="small" icon={<X size={14} />} loading={batchLoading}>
              {t("inbox.batchDeny")}
            </Button>
          </Popconfirm>
          <Popconfirm
            title={t("inbox.confirmDismiss")}
            onConfirm={() => handleBatchPendingAction("dismiss")}
          >
            <Button
              danger
              size="small"
              icon={<Trash2 size={14} />}
              loading={batchLoading}
            >
              {t("inbox.batchDismiss")}
            </Button>
          </Popconfirm>
        </Space>
      )}

      <Table
        dataSource={filteredPending}
        columns={pendingColumns}
        rowKey={(r) => `${r.agent_id}:${r.sender_address}`}
        rowSelection={{
          selectedRowKeys: selectedPendingKeys,
          onChange: (keys) => setSelectedPendingKeys(keys as string[]),
        }}
        size="small"
        loading={pendingLoading}
        pagination={{ pageSize: 5, showSizeChanger: false }}
        scroll={{ x: 1120 }}
      />

      <Divider />

      {/* === List section === */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <Text strong style={{ fontSize: 15 }}>
          {t("inbox.senderLists")}
        </Text>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={(k) => {
          setActiveTab(k as "whitelist" | "blacklist");
          setSelectedListKeys([]);
        }}
        items={[
          { key: "whitelist", label: t("inbox.whitelist") },
          { key: "blacklist", label: t("inbox.blacklist") },
        ]}
        tabBarExtraContent={
          <Space>
            <Select
              value={selectedAgent}
              onChange={(value) => {
                setSelectedAgent(value);
                setSelectedListKeys([]);
              }}
              allowClear
              style={{ width: 160 }}
              placeholder={t("inbox.selectAgent")}
              options={availableAgents.map((id) => ({ label: id, value: id }))}
            />
            <Button
              type="primary"
              icon={<Plus size={14} />}
              onClick={() => setAddModalOpen(true)}
            >
              {t("inbox.addSender")}
            </Button>
          </Space>
        }
      />

      {selectedListKeys.length > 0 && (
        <Space style={{ marginBottom: 8 }}>
          <Popconfirm
            title={t("inbox.confirmRemove")}
            onConfirm={handleBatchRemove}
          >
            <Button
              danger
              size="small"
              icon={<Trash2 size={14} />}
              loading={listBatchLoading}
            >
              {t("inbox.batchRemove")}
            </Button>
          </Popconfirm>
        </Space>
      )}

      <Table
        dataSource={listData}
        columns={listColumns}
        rowKey={(record) => `${record.agent_id}:${record.address}`}
        rowSelection={{
          selectedRowKeys: selectedListKeys,
          onChange: (keys) => setSelectedListKeys(keys as string[]),
        }}
        size="small"
        loading={listLoading}
        pagination={{ pageSize: 10, showSizeChanger: false }}
      />

      {/* === Add Modal === */}
      <Modal
        title={t("inbox.addSender")}
        open={addModalOpen}
        onCancel={() => {
          setAddModalOpen(false);
          setNewAddress("");
          setNewDisplayName("");
          setNewRemark("");
        }}
        onOk={handleAddToList}
        okButtonProps={{ disabled: !newAddress.trim() }}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          <div>
            <Text strong style={{ display: "block", marginBottom: 6 }}>
              {t("inbox.senderAddress")}
              <Text type="danger">{t("inbox.required")}</Text>
            </Text>
            <Input
              placeholder="user@domain.com / *@domain.com"
              value={newAddress}
              onChange={(e) => setNewAddress(e.target.value)}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("inbox.domainWildcardHint")}
            </Text>
          </div>
          <div>
            <Text strong style={{ display: "block", marginBottom: 6 }}>
              {t("inbox.displayName")}
              <Text type="secondary">{t("inbox.optional")}</Text>
            </Text>
            <Input
              placeholder={t("inbox.displayName")}
              value={newDisplayName}
              onChange={(e) => setNewDisplayName(e.target.value)}
            />
          </div>
          <div>
            <Text strong style={{ display: "block", marginBottom: 6 }}>
              {t("inbox.remark")}
              <Text type="secondary">{t("inbox.optional")}</Text>
            </Text>
            <Input
              placeholder={t("inbox.remark")}
              value={newRemark}
              onChange={(e) => setNewRemark(e.target.value)}
            />
          </div>
        </Space>
      </Modal>
    </Drawer>
  );
}
