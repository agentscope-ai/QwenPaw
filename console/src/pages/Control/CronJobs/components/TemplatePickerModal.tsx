import { useMemo, useState } from "react";
import { Button } from "@agentscope-ai/design";
import { Segmented } from "antd";
import { X, CalendarClock } from "lucide-react";
import { SharedModal } from "@/components/interaction/SharedModal";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { Cascade } from "@/components/interaction/Cascade";
import { useTranslation } from "react-i18next";
import type { CronTemplateCategory, CronTemplateDefinition } from "./templates";
import { CRON_TEMPLATES } from "./templates";
import styles from "../index.module.less";

interface TemplatePickerModalProps {
  open: boolean;
  surfaceId?: string;
  timezone: string;
  onCancel: () => void;
  onUseTemplate: (templateValues: Record<string, unknown>) => void;
}

export function TemplatePickerModal({
  open,
  surfaceId,
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
      value: "cron" as const,
    },
    {
      label: t("cronJobs.scheduleTypeOnce"),
      value: "once" as const,
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
    <SharedModal
      open={open}
      surfaceId={surfaceId}
      closeIcon={<X size={18} />}
      title={t("cronJobs.templateModalTitle")}
      footer={null}
      width={860}
      onCancel={onCancel}
    >
      <div className={styles.templateModalHeader}>
        <Segmented<CronTemplateCategory>
          aria-label={t("cronJobs.scheduleType")}
          value={category}
          options={categoryOptions}
          onChange={setCategory}
        />
      </div>
      <div className={styles.templateGrid}>
        {filteredTemplates.map((template, index) => (
          <Cascade key={template.id} index={index}>
            <InteractiveCard tilt={2} className={styles.templateCard}>
              <CalendarClock size={20} aria-hidden />
              <div className={styles.templateTitle}>{t(template.titleKey)}</div>
              <div className={styles.templateDesc}>
                {t(template.descriptionKey)}
              </div>
              <div className={styles.templateMeta}>
                {t(template.frequencyKey)}
              </div>
              <div className={styles.templateActions}>
                <Button data-press onClick={() => handleUseTemplate(template)}>
                  {t("cronJobs.useTemplate")}
                </Button>
              </div>
            </InteractiveCard>
          </Cascade>
        ))}
      </div>
    </SharedModal>
  );
}
