import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from "@/components/ui/sheet";
import { useTranslation } from "react-i18next";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  deriveInstalledFromLabel,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import { MAX_TAGS, MAX_TAG_LENGTH } from "../../../Agent/Skills/components";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import type { PoolMode } from "../useSkillPool";
import styles from "../index.module.less";

interface PoolSkillDrawerFormRef {
  getName: () => string;
  setName: (v: string) => void;
  getTags: () => string[];
  setTags: (v: string[]) => void;
}

interface PoolSkillDrawerProps {
  mode: PoolMode | null;
  activeSkill: PoolSkillSpec | null;
  form: PoolSkillDrawerFormRef;
  drawerContent: string;
  showMarkdown: boolean;
  configText: string;
  availableTags?: string[];
  onClose: () => void;
  onSave: () => void;
  onContentChange: (content: string) => void;
  onShowMarkdownChange: (value: boolean) => void;
  onConfigTextChange: (text: string) => void;
  onChangeBuiltinLanguage?: (skill: PoolSkillSpec, language: string) => void;
  validateFrontmatter: (_: unknown, value: string) => Promise<void>;
}

function TagInput({
  values,
  onChange,
  suggestions,
  placeholder,
}: {
  values: string[];
  onChange: (vals: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
}) {
  const [inp, setInp] = useState("");

  const add = (val: string) => {
    const t = val.trim();
    if (
      t &&
      !values.includes(t) &&
      values.length < MAX_TAGS &&
      t.length <= MAX_TAG_LENGTH
    ) {
      onChange([...values, t]);
    }
    setInp("");
  };

  const remove = (v: string) => onChange(values.filter((x) => x !== v));

  return (
    <div className="flex flex-wrap gap-1 min-h-[36px] border rounded-md px-2 py-1 focus-within:ring-1 focus-within:ring-ring">
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1 bg-secondary text-secondary-foreground text-xs rounded px-2 py-0.5"
        >
          {v}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground leading-none"
            onClick={() => remove(v)}
          >
            ×
          </button>
        </span>
      ))}
      <input
        className="flex-1 min-w-[80px] outline-none text-sm bg-transparent"
        placeholder={placeholder}
        value={inp}
        list="tag-suggestions-pool"
        onChange={(e) => setInp(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add(inp);
          } else if (e.key === "Backspace" && !inp && values.length > 0) {
            remove(values[values.length - 1]);
          }
        }}
      />
      {suggestions && (
        <datalist id="tag-suggestions-pool">
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </div>
  );
}

export function PoolSkillDrawer({
  mode,
  activeSkill,
  form,
  drawerContent,
  showMarkdown,
  configText,
  availableTags = [],
  onClose,
  onSave,
  onContentChange,
  onShowMarkdownChange,
  onConfigTextChange,
  onChangeBuiltinLanguage,
}: PoolSkillDrawerProps) {
  const { t } = useTranslation();

  const isOpen = mode === "create" || mode === "edit";

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <SheetContent
        side="right"
        className="w-[520px] sm:w-[520px] flex flex-col"
      >
        <SheetHeader>
          <SheetTitle>
            {mode === "edit"
              ? t("skillPool.editTitle", { name: activeSkill?.name || "" })
              : t("skillPool.createTitle")}
          </SheetTitle>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto flex flex-col gap-4 py-4">
          {mode === "edit" && activeSkill && (
            <div className={`${styles.metaStack} flex flex-col gap-2 mb-2`}>
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>{t("skillPool.status")}</div>
                <div
                  className={`${styles.infoBlock} ${
                    styles[getPoolBuiltinStatusTone(activeSkill.sync_status)]
                  }`}
                >
                  {getPoolBuiltinStatusLabel(activeSkill.sync_status, t)}
                </div>
              </div>
              {isSkillBuiltin(activeSkill.source) &&
                (activeSkill.available_builtin_languages?.length ?? 0) > 1 &&
                onChangeBuiltinLanguage && (
                  <div className={styles.infoSection}>
                    <div className={styles.infoLabel}>
                      {t("skillPool.builtinLanguage")}
                    </div>
                    <div className={styles.languageToggle}>
                      {activeSkill.available_builtin_languages?.map((lang) => (
                        <Button
                          key={lang}
                          size="sm"
                          variant={
                            activeSkill.builtin_language === lang
                              ? "default"
                              : "outline"
                          }
                          onClick={() =>
                            void onChangeBuiltinLanguage(activeSkill, lang)
                          }
                        >
                          {lang === "zh" ? "中文" : "English"}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>
                  {t("skillPool.installedFrom")}
                </div>
                <div className={styles.infoBlock}>
                  {activeSkill.external && activeSkill.external_path
                    ? activeSkill.external_path
                    : deriveInstalledFromLabel(activeSkill.installed_from)}
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <Label>{t("skillPool.skillName")}</Label>
            <Input
              placeholder={t("skillPool.skillNamePlaceholder")}
              value={form.getName()}
              onChange={(e) => form.setName(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1">
            <MarkdownCopy
              content={drawerContent}
              showMarkdown={showMarkdown}
              onShowMarkdownChange={onShowMarkdownChange}
              editable={true}
              onContentChange={onContentChange}
              textareaProps={{
                placeholder: t("skillPool.contentPlaceholder"),
                rows: 12,
              }}
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("skillPool.tags")}</Label>
            <TagInput
              values={form.getTags()}
              onChange={form.setTags}
              suggestions={availableTags}
              placeholder={t("skillPool.tagsPlaceholder")}
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("skills.config")}</Label>
            <Textarea
              rows={4}
              value={configText}
              onChange={(e) => onConfigTextChange(e.target.value)}
              placeholder={t("skills.configPlaceholder")}
            />
          </div>
        </div>

        <SheetFooter className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={onSave}>
            {mode === "edit" ? t("common.save") : t("common.create")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
