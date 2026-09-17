import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  adminUsersApi,
  type AdminUser,
  type AdminUserProfileInput,
  type CreateAdminUserRequest,
} from "../../../api/modules/adminUsers";
import { formatGovernanceError } from "./errors";

export default function UsersPage() {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [resettingUser, setResettingUser] = useState<AdminUser | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CreateAdminUserRequest>();
  const [profileForm] = Form.useForm<AdminUserProfileInput>();
  const [passwordForm] = Form.useForm<{
    new_password: string;
    confirm_password: string;
  }>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await adminUsersApi.list());
    } catch (error) {
      message.error(formatGovernanceError(error, t));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const createUser = async (values: CreateAdminUserRequest) => {
    setCreating(true);
    try {
      await adminUsersApi.create(values);
      message.success(t("adminUsers.created", "User created"));
      setCreateOpen(false);
      form.resetFields();
      await load();
    } catch (error) {
      message.error(formatGovernanceError(error, t));
    } finally {
      setCreating(false);
    }
  };

  const updateRole = async (
    user: AdminUser,
    platformRole: AdminUser["platform_role"],
  ) => {
    try {
      await adminUsersApi.setRole(user.id, platformRole);
      await load();
    } catch (error) {
      message.error(formatGovernanceError(error, t));
    }
  };

  const toggleStatus = (user: AdminUser) => {
    const nextStatus = user.status === "active" ? "disabled" : "active";
    modal.confirm({
      title:
        nextStatus === "disabled"
          ? t("adminUsers.disableTitle", "Disable user")
          : t("adminUsers.enableTitle", "Enable user"),
      content: user.username,
      okButtonProps: { danger: nextStatus === "disabled" },
      onOk: async () => {
        try {
          await adminUsersApi.setStatus(user.id, nextStatus);
          await load();
        } catch (error) {
          message.error(formatGovernanceError(error, t));
        }
      },
    });
  };

  const revokeSessions = (user: AdminUser) => {
    modal.confirm({
      title: t("adminUsers.revokeTitle", "Revoke login sessions"),
      content: user.username,
      onOk: async () => {
        try {
          const result = await adminUsersApi.revokeSessions(user.id);
          message.success(
            t("adminUsers.revoked", "Revoked {{count}} sessions", {
              count: result.revoked_sessions,
            }),
          );
        } catch (error) {
          message.error(formatGovernanceError(error, t));
        }
      },
    });
  };

  const openProfile = (user: AdminUser) => {
    setEditingUser(user);
    profileForm.setFieldsValue({
      username: user.username,
      display_name: user.display_name ?? "",
      email: user.email ?? "",
      phone: user.phone ?? "",
      department: user.department ?? "",
      job_title: user.job_title ?? "",
      remark: user.remark ?? "",
    });
  };

  const saveProfile = async (values: AdminUserProfileInput) => {
    if (!editingUser) return;
    setSaving(true);
    try {
      await adminUsersApi.updateProfile(editingUser.id, values);
      message.success(t("adminUsers.profileSaved", "User profile saved"));
      setEditingUser(null);
      await load();
    } catch (error) {
      message.error(formatGovernanceError(error, t));
    } finally {
      setSaving(false);
    }
  };

  const resetPassword = async (values: { new_password: string }) => {
    if (!resettingUser) return;
    setSaving(true);
    try {
      const result = await adminUsersApi.resetPassword(
        resettingUser.id,
        values.new_password,
      );
      message.success(
        t(
          "adminUsers.passwordResetDone",
          "Password reset; {{count}} sessions revoked",
          {
            count: result.revoked_sessions,
          },
        ),
      );
      setResettingUser(null);
      passwordForm.resetFields();
    } catch (error) {
      message.error(formatGovernanceError(error, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card>
        <Space
          style={{ width: "100%", justifyContent: "space-between" }}
          align="start"
        >
          <div>
            <Typography.Title level={3} style={{ marginTop: 0 }}>
              {t("adminUsers.title", "User Management")}
            </Typography.Title>
            <Typography.Text type="secondary">
              {t(
                "adminUsers.description",
                "Create users, manage roles and status, and revoke login sessions.",
              )}
            </Typography.Text>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>
              {t("common.refresh", "Refresh")}
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
            >
              {t("adminUsers.create", "Create User")}
            </Button>
          </Space>
        </Space>

        <Table<AdminUser>
          style={{ marginTop: 24 }}
          rowKey="id"
          loading={loading}
          dataSource={users}
          pagination={false}
          columns={[
            {
              title: t("adminUsers.username", "Username"),
              dataIndex: "username",
            },
            {
              title: t("adminUsers.role", "Role"),
              render: (_, user) => (
                <Select
                  aria-label={`${user.username} role`}
                  value={user.platform_role}
                  style={{ width: 120 }}
                  onChange={(value) => void updateRole(user, value)}
                  options={[
                    {
                      value: "admin",
                      label: t("account.roleAdmin", "Administrator"),
                    },
                    {
                      value: "member",
                      label: t("account.roleMember", "Member"),
                    },
                  ]}
                />
              ),
            },
            {
              title: t("adminUsers.status", "Status"),
              render: (_, user) => (
                <Tag color={user.status === "active" ? "green" : "default"}>
                  {user.status === "active"
                    ? t("adminUsers.active", "Active")
                    : t("adminUsers.disabled", "Disabled")}
                </Tag>
              ),
            },
            {
              title: t("adminUsers.actions", "Actions"),
              render: (_, user) => (
                <Space>
                  <Button size="small" onClick={() => openProfile(user)}>
                    {t("adminUsers.editProfile", "Edit Profile")}
                  </Button>
                  <Button size="small" onClick={() => setResettingUser(user)}>
                    {t("adminUsers.resetPassword", "Reset Password")}
                  </Button>
                  <Button size="small" onClick={() => toggleStatus(user)}>
                    {user.status === "active"
                      ? t("adminUsers.disable", "Disable")
                      : t("adminUsers.enable", "Enable")}
                  </Button>
                  <Button size="small" onClick={() => revokeSessions(user)}>
                    {t("adminUsers.revokeSessions", "Revoke Sessions")}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={t("adminUsers.create", "Create User")}
        open={createOpen}
        okText={t("common.create", "Create")}
        cancelText={t("common.cancel", "Cancel")}
        confirmLoading={creating}
        onOk={() => form.submit()}
        onCancel={() => {
          setCreateOpen(false);
          form.resetFields();
        }}
        destroyOnHidden
      >
        <Form<CreateAdminUserRequest>
          form={form}
          layout="vertical"
          initialValues={{ platform_role: "member" }}
          onFinish={(values) => void createUser(values)}
        >
          <Form.Item
            name="username"
            label={t("adminUsers.username", "Username")}
            rules={[{ required: true }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label={t("adminUsers.initialPassword", "Initial Password")}
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="platform_role"
            label={t("adminUsers.role", "Role")}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                {
                  value: "member",
                  label: t("account.roleMember", "Member"),
                },
                {
                  value: "admin",
                  label: t("account.roleAdmin", "Administrator"),
                },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("adminUsers.editProfile", "Edit Profile")}
        open={Boolean(editingUser)}
        confirmLoading={saving}
        onOk={() => profileForm.submit()}
        onCancel={() => setEditingUser(null)}
        destroyOnHidden
      >
        <Form<AdminUserProfileInput>
          form={profileForm}
          layout="vertical"
          onFinish={(values) => void saveProfile(values)}
        >
          <Form.Item
            name="username"
            label={t("adminUsers.username", "Username")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="display_name"
            label={t("account.displayName", "Display Name")}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="email"
            label={t("account.email", "Email")}
            rules={[{ type: "email" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="phone" label={t("account.phone", "Phone")}>
            <Input />
          </Form.Item>
          <Form.Item
            name="department"
            label={t("account.department", "Department")}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="job_title"
            label={t("account.jobTitle", "Job Title")}
          >
            <Input />
          </Form.Item>
          <Form.Item name="remark" label={t("account.remark", "Remark")}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("adminUsers.resetPassword", "Reset Password")}
        open={Boolean(resettingUser)}
        confirmLoading={saving}
        onOk={() => passwordForm.submit()}
        onCancel={() => {
          setResettingUser(null);
          passwordForm.resetFields();
        }}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          {resettingUser?.username} ·{" "}
          {t(
            "adminUsers.resetPasswordHint",
            "All active sessions for this user will be revoked.",
          )}
        </Typography.Paragraph>
        <Form
          form={passwordForm}
          layout="vertical"
          onFinish={(values) => void resetPassword(values)}
        >
          <Form.Item
            name="new_password"
            label={t("account.newPassword", "New Password")}
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label={t("account.confirmNewPassword", "Confirm New Password")}
            dependencies={["new_password"]}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  return value === getFieldValue("new_password")
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error(
                          t(
                            "account.passwordMismatch",
                            "Passwords do not match",
                          ),
                        ),
                      );
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
