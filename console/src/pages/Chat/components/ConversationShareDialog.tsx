import { Button, Modal, Select, Spin } from "antd";
import { useEffect, useState } from "react";
import { chatApi } from "../../../api/modules/chat";
import type {
  ConversationMember,
  ConversationShareCandidate,
} from "../../../api/types/chat";
import { useAppMessage } from "../../../hooks/useAppMessage";

interface Props {
  open: boolean;
  chatId: string | null;
  onClose: () => void;
}

export default function ConversationShareDialog({
  open,
  chatId,
  onClose,
}: Props) {
  const { message } = useAppMessage();
  const [members, setMembers] = useState<ConversationMember[]>([]);
  const [candidates, setCandidates] = useState<ConversationShareCandidate[]>(
    [],
  );
  const [selectedUser, setSelectedUser] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    if (!chatId) return;
    setLoading(true);
    try {
      const [nextMembers, nextCandidates] = await Promise.all([
        chatApi.listConversationMembers(chatId),
        chatApi.listConversationShareCandidates(chatId),
      ]);
      setMembers(nextMembers);
      setCandidates(nextCandidates);
      setSelectedUser(undefined);
    } catch (error) {
      message.error("加载会话分享信息失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void load();
  }, [open, chatId]);

  const add = async () => {
    if (!chatId || !selectedUser) return;
    setSaving(true);
    try {
      await chatApi.addConversationViewer(chatId, selectedUser);
      message.success("已添加会话查看者");
      await load();
    } catch {
      message.error("添加会话查看者失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (userId: string) => {
    if (!chatId) return;
    setSaving(true);
    try {
      await chatApi.removeConversationViewer(chatId, userId);
      setMembers((current) =>
        current.filter((member) => member.user_id !== userId),
      );
      message.success("已移除会话查看者");
    } catch {
      message.error("移除会话查看者失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title="分享会话（仅查看）"
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      {loading ? (
        <Spin />
      ) : (
        <>
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            <Select
              style={{ flex: 1 }}
              placeholder="选择当前 Agent 可使用的用户"
              value={selectedUser}
              onChange={setSelectedUser}
              options={candidates.map((candidate) => ({
                value: candidate.user_id,
                label: candidate.username,
              }))}
            />
            <Button
              type="primary"
              loading={saving}
              disabled={!selectedUser}
              onClick={add}
            >
              添加
            </Button>
          </div>
          {members.length === 0 ? (
            <div>暂无查看者</div>
          ) : (
            members.map((member) => (
              <div
                key={member.user_id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "8px 0",
                }}
              >
                <span>{member.username}</span>
                <Button
                  danger
                  type="link"
                  loading={saving}
                  onClick={() => remove(member.user_id)}
                >
                  移除
                </Button>
              </div>
            ))
          )}
        </>
      )}
    </Modal>
  );
}
