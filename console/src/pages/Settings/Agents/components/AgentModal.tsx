import {
  Avatar,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Typography,
  Upload,
  message,
} from "antd";
import { DeleteOutlined, UploadOutlined } from "@ant-design/icons";
import { Bot } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AgentProfileConfig } from "@/api/types/agents";
import styles from "../index.module.less";

interface AgentModalProps {
  open: boolean;
  editingAgent: AgentProfileConfig | null;
  form: ReturnType<typeof Form.useForm>[0];
  avatarPreviewUrl?: string;
  onAvatarChange: (file: File) => void;
  onAvatarRemove: () => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
}

export function AgentModal({
  open,
  editingAgent,
  form,
  avatarPreviewUrl,
  onAvatarChange,
  onAvatarRemove,
  onSave,
  onCancel,
}: AgentModalProps) {
  const { t } = useTranslation();

  const beforeUpload = (file: File) => {
    const allowedTypes = ["image/png", "image/jpeg", "image/webp"];
    if (!allowedTypes.includes(file.type)) {
      message.error(t("agent.avatarInvalidType"));
      return Upload.LIST_IGNORE;
    }

    if (file.size > 2 * 1024 * 1024) {
      message.error(t("agent.avatarTooLarge"));
      return Upload.LIST_IGNORE;
    }

    onAvatarChange(file);
    return false;
  };

  return (
    <Modal
      title={
        editingAgent
          ? t("agent.editTitle", { name: editingAgent.name })
          : t("agent.createTitle")
      }
      open={open}
      onOk={onSave}
      onCancel={onCancel}
      width={600}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical" autoComplete="off">
        {editingAgent && (
          <Form.Item name="id" label={t("agent.id")}>
            <Input disabled />
          </Form.Item>
        )}
        <Form.Item
          name="name"
          label={t("agent.name")}
          rules={[{ required: true, message: t("agent.nameRequired") }]}
        >
          <Input placeholder={t("agent.namePlaceholder")} />
        </Form.Item>
        <Form.Item name="description" label={t("agent.description")}>
          <Input.TextArea
            placeholder={t("agent.descriptionPlaceholder")}
            rows={3}
          />
        </Form.Item>
        <Form.Item
          label={t("agent.avatar")}
          extra={
            <span className={styles.agentAvatarHelp}>
              {t("agent.avatarHelp")}
            </span>
          }
        >
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space size={16} align="center">
              <Avatar
                size={72}
                shape="square"
                src={avatarPreviewUrl}
                icon={<Bot size={28} strokeWidth={2} />}
                className={styles.agentAvatarPlaceholder}
              />
              <Space direction="vertical" size={4}>
                <Typography.Text className={styles.agentAvatarMeta}>
                  {t("agent.avatarRecommended")}
                </Typography.Text>
                <Space wrap>
                  <Upload
                    accept="image/png,image/jpeg,image/webp"
                    showUploadList={false}
                    beforeUpload={beforeUpload}
                  >
                    <Button icon={<UploadOutlined />}>
                      {t("common.upload")}
                    </Button>
                  </Upload>
                  {avatarPreviewUrl && (
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      onClick={onAvatarRemove}
                    >
                      {t("common.delete")}
                    </Button>
                  )}
                </Space>
              </Space>
            </Space>
          </Space>
        </Form.Item>
        <Form.Item
          name="workspace_dir"
          label={t("agent.workspace")}
          help={!editingAgent ? t("agent.workspaceHelp") : undefined}
        >
          <Input
            placeholder="~/.copaw/workspaces/my-agent"
            disabled={!!editingAgent}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
