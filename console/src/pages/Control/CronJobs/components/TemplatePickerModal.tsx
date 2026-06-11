import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CronTemplateCategory, CronTemplateDefinition } from "./templates";
import { CRON_TEMPLATES } from "./templates";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="max-w-[900px] w-full">
        <DialogHeader>
          <DialogTitle>{t("cronJobs.templateModalTitle")}</DialogTitle>
        </DialogHeader>

        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-muted-foreground">
            {t("cronJobs.templateModalDescription")}
          </p>
          <Select
            value={category}
            onValueChange={(v) => setCategory(v as CronTemplateCategory)}
          >
            <SelectTrigger className="w-[220px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="cron">
                {t("cronJobs.scheduleTypeRecurring")}
              </SelectItem>
              <SelectItem value="once">
                {t("cronJobs.scheduleTypeOnce")}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
          {filteredTemplates.map((template) => (
            <div
              key={template.id}
              className="border rounded-lg p-4 flex flex-col gap-2 hover:border-primary/50 transition-colors"
            >
              <div className="font-medium text-sm">{t(template.titleKey)}</div>
              <div className="text-xs text-muted-foreground flex-1">
                {t(template.descriptionKey)}
              </div>
              <div className="text-xs text-muted-foreground">
                {t(template.frequencyKey)}
              </div>
              <div className="mt-2">
                <Button size="sm" onClick={() => handleUseTemplate(template)}>
                  {t("cronJobs.useTemplate")}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
