import { useState } from "react";
import { App, Button, Form, Input, Modal } from "antd";
import { KeyRound } from "lucide-react";
import { governanceRequest } from "../../../api/modules/hubGovernance";
import type { HubUser } from "../../../api/modules/hub";
import { useGovernanceText } from "./shared";

export default function PasswordReset({ user }: { user: HubUser }) {
  const text = useGovernanceText();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  if (user.role !== "user") return null;
  return (
    <>
      <Button
        size="small"
        icon={<KeyRound size={13} />}
        onClick={() => setOpen(true)}
      >
        {text("重置密码", "Reset password")}
      </Button>
      <Modal
        open={open}
        title={`${text("重置密码", "Reset password")} · ${user.username}`}
        onCancel={() => setOpen(false)}
        destroyOnHidden
        confirmLoading={busy}
        onOk={() => form.submit()}
        afterClose={() => form.resetFields()}
      >
        <p>
          {text(
            "旧密码及登录凭证将失效，历史数据保留。请自行安全交付新密码。",
            "Old passwords and login tokens will expire. Data is preserved. Share the new password securely.",
          )}
        </p>
        <Form
          form={form}
          layout="vertical"
          onFinish={async ({ password }) => {
            setBusy(true);
            try {
              await governanceRequest(
                `admin/users/${user.user_id}/password`,
                "POST",
                { new_password: password },
              );
              message.success(text("密码已重置", "Password reset"));
              setOpen(false);
            } catch (error) {
              message.error((error as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item
            name="password"
            label={text("新密码", "New password")}
            rules={[{ required: true, min: 8, max: 1024 }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label={text("确认密码", "Confirm password")}
            dependencies={["password"]}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  value === getFieldValue("password")
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error(text("密码不一致", "Passwords differ")),
                      ),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
