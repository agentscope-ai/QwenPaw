import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import type { AgentMember, ShareableUser } from "@/api/types/agents";
import { useAppMessage } from "@/hooks/useAppMessage";

interface AgentMembersModalProps {
  open: boolean;
  agentId: string | null;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
}

export function AgentMembersModal({
  open,
  agentId,
  onClose,
  onChanged,
}: AgentMembersModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [members, setMembers] = useState<AgentMember[]>([]);
  const [users, setUsers] = useState<ShareableUser[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string>();
  const [role, setRole] = useState<AgentMember["role"]>("user");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!open || !agentId) return;
    setLoading(true);
    try {
      const [memberList, directory] = await Promise.all([
        agentsApi.listMembers(agentId),
        agentsApi.listShareableUsers(),
      ]);
      setMembers(memberList);
      setUsers(directory);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  }, [agentId, message, open, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const availableUsers = useMemo(() => {
    const memberIds = new Set(members.map((member) => member.user_id));
    return users.filter((user) => !memberIds.has(user.id));
  }, [members, users]);

  const grant = async () => {
    if (!agentId || !selectedUserId) return;
    await agentsApi.grantMember(agentId, selectedUserId, role);
    setSelectedUserId(undefined);
    await load();
    await onChanged();
  };

  const revoke = async (userId: string) => {
    if (!agentId) return;
    await agentsApi.revokeMember(agentId, userId);
    await load();
    await onChanged();
  };

  const transfer = async (userId: string) => {
    if (!agentId) return;
    await agentsApi.transferOwner(agentId, userId);
    await onChanged();
    onClose();
  };

  return (
    <Modal
      title={t("agent.manageMembers")}
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>{t("common.close")}</Button>}
      width={720}
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          aria-label={t("agent.memberUser")}
          value={selectedUserId}
          onChange={setSelectedUserId}
          placeholder={t("agent.memberUser")}
          style={{ width: 220 }}
          options={availableUsers.map((user) => ({
            value: user.id,
            label: user.username,
          }))}
        />
        <Select
          aria-label={t("agent.memberRole")}
          value={role}
          onChange={setRole}
          style={{ width: 160 }}
          options={[
            { value: "user", label: t("agent.accessRole.user") },
            {
              value: "collaborator",
              label: t("agent.accessRole.collaborator"),
            },
          ]}
        />
        <Button type="primary" disabled={!selectedUserId} onClick={grant}>
          {t("agent.addMember")}
        </Button>
      </Space>
      <Table
        rowKey="user_id"
        loading={loading}
        pagination={false}
        dataSource={members}
        columns={[
          { title: t("agent.memberUser"), dataIndex: "username" },
          {
            title: t("agent.memberRole"),
            dataIndex: "role",
            render: (value: AgentMember["role"]) => (
              <Tag>{t(`agent.accessRole.${value}`)}</Tag>
            ),
          },
          {
            title: t("common.actions"),
            render: (_value, member: AgentMember) => (
              <Space>
                <Popconfirm
                  title={t("agent.transferOwnerConfirm")}
                  onConfirm={() => transfer(member.user_id)}
                >
                  <Button size="small">{t("agent.transferOwner")}</Button>
                </Popconfirm>
                <Popconfirm
                  title={t("agent.revokeMemberConfirm")}
                  onConfirm={() => revoke(member.user_id)}
                >
                  <Button size="small" danger>
                    {t("agent.revokeMember")}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
    </Modal>
  );
}
