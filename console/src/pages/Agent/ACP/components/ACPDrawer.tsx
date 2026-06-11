import { Controller } from "react-hook-form";
import type { UseFormReturn } from "react-hook-form";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Link } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
  type ACPAgentConfig,
  type ACPToolParseMode,
} from "../../../../api/types";
import { getWebsiteLang } from "../../../../layouts/constants";
import styles from "../../../Control/Channels/index.module.less";
import { openExternalLink } from "../../../../utils/openExternalLink";

export type ACPFormValues = Record<string, unknown>;

export interface ACPDrawerProps {
  open: boolean;
  activeKey: string | null;
  isCreateMode?: boolean;
  form: UseFormReturn<ACPFormValues>;
  saving: boolean;
  initialValues?: ACPAgentConfig;
  canEditKey?: boolean;
  canDelete?: boolean;
  onClose: () => void;
  onSubmit: (values: ACPFormValues) => void;
  onDelete?: () => void;
}

const TOOL_PARSE_MODE_OPTIONS: { value: ACPToolParseMode; label: string }[] = [
  { value: "call_title", label: "call_title" },
  { value: "update_detail", label: "update_detail" },
  { value: "call_detail", label: "call_detail" },
];

const ACP_DOC_SECTION_HASH = {
  zh: "如何配置外部-runner",
  en: "How-to-configure-external-runners",
} as const;

function getACPDocsUrl(lang: string): string {
  const websiteLang = getWebsiteLang(lang);
  const hash =
    websiteLang === "zh" ? ACP_DOC_SECTION_HASH.zh : ACP_DOC_SECTION_HASH.en;
  return `https://qwenpaw.agentscope.io/docs/acp-integration?lang=${websiteLang}#${hash}`;
}

export function parseArgsText(value: unknown): string[] {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseEnvText(value: unknown): Record<string, string> {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const index = line.indexOf("=");
      if (index >= 0) {
        const key = line.slice(0, index).trim();
        const envValue = line.slice(index + 1).trim();
        if (key) acc[key] = envValue;
      }
      return acc;
    }, {});
}

function findInvalidEnvLine(value: unknown): string | null {
  const lines = String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  for (const line of lines) {
    const index = line.indexOf("=");
    if (index <= 0 || !line.slice(0, index).trim()) {
      return line;
    }
  }
  return null;
}

export function stringifyArgs(args: string[] = []): string {
  return args.join("\n");
}

export function stringifyEnv(env: Record<string, string> = {}): string {
  return Object.entries(env)
    .map(([key, value]) => key + "=" + value)
    .join("\n");
}

export function ACPDrawer({
  open,
  activeKey,
  isCreateMode = false,
  form,
  saving,
  canEditKey = false,
  canDelete = false,
  onClose,
  onSubmit,
  onDelete,
}: ACPDrawerProps) {
  const { t, i18n } = useTranslation();
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = form;

  const title = isCreateMode
    ? t("acp.createTitle")
    : activeKey
    ? t("acp.editTitle") + ": " + activeKey
    : t("acp.editTitle");

  return (
    <Sheet open={open} onOpenChange={(v: boolean) => !v && onClose()}>
      <SheetContent
        side="right"
        className="w-[520px] sm:max-w-[520px] flex flex-col overflow-y-auto"
      >
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
        </SheetHeader>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex-1 overflow-y-auto space-y-4 py-4"
          id="acp-drawer-form"
        >
          <div className="space-y-1">
            <Label htmlFor="agentKey">{t("acp.agentKey")}</Label>
            <Input
              id="agentKey"
              placeholder="my_custom_runner"
              disabled={!canEditKey}
              {...register("agentKey", {
                required: t("acp.agentKeyRequired") as string,
                pattern: {
                  value: /^[A-Za-z0-9_-]+$/,
                  message: t("acp.agentKeyInvalid") as string,
                },
              })}
            />
            {errors.agentKey && (
              <p className="text-sm text-destructive">
                {errors.agentKey.message as string}
              </p>
            )}
          </div>

          <div className="flex items-center space-x-2">
            <Controller
              name="enabled"
              control={control}
              render={({ field }) => (
                <Switch
                  id="enabled"
                  checked={Boolean(field.value)}
                  onCheckedChange={field.onChange}
                />
              )}
            />
            <Label htmlFor="enabled">{t("acp.enabled")}</Label>
          </div>

          <div className="space-y-1">
            <Label htmlFor="command">{t("acp.command")}</Label>
            <Input
              id="command"
              placeholder="qwen"
              {...register("command", {
                required: t("acp.commandRequired") as string,
              })}
            />
            {errors.command && (
              <p className="text-sm text-destructive">
                {errors.command.message as string}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="argsText">{t("acp.args")}</Label>
            <Textarea id="argsText" rows={4} {...register("argsText")} />
          </div>

          <div className="space-y-1">
            <Label htmlFor="envText">{t("acp.env")}</Label>
            <Textarea
              id="envText"
              rows={4}
              {...register("envText", {
                validate: (value: unknown) => {
                  const invalidLine = findInvalidEnvLine(value);
                  if (invalidLine) {
                    return t("acp.envInvalidLine", {
                      line: invalidLine,
                    }) as string;
                  }
                  return true;
                },
              })}
            />
            {errors.envText && (
              <p className="text-sm text-destructive">
                {errors.envText.message as string}
              </p>
            )}
          </div>

          <div className={styles.formTopActions}>
            <button
              type="button"
              className={
                styles.dingtalkDocBtn +
                " inline-flex items-center gap-1 text-sm"
              }
              style={{ color: "var(--primary)" }}
              onClick={() => openExternalLink(getACPDocsUrl(i18n.language))}
              title={t("acp.docsHelp")}
            >
              <Link size={12} />
              {t("acp.docs")}
            </button>
          </div>

          <div className="flex items-center space-x-2">
            <Controller
              name="trusted"
              control={control}
              render={({ field }) => (
                <Switch
                  id="trusted"
                  checked={Boolean(field.value)}
                  onCheckedChange={field.onChange}
                />
              )}
            />
            <Label htmlFor="trusted">{t("acp.trusted")}</Label>
          </div>

          <div className="space-y-1">
            <Label>{t("acp.toolParseMode")}</Label>
            <Controller
              name="tool_parse_mode"
              control={control}
              rules={{
                required: t("acp.toolParseModeRequired") as string,
              }}
              render={({ field }) => (
                <Select
                  value={field.value as string}
                  onValueChange={field.onChange}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TOOL_PARSE_MODE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.tool_parse_mode && (
              <p className="text-sm text-destructive">
                {errors.tool_parse_mode.message as string}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="stdio_buffer_limit_bytes">
              {t("acp.stdioBufferLimit")}
            </Label>
            <Input
              id="stdio_buffer_limit_bytes"
              type="number"
              min={1}
              step={1024}
              placeholder={String(ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES)}
              {...register("stdio_buffer_limit_bytes", {
                required: t("acp.stdioBufferLimitRequired") as string,
                min: {
                  value: 1,
                  message: t("acp.stdioBufferLimitMin") as string,
                },
                valueAsNumber: true,
              })}
            />
            {errors.stdio_buffer_limit_bytes && (
              <p className="text-sm text-destructive">
                {errors.stdio_buffer_limit_bytes.message as string}
              </p>
            )}
          </div>
        </form>

        <SheetFooter className="flex justify-between pt-4 border-t">
          <div>
            {canDelete && (
              <Button variant="destructive" type="button" onClick={onDelete}>
                {t("common.delete")}
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" type="button" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" form="acp-drawer-form" disabled={saving}>
              {saving && (
                <span className="mr-2 h-4 w-4 animate-spin border-2 border-current border-t-transparent rounded-full inline-block" />
              )}
              {t("common.save")}
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
