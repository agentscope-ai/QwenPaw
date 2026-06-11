import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
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

const harvestSchema = z.object({
  name: z.string().min(1, "Please input harvest name"),
  keywords: z.string().min(1, "Please input keywords"),
  frequency: z.enum(["daily", "weekly"]),
});

type HarvestFormValues = z.infer<typeof harvestSchema>;

export function CreateHarvestModal({
  open,
  onClose,
  onSubmit,
}: CreateHarvestModalProps) {
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");

  const selectedTemplate = useMemo(
    () => TEMPLATES.find((template) => template.id === selectedTemplateId),
    [selectedTemplateId],
  );

  const form = useForm<HarvestFormValues>({
    resolver: zodResolver(harvestSchema),
    defaultValues: { name: "", keywords: "", frequency: "daily" },
  });

  const handleSelectTemplate = (templateId: string) => {
    const template = TEMPLATES.find((item) => item.id === templateId);
    if (!template) return;
    setSelectedTemplateId(templateId);
    form.setValue("name", template.name);
    form.setValue("keywords", "");
    form.setValue(
      "frequency",
      template.defaultSchedule.cron.includes("* * *") ? "daily" : "weekly",
    );
  };

  const handleSubmit = (values: HarvestFormValues) => {
    if (!selectedTemplate) return;
    onSubmit({ ...values, templateId: selectedTemplate.id });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose();
      }}
    >
      <DialogContent className="max-w-[860px] w-full">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={18} />
            Create Harvest
          </DialogTitle>
          <DialogDescription className="sr-only">
            Create Harvest
          </DialogDescription>
        </DialogHeader>

        <div className={cn("grid grid-cols-3 gap-3 mt-2", styles.templateGrid)}>
          {TEMPLATES.map((template) => (
            <Card
              key={template.id}
              className={cn(
                "cursor-pointer hover:shadow-md transition-all border-2",
                selectedTemplateId === template.id
                  ? "border-orange-500 bg-orange-50 dark:bg-orange-950/20"
                  : "border-border hover:border-orange-300",
                styles.templateCard,
                selectedTemplateId === template.id && styles.templateCardActive,
              )}
              onClick={() => handleSelectTemplate(template.id)}
            >
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-xl">{template.emoji}</span>
                  <strong className="text-sm font-semibold text-foreground">
                    {template.name}
                  </strong>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {template.description}
                </p>
                <span className="text-xs text-muted-foreground/70 mt-1.5 block">
                  ~{template.estimatedReadTime} min read
                </span>
              </CardContent>
            </Card>
          ))}
        </div>

        {selectedTemplate && (
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(handleSubmit)}
              className={cn("flex flex-col gap-4 mt-4", styles.formSection)}
            >
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Harvest Name</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="keywords"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Keywords</FormLabel>
                    <FormControl>
                      <Textarea
                        rows={3}
                        placeholder="AI, Open Source, Product..."
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="frequency"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Frequency</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="daily">Daily</SelectItem>
                        <SelectItem value="weekly">Weekly</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className={cn("flex justify-end gap-2", styles.actions)}>
                <Button type="button" variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  className="bg-orange-500 hover:bg-orange-600 text-white border-0"
                >
                  Create Harvest
                </Button>
              </div>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
