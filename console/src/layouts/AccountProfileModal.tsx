import { Button, Form, Input, Modal, Tabs } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../hooks/useAppMessage";
import { useAuthStore } from "../stores/authStore";

interface AccountProfileModalProps {
  open: boolean;
  onClose: () => void;
  onPasswordChanged: () => void;
}

interface ProfileFormValues {
  username: string;
  display_name?: string;
  email?: string;
  phone?: string;
  department?: string;
  job_title?: string;
  remark?: string;
}

interface PasswordFormValues {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

export default function AccountProfileModal({
  open,
  onClose,
  onPasswordChanged,
}: AccountProfileModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const user = useAuthStore((state) => state.user);
  const updateProfile = useAuthStore((state) => state.updateProfile);
  const changePassword = useAuthStore((state) => state.changePassword);
  const [profileForm] = Form.useForm<ProfileFormValues>();
  const [passwordForm] = Form.useForm<PasswordFormValues>();
  const [loading, setLoading] = useState(false);

  const saveProfile = async (values: ProfileFormValues) => {
    setLoading(true);
    try {
      await updateProfile(values);
      message.success(t("account.profileSaved", "账户资料已保存"));
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("account.updateFailed"),
      );
    } finally {
      setLoading(false);
    }
  };

  const savePassword = async (values: PasswordFormValues) => {
    setLoading(true);
    try {
      await changePassword(values.current_password, values.new_password);
      passwordForm.resetFields();
      onPasswordChanged();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("account.updateFailed"),
      );
    } finally {
      setLoading(false);
    }
  };

  const profile = (
    <Form<ProfileFormValues>
      form={profileForm}
      layout="vertical"
      initialValues={{
        username: user?.username,
        display_name: user?.display_name ?? "",
        email: user?.email ?? "",
        phone: user?.phone ?? "",
        department: user?.department ?? "",
        job_title: user?.job_title ?? "",
        remark: user?.remark ?? "",
      }}
      onFinish={(values) => void saveProfile(values)}
    >
      <Form.Item
        name="username"
        label={t("account.username", "用户名")}
        rules={[{ required: true }]}
      >
        <Input />
      </Form.Item>
      <Form.Item name="display_name" label={t("account.displayName", "显示名")}>
        <Input />
      </Form.Item>
      <Form.Item
        name="email"
        label={t("account.email", "邮箱")}
        rules={[{ type: "email" }]}
      >
        <Input />
      </Form.Item>
      <Form.Item name="phone" label={t("account.phone", "手机号")}>
        <Input />
      </Form.Item>
      <Form.Item name="department" label={t("account.department", "部门")}>
        <Input />
      </Form.Item>
      <Form.Item name="job_title" label={t("account.jobTitle", "职位")}>
        <Input />
      </Form.Item>
      <Form.Item name="remark" label={t("account.remark", "备注")}>
        <Input.TextArea rows={3} />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={loading} block>
        {t("account.saveProfile", "保存资料")}
      </Button>
    </Form>
  );

  const password = (
    <Form<PasswordFormValues>
      form={passwordForm}
      layout="vertical"
      onFinish={(values) => void savePassword(values)}
    >
      <Form.Item
        name="current_password"
        label={t("account.oldPassword", "旧密码")}
        rules={[{ required: true }]}
      >
        <Input.Password autoComplete="current-password" />
      </Form.Item>
      <Form.Item
        name="new_password"
        label={t("account.newPassword", "新密码")}
        rules={[{ required: true }]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name="confirm_password"
        label={t("account.confirmNewPassword", "确认新密码")}
        dependencies={["new_password"]}
        rules={[
          { required: true },
          ({ getFieldValue }) => ({
            validator(_, value) {
              return value === getFieldValue("new_password")
                ? Promise.resolve()
                : Promise.reject(
                    new Error(
                      t("account.passwordMismatch", "两次输入的新密码不一致"),
                    ),
                  );
            },
          }),
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={loading} block>
        {t("account.changePassword", "修改密码")}
      </Button>
    </Form>
  );

  return (
    <Modal
      open={open}
      title={t("account.information", "账户信息")}
      onCancel={onClose}
      footer={null}
      centered
      destroyOnHidden
    >
      <Tabs
        items={[
          {
            key: "profile",
            label: t("account.basicProfile", "基本资料"),
            children: profile,
          },
          {
            key: "password",
            label: t("account.changePassword", "修改密码"),
            children: password,
          },
        ]}
      />
    </Modal>
  );
}
