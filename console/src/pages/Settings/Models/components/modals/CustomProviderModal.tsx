import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";

const formSchema = z.object({
  id: z
    .string()
    .min(1)
    .regex(/^[a-z][a-z0-9_-]{0,63}$/),
  name: z.string().min(1),
  default_base_url: z.string().optional(),
  api_key_prefix: z.string().optional(),
  chat_model: z.enum(["OpenAIChatModel", "AnthropicChatModel"]),
});

type FormValues = z.infer<typeof formSchema>;

interface CustomProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function CustomProviderModal({
  open,
  onClose,
  onSaved,
}: CustomProviderModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      id: "",
      name: "",
      default_base_url: "",
      api_key_prefix: "",
      chat_model: "OpenAIChatModel",
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        id: "",
        name: "",
        default_base_url: "",
        api_key_prefix: "",
        chat_model: "OpenAIChatModel",
      });
    }
  }, [open, form]);

  const handleSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      await api.createCustomProvider({
        id: values.id.trim(),
        name: values.name.trim(),
        default_base_url: values.default_base_url?.trim() || "",
        api_key_prefix: values.api_key_prefix?.trim() || "",
        chat_model: values.chat_model,
      });
      message.success(
        t("models.providerCreated", { name: values.name.trim() }),
      );
      onSaved();
      onClose();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.providerCreateFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("models.addProviderTitle")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("models.addProviderTitle")}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(handleSubmit)}
            className="flex flex-col gap-4 mt-2"
          >
            <FormField
              control={form.control}
              name="id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("models.providerIdLabel")}</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={t("models.providerIdPlaceholder")}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    {t("models.providerIdHint")}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("models.providerNameLabel")}</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={t("models.providerNamePlaceholder")}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="default_base_url"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("models.defaultBaseUrlLabel")}</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={t("models.defaultBaseUrlPlaceholder")}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="chat_model"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("models.protocol")}</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="OpenAIChatModel">
                        {t("models.protocolOpenAI")}
                      </SelectItem>
                      <SelectItem value="AnthropicChatModel">
                        {t("models.protocolAnthropic")}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>{t("models.protocolHint")}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                {t("models.cancel")}
              </Button>
              <Button type="submit" disabled={saving}>
                {t("common.create")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
