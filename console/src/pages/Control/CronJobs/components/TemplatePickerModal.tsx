import { useMemo, useState } from "react";
import { Button, Modal, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { CronTemplateCategory, CronTemplateDefinition } from "./templates";
import { CRON_TEMPLATES } from "./templates";
import styles from "../index.module.less";

interface TemplatePickerModalProps {
  open: boolean;
  timezone: string;
  onCancel: () => void;
  onUseTemplate: (templateValues: Record<string, unknown>) => void;
}

export function TemplatePickerModal({
  open,
  timezone,
  onCancel,
  onUseTemplate,
}: TemplatePickerModalProps) {
  const { t } = useTranslation();
  const [category, setCategory] = useState<CronTemplateCategory>("cron");

  const filteredTemplates = useMemo(
    () => CRON_TEMPLATES.filter((template) => template.category === category),
    [category],
  );

  const categoryOptions = [
    {
      label: t("cronJobs.scheduleTypeRecurring"),
      value: "cron",
    },
    {
      label: t("cronJobs.scheduleTypeOnce"),
      value: "once",
    },
  ];

  const handleUseTemplate = (template: CronTemplateDefinition) => {
    const templateValues = template.toFormValues(timezone);
    onUseTemplate({
      ...templateValues,
      name: t(template.titleKey),
      text:
        templateValues.task_type === "agent"
          ? ""
          : (templateValues.text as string) ||
            (t(template.descriptionKey) as string),
    });
  };

  return (
    <Modal
      visible={open}
      title={t("cronJobs.templateModalTitle")}
      footer={null}
      width={860}
      onCancel={onCancel}
    >
      <div className={styles.templateModalHeader}>
        <div className={styles.templateModalDesc}>
          {t("cronJobs.templateModalDescription")}
        </div>
        <Select<CronTemplateCategory>
          value={category}
          options={categoryOptions}
          style={{ width: 220 }}
          onChange={setCategory}
        />
      </div>
      <div className={styles.templateGrid}>
        {filteredTemplates.map((template) => (
          <div key={template.id} className={styles.templateCard}>
            <div className={styles.templateTitle}>{t(template.titleKey)}</div>
            <div className={styles.templateDesc}>
              {t(template.descriptionKey)}
            </div>
            <div className={styles.templateMeta}>
              {t(template.frequencyKey)}
            </div>
            <div className={styles.templateActions}>
              <Button
                type="primary"
                onClick={() => handleUseTemplate(template)}
              >
                {t("cronJobs.useTemplate")}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}
