import { useEffect, useCallback } from "react";
import {
  Drawer,
  Form,
  Input,
  Button,
  Switch,
  Radio,
  InputNumber,
  Select,
} from "@agentscope-ai/design";
import { Space } from "antd";
import type { AgentSACPConfig } from "@/api/types/agent_sacp";
import type { AgentSummary } from "@/api/types/agents";

interface AgentSACPModalProps {
  open: boolean;
  editingAgent: AgentSACPConfig | null;
  saving: boolean;
  internalAgents: AgentSummary[];
  globalAuthKey: string;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}

interface FormValues {
  name: string;
  description: string;
  is_internal: boolean;
  internal_agent_id: string;
  url: string;
  auth_key: string;
  health_check_enabled: boolean;
  health_check_interval: number;
}

const DEFAULT_FORM_VALUES: FormValues = {
  name: "",
  description: "",
  is_internal: true,
  internal_agent_id: "",
  url: "",
  auth_key: "",
  health_check_enabled: true,
  health_check_interval: 300,
};

export function AgentSACPModal({
  open,
  editingAgent,
  saving,
  internalAgents,
  globalAuthKey,
  onClose,
  onSubmit,
}: AgentSACPModalProps) {
  const [form] = Form.useForm<FormValues>();
  const isInternal = Form.useWatch("is_internal", form);

  // Reset or populate form when modal opens
  useEffect(() => {
    if (!open) return;

    if (editingAgent) {
      form.setFieldsValue({
        name: editingAgent.name,
        description: editingAgent.description,
        is_internal: editingAgent.is_internal,
        internal_agent_id: editingAgent.internal_agent_id ?? "",
        url: editingAgent.url,
        auth_key: editingAgent.auth_key,
        health_check_enabled: editingAgent.health_check_enabled,
        health_check_interval: editingAgent.health_check_interval,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        ...DEFAULT_FORM_VALUES,
        auth_key: globalAuthKey,
      });
    }
  }, [open, editingAgent, form, globalAuthKey]);

  // Sync auth_key when globalAuthKey changes (only for new agents)
  useEffect(() => {
    if (!open || editingAgent) return;
    const current = form.getFieldValue("auth_key");
    if (!current && globalAuthKey) {
      form.setFieldValue("auth_key", globalAuthKey);
    }
  }, [globalAuthKey, open, editingAgent, form]);

  // Clear/set fields when type switches
  useEffect(() => {
    if (!open) return;

    if (isInternal) {
      form.setFieldsValue({
        url: "",
        // auth_key intentionally kept — may use global or override
      });
    } else {
      form.setFieldsValue({
        internal_agent_id: "",
        url: form.getFieldValue("url") || "",
        auth_key: form.getFieldValue("auth_key") || "",
      });
    }
  }, [isInternal, open, form]);

  // Auto-fill fields when an internal agent is selected
  const handleInternalAgentChange = useCallback(
    (agentId: string) => {
      const agent = internalAgents.find((a) => a.id === agentId);
      if (agent) {
        form.setFieldsValue({
          name: agent.name,
          description: agent.description ?? "",
          internal_agent_id: agent.id,
          auth_key: globalAuthKey || form.getFieldValue("auth_key") || "",
        });
      }
    },
    [internalAgents, globalAuthKey, form],
  );

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      onSubmit({
        ...values,
        internal_agent_id: values.is_internal
          ? values.internal_agent_id || null
          : null,
        url: values.is_internal ? "" : values.url,
        // auth_key: for internal, allow override; for external, use entered value
        auth_key: values.is_internal
          ? values.auth_key || globalAuthKey
          : values.auth_key,
      });
    });
  };

  return (
    <Drawer
      width={520}
      placement="right"
      title={editingAgent ? "编辑 SACP Agent" : "创建 SACP Agent"}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={
        <Space>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="primary" loading={saving} onClick={handleSubmit}>
            {editingAgent ? "Update" : "Create"}
          </Button>
        </Space>
      }
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ ...DEFAULT_FORM_VALUES, auth_key: globalAuthKey }}
      >
        <Form.Item
          name="is_internal"
          label="Agent 类型"
          rules={[{ required: true, message: "请选择 Agent 类型" }]}
        >
          <Radio.Group>
            <Radio value={true}>自管理</Radio>
            <Radio value={false}>外部</Radio>
          </Radio.Group>
        </Form.Item>

        {isInternal && (
          <>
            {/* Step 1: Select internal agent */}
            <Form.Item
              name="internal_agent_id"
              label="选择内部 Agent"
              rules={[{ required: true, message: "请选择一个内部 Agent" }]}
            >
              <Select
                placeholder="请选择一个内部 Agent..."
                onChange={handleInternalAgentChange}
                allowClear
                showSearch
                optionFilterProp="label"
                options={internalAgents.map((agent) => ({
                  label: agent.name,
                  value: agent.id,
                  title: agent.description || agent.name,
                }))}
              />
            </Form.Item>

            {/* Step 2: Auto-filled name */}
            <Form.Item
              name="name"
              label="名称"
              rules={[{ required: true, message: "请输入名称" }]}
            >
              <Input placeholder="Agent 名称" />
            </Form.Item>

            <Form.Item name="description" label="描述">
              <Input.TextArea rows={3} placeholder="描述（可选）" />
            </Form.Item>

            {/* Auth key: pre-filled with global, can override */}
            <Form.Item
              name="auth_key"
              label="Auth Key"
              extra={
                globalAuthKey
                  ? `使用全局密钥（来自设置），或手动输入覆盖`
                  : "请输入 Auth Key"
              }
            >
              <Input.Password placeholder="全局 Auth Key 或手动输入" />
            </Form.Item>
          </>
        )}

        {!isInternal && (
          <>
            <Form.Item
              name="name"
              label="名称"
              rules={[{ required: true, message: "请输入名称" }]}
            >
              <Input placeholder="请输入名称" />
            </Form.Item>

            <Form.Item name="description" label="描述">
              <Input.TextArea rows={3} placeholder="请输入描述" />
            </Form.Item>

            <Form.Item
              name="url"
              label="URL"
              rules={[{ required: true, message: "请输入 URL" }]}
            >
              <Input placeholder="https://..." />
            </Form.Item>

            <Form.Item
              name="auth_key"
              label="Auth Key"
              rules={[{ required: true, message: "请输入 Auth Key" }]}
            >
              <Input.Password placeholder="请输入 Auth Key" />
            </Form.Item>
          </>
        )}

        <Form.Item
          name="health_check_enabled"
          label="启用健康检查"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="health_check_interval"
          label="健康检查间隔"
          rules={[{ required: true, message: "请输入健康检查间隔" }]}
        >
          <InputNumber
            min={60}
            step={60}
            style={{ width: "100%" }}
            addonAfter="秒"
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
