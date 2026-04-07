import { useState, useEffect } from "react";
import { Modal, Form, Input, message } from "antd";
import { useTranslation } from "react-i18next";
import type { Meeting } from "@/api/types/meetings";
import { meetingsApi } from "@/api/modules/meetings";

const { TextArea } = Input;

interface EditMeetingModalProps {
  open: boolean;
  meeting: Meeting | null;
  onCancel: () => void;
  onUpdated?: () => void;
}

export function EditMeetingModal({
  open,
  meeting,
  onCancel,
  onUpdated,
}: EditMeetingModalProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && meeting) {
      form.setFieldsValue({
        meeting_name: meeting.meeting_name,
        topic_title: meeting.topic?.title || meeting.topic_title,
        topic_description: meeting.topic?.description,
        topic_context: meeting.topic?.context,
      });
    }
  }, [open, meeting, form]);

  const handleSave = async () => {
    if (!meeting) return;

    const values = form.getFieldsValue();

    setSaving(true);
    try {
      await meetingsApi.updateMeeting(meeting.meeting_id, {
        meeting_name: values.meeting_name,
        topic: {
          title: values.topic_title,
          description: values.topic_description,
          context: values.topic_context,
        },
      });
      message.success(t("meetings.updateSuccess") || "会议更新成功");
      onUpdated?.();
      onCancel();
    } catch (err: any) {
      message.error(
        err.message || t("meetings.updateFailed") || "会议更新失败",
      );
      throw err;
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("meetings.editMeeting") || "编辑会议"}
      open={open}
      onCancel={onCancel}
      onOk={handleSave}
      okText={t("common.save") || "保存"}
      cancelText={t("common.cancel")}
      confirmLoading={saving}
      width={600}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="meeting_name"
          label={t("meetings.form.name") || "会议名称"}
        >
          <Input />
        </Form.Item>

        <Form.Item
          name="topic_title"
          label={t("meetings.form.topicTitle") || "议题标题"}
        >
          <Input />
        </Form.Item>

        <Form.Item
          name="topic_description"
          label={t("meetings.form.topicDescription") || "议题描述"}
        >
          <TextArea rows={3} />
        </Form.Item>

        <Form.Item
          name="topic_context"
          label={t("meetings.form.topicContext") || "议题背景"}
        >
          <TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
