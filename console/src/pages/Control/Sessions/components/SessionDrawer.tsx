import { Drawer, Form, Input, Button } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import type { Session } from "./constants";
import styles from "../index.module.less";

interface SessionDrawerProps {
  open: boolean;
  editingSession: Session | null;
  form: FormInstance<Session>;
  saving: boolean;
  onClose: () => void;
  onSubmit: (values: Session) => void;
}

export function SessionDrawer({
  open,
  editingSession,
  form,
  saving,
  onClose,
  onSubmit,
}: SessionDrawerProps) {
  const { t } = useTranslation();

  const drawerFooter = (
    <div className={styles.formActions}>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button type="primary" loading={saving} onClick={() => form.submit()}>
        {t("common.save")}
      </Button>
    </div>
  );

  return (
    <Drawer
      width={520}
      placement="right"
      title={t("sessions.editSession")}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={drawerFooter}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item
          name="name"
          label="name"
          rules={[{ required: false, message: "Please input name" }]}
        >
          <Input placeholder="Session name" />
        </Form.Item>

        {editingSession && (
          <>
            <Form.Item label="id">
              <Input value={editingSession.id} disabled />
            </Form.Item>

            <Form.Item label="session_id">
              <Input value={editingSession.session_id} disabled />
            </Form.Item>

            <Form.Item label="user_id">
              <Input value={editingSession.user_id} disabled />
            </Form.Item>

            <Form.Item label="channel">
              <Input value={editingSession.channel} disabled />
            </Form.Item>
          </>
        )}
      </Form>
    </Drawer>
  );
}
