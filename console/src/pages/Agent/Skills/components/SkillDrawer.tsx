import { useState, useEffect, useRef } from "react";
import type { UseFormReturn } from "react-hook-form";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import { Zap, StopCircle } from "lucide-react";
import type { SkillSpec } from "../../../../api/types";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import { api } from "../../../../api";
import { deriveInstalledFromLabel } from "../../../../utils/skill";

export function parseFrontmatter(
  content: string,
): Record<string, string> | null {
  try {
    const trimmed = content.trim();
    if (!trimmed.startsWith("---")) return null;
    const endIndex = trimmed.indexOf("---", 3);
    if (endIndex === -1) return null;
    const frontmatterBlock = trimmed.slice(3, endIndex).trim();
    if (!frontmatterBlock) return null;
    const result: Record<string, string> = {};
    for (const line of frontmatterBlock.split("\n")) {
      const colonIndex = line.indexOf(":");
      if (colonIndex > 0) {
        const key = line.slice(0, colonIndex).trim();
        const value = line.slice(colonIndex + 1).trim();
        result[key] = value;
      }
    }
    return result;
  } catch {
    return null;
  }
}

const CHANNEL_OPTIONS = [
  "all",
  "console",
  "discord",
  "telegram",
  "dingtalk",
  "feishu",
  "imessage",
  "qq",
  "mattermost",
  "wecom",
  "mqtt",
];

export const MAX_TAGS = 8;
export const MAX_TAG_LENGTH = 16;

export interface SkillDrawerFormValues {
  name: string;
  description?: string;
  content: string;
  enabled?: boolean;
  channels?: string[];
  tags?: string[];
  source?: string;
  config?: Record<string, unknown>;
}

interface SkillDrawerProps {
  open: boolean;
  editingSkill: SkillSpec | null;
  form: UseFormReturn<SkillDrawerFormValues>;
  availableTags?: string[];
  onClose: () => void;
  onSubmit: (values: SkillSpec) => void;
  onContentChange?: (content: string) => void;
}

export function SkillDrawer({
  open,
  editingSkill,
  form,
  availableTags: _availableTags = [],
  onClose,
  onSubmit,
  onContentChange,
}: SkillDrawerProps) {
  const { t, i18n } = useTranslation();
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [contentValue, setContentValue] = useState("");
  const [optimizing, setOptimizing] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [configText, setConfigText] = useState("{}");
  const [configError, setConfigError] = useState("");
  const { message } = useAppMessage();

  useEffect(() => {
    if (editingSkill) {
      const channels = editingSkill.channels || ["all"];
      const fallbackConfigText = JSON.stringify(
        editingSkill.config || {},
        null,
        2,
      );
      setContentValue(editingSkill.content);
      setConfigText(fallbackConfigText);
      form.reset({
        name: editingSkill.name,
        content: editingSkill.content,
        channels,
        tags: editingSkill.tags || [],
        source: editingSkill.source,
      });
      setConfigError("");
      let active = true;
      api
        .getSkillConfig(editingSkill.name)
        .then((res) => {
          if (!active) return;
          setConfigText(JSON.stringify(res.config || {}, null, 2));
        })
        .catch(() => {
          if (!active) return;
          setConfigText(fallbackConfigText);
        });
      return () => {
        active = false;
      };
    } else {
      setContentValue("");
      setConfigText("{}");
      setConfigError("");
      form.reset();
    }
  }, [editingSkill, form, t]);

  const handleFormSubmit = form.handleSubmit(async (values) => {
    let parsedConfig: Record<string, unknown> | undefined;
    const trimmed = configText.trim();
    if (!trimmed) {
      parsedConfig = {};
    } else {
      try {
        parsedConfig = JSON.parse(trimmed);
        setConfigError("");
      } catch {
        setConfigError(t("skills.configInvalidJson"));
        return;
      }
    }
    onSubmit({
      ...editingSkill,
      ...values,
      content: contentValue || values.content,
      source: editingSkill?.source || "",
      config: parsedConfig,
    });
  });

  const handleContentChange = (content: string) => {
    setContentValue(content);
    form.setValue("content", content);
    if (onContentChange) {
      onContentChange(content);
    }
  };

  const handleOptimize = async () => {
    if (!contentValue.trim()) {
      message.warning(t("skills.noContentToOptimize"));
      return;
    }

    setOptimizing(true);
    abortControllerRef.current = new AbortController();
    const originalContent = contentValue;
    setContentValue("");

    try {
      await api.streamOptimizeSkill(
        originalContent,
        (textChunk) => {
          setContentValue((prev) => {
            const newContent = prev + textChunk;
            form.setValue("content", newContent);
            return newContent;
          });
        },
        abortControllerRef.current.signal,
        i18n.language,
      );
      message.success(t("skills.optimizeSuccess"));
    } catch (error: unknown) {
      const aborted =
        error instanceof DOMException && error.name === "AbortError";
      if (!aborted) {
        message.error(
          error instanceof Error ? error.message : t("skills.optimizeFailed"),
        );
      }
    } finally {
      setOptimizing(false);
      abortControllerRef.current = null;
    }
  };

  const handleStopOptimize = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setOptimizing(false);
      abortControllerRef.current = null;
    }
  };

  const channels = form.watch("channels") || [];

  const toggleChannel = (ch: string) => {
    const next = channels.includes(ch)
      ? channels.filter((c) => c !== ch)
      : [...channels, ch];
    form.setValue("channels", next);
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="w-[520px] sm:max-w-[520px] overflow-y-auto flex flex-col"
      >
        <SheetHeader>
          <SheetTitle>
            {editingSkill ? t("skills.viewSkill") : t("skills.createSkill")}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {editingSkill ? t("skills.viewSkill") : t("skills.createSkill")}
          </SheetDescription>
        </SheetHeader>

        <form
          id="skill-drawer-form"
          onSubmit={handleFormSubmit}
          className="flex-1 space-y-4 py-4"
        >
          <div className="space-y-1">
            <Label>Name</Label>
            <Input
              {...form.register("name", {
                required: !editingSkill
                  ? t("skills.pleaseInputName")
                  : undefined,
              })}
              disabled={Boolean(editingSkill)}
              placeholder={
                !editingSkill ? t("skills.skillNamePlaceholder") : undefined
              }
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">
                {form.formState.errors.name.message}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label>Content</Label>
            <MarkdownCopy
              content={contentValue}
              showMarkdown={showMarkdown}
              onShowMarkdownChange={setShowMarkdown}
              editable={true}
              onContentChange={handleContentChange}
              textareaProps={{
                ...(!editingSkill && {
                  placeholder: t("skills.contentPlaceholder"),
                }),
                rows: 12,
              }}
            />
          </div>

          <div className="space-y-1">
            <Label>{t("skills.channels")}</Label>
            <div className="flex flex-wrap gap-1">
              {CHANNEL_OPTIONS.map((ch) => (
                <button
                  key={ch}
                  type="button"
                  onClick={() => toggleChannel(ch)}
                  className={`rounded px-2 py-0.5 text-xs border transition-colors ${
                    channels.includes(ch)
                      ? "bg-primary text-primary-foreground border-primary"
                      : "border-muted-foreground/30 text-muted-foreground hover:border-primary"
                  }`}
                >
                  {ch}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1">
            <Label>{t("skills.config")}</Label>
            <Textarea
              rows={4}
              value={configText}
              onChange={(e) => {
                setConfigText(e.target.value);
                setConfigError("");
              }}
              placeholder={t("skills.configPlaceholder")}
            />
            {configError && (
              <p className="text-xs text-destructive">{configError}</p>
            )}
          </div>

          {editingSkill && (
            <>
              <div className="space-y-1">
                <Label>{t("skills.type")}</Label>
                <Input disabled value={editingSkill.source || ""} />
              </div>
              <div className="space-y-1">
                <Label>{t("skills.installedFrom")}</Label>
                <Input
                  disabled
                  value={deriveInstalledFromLabel(editingSkill.installed_from)}
                />
              </div>
            </>
          )}
        </form>

        <SheetFooter className="flex items-center justify-between gap-2 pt-2">
          {!editingSkill && (
            <div>
              {!optimizing ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleOptimize}
                  disabled={!contentValue.trim()}
                >
                  <Zap size={14} className="mr-1" />
                  {t("skills.optimizeWithAI")}
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={handleStopOptimize}
                >
                  <StopCircle size={14} className="mr-1" />
                  {t("skills.stopOptimize")}
                </Button>
              )}
            </div>
          )}
          <div className="flex gap-2 ml-auto">
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" form="skill-drawer-form">
              {editingSkill ? t("common.save") : t("skills.create")}
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
