import { useTranslation } from "react-i18next";
import { useState } from "react";
import { App, Button, Form, Input, Modal } from "antd";
import { KeyRound } from "lucide-react";
import { governanceRequest } from "../../../api/modules/hubGovernance";
import { governanceErrorMessage } from "./errors";
import type { HubUser } from "../../../api/modules/hub";

export default function PasswordReset({ user }: { user: HubUser }) {
  const { t } = useTranslation();
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
        {t("hub.governance.password.reset")}
      </Button>
      <Modal
        open={open}
        title={t("hub.governance.password.title", { username: user.username })}
        onCancel={() => setOpen(false)}
        destroyOnHidden
        confirmLoading={busy}
        onOk={() => form.submit()}
        afterClose={() => form.resetFields()}
      >
        <p>{t("hub.governance.password.hint")}</p>
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
              message.success(t("hub.governance.password.success"));
              setOpen(false);
            } catch (error) {
              message.error(governanceErrorMessage(error, t));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item
            name="password"
            label={t("hub.governance.password.new")}
            rules={[{ required: true, min: 8, max: 1024 }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label={t("hub.governance.password.confirm")}
            dependencies={["password"]}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  value === getFieldValue("password")
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error(t("hub.governance.password.mismatch")),
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
