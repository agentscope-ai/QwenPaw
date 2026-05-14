import { useMemo, useState } from "react";
import { Modal, Form, Input, Select, Button, Card } from "antd";
import { Sparkles } from "lucide-react";
import type { HarvestTemplate } from "../types";
import styles from "./CreateHarvestModal.module.less";

interface CreateHarvestModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (values: {
    name: string;
    keywords: string;
    templateId: string;
    frequency: string;
  }) => void;
}

const TEMPLATES: HarvestTemplate[] = [
  {
    id: "tech-daily",
    name: "Tech Frontier Harvest",
    emoji: "🚀",
    description: "Daily updates on AI, tech trends and open source.",
    estimatedReadTime: 8,
    defaultSchedule: { cron: "0 9 * * *", timezone: "Asia/Shanghai" },
  },
  {
    id: "industry-weekly",
    name: "Industry Intelligence",
    emoji: "📊",
    description: "Weekly deep-dive analysis of industry trends.",
    estimatedReadTime: 15,
    defaultSchedule: { cron: "0 10 * * 1", timezone: "Asia/Shanghai" },
  },
  {
    id: "competitor-daily",
    name: "Competitor Watch",
    emoji: "🏢",
    description: "Track competitor moves and key market signals.",
    estimatedReadTime: 6,
    defaultSchedule: { cron: "0 18 * * *", timezone: "Asia/Shanghai" },
  },
];

export function CreateHarvestModal({
  open,
  onClose,
  onSubmit,
}: CreateHarvestModalProps) {
  const [form] = Form.useForm();
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");

  const selectedTemplate = useMemo(
    () => TEMPLATES.find((template) => template.id === selectedTemplateId),
    [selectedTemplateId],
  );

  const handleSelectTemplate = (templateId: string) => {
    const template = TEMPLATES.find((item) => item.id === templateId);
    if (!template) return;
    setSelectedTemplateId(templateId);
    form.setFieldsValue({
      name: template.name,
      keywords: "",
      frequency: template.defaultSchedule.cron.includes("* * *")
        ? "daily"
        : "weekly",
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      title={
        <span className={styles.modalTitle}>
          <Sparkles size={18} /> Create Harvest
        </span>
      }
      destroyOnClose
    >
      <div className={styles.templateGrid}>
        {TEMPLATES.map((template) => (
          <Card
            key={template.id}
            hoverable
            className={`${styles.templateCard} ${
              selectedTemplateId === template.id
                ? styles.templateCardActive
                : ""
            }`}
            onClick={() => handleSelectTemplate(template.id)}
          >
            <div className={styles.templateHeader}>
              <span className={styles.templateEmoji}>{template.emoji}</span>
              <strong>{template.name}</strong>
            </div>
            <p className={styles.templateDesc}>{template.description}</p>
            <span className={styles.templateMeta}>
              ~{template.estimatedReadTime} min read
            </span>
          </Card>
        ))}
      </div>

      {selectedTemplate ? (
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) =>
            onSubmit({
              ...values,
              templateId: selectedTemplate.id,
            })
          }
          className={styles.formSection}
        >
          <Form.Item
            name="name"
            label="Harvest Name"
            rules={[{ required: true, message: "Please input harvest name" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="keywords"
            label="Keywords"
            rules={[{ required: true, message: "Please input keywords" }]}
          >
            <Input.TextArea
              rows={3}
              placeholder="AI, Open Source, Product..."
            />
          </Form.Item>
          <Form.Item name="frequency" label="Frequency" initialValue="daily">
            <Select
              options={[
                { label: "Daily", value: "daily" },
                { label: "Weekly", value: "weekly" },
              ]}
            />
          </Form.Item>
          <div className={styles.actions}>
            <Button onClick={onClose}>Cancel</Button>
            <Button type="primary" htmlType="submit">
              Create Harvest
            </Button>
          </div>
        </Form>
      ) : null}
    </Modal>
  );
}
